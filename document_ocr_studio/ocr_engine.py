from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class OCREngineError(RuntimeError):
    """Raised when deterministic OCR cannot run in the local environment."""


@dataclass(frozen=True)
class OCRWord:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block: int
    paragraph: int
    line: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def center_x(self) -> float:
        return self.left + (self.width / 2)


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    words: tuple[OCRWord, ...]

    @property
    def right(self) -> int:
        return self.left + self.width


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float
    words: tuple[OCRWord, ...]
    lines: tuple[OCRLine, ...]
    table_rows: tuple[tuple[str, ...], ...]
    key_values: tuple[tuple[str, str], ...]
    image_size: tuple[int, int]


def validate_image_path(path: str | Path) -> Path:
    image_path = Path(path)
    if not image_path.exists():
        raise OCREngineError(f"Image not found: {image_path}")
    if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
        supported = ", ".join(sorted(IMAGE_EXTENSIONS))
        raise OCREngineError(f"Unsupported image type. Use one of: {supported}")
    return image_path


def scan_image(path: str | Path, language: str = "eng") -> OCRResult:
    image_path = validate_image_path(path)
    pytesseract = _load_tesseract()
    processed, image_size = _preprocess_image(image_path)

    config = "--oem 3 --psm 6 -c preserve_interword_spaces=1"
    try:
        raw_data = pytesseract.image_to_data(
            processed,
            lang=language,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
        raw_text = pytesseract.image_to_string(
            processed,
            lang=language,
            config=config,
        ).strip()
    except Exception as exc:
        raise OCREngineError(f"Tesseract OCR failed: {exc}") from exc

    words = _parse_words(raw_data)
    lines = _build_lines(words)
    table_rows = _extract_table_rows(lines)
    key_values = _extract_key_values(lines)
    confidence = _average_confidence(words)
    text = raw_text or "\n".join(line.text for line in lines)

    if not text and not words:
        raise OCREngineError("No text was detected in the image.")

    return OCRResult(
        text=text,
        confidence=confidence,
        words=tuple(words),
        lines=tuple(lines),
        table_rows=tuple(tuple(row) for row in table_rows),
        key_values=tuple(key_values),
        image_size=image_size,
    )


def parse_text_to_grid(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    delimited = _parse_delimited_lines(lines)
    if delimited:
        return delimited

    spaced_rows = []
    split_count = 0
    for line in lines:
        cells = [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
        if len(cells) > 1:
            split_count += 1
        spaced_rows.append(cells if len(cells) > 1 else [line])

    max_cols = max(len(row) for row in spaced_rows)
    if max_cols > 1 and split_count >= 2:
        return _normalize_rows(spaced_rows)

    key_values = []
    for line in lines:
        match = re.match(r"^(.{1,80}?)(?:\s*[:=]\s+|\s{3,})(.+)$", line)
        if match:
            key_values.append([match.group(1).strip(), match.group(2).strip()])
    if key_values and len(key_values) >= max(2, len(lines) // 2):
        return [["Field", "Value"], *key_values]

    return [["Line", "Text"], *[[str(index + 1), line] for index, line in enumerate(lines)]]


def rows_to_tsv(rows: Iterable[Iterable[str]]) -> str:
    return "\n".join("\t".join(str(cell) for cell in row) for row in rows)


def write_rows_to_csv(path: str | Path, rows: Iterable[Iterable[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(list(row))


def _load_tesseract():
    try:
        import pytesseract
    except ImportError as exc:
        raise OCREngineError(
            "pytesseract is not installed. Install dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    configured = os.environ.get("TESSERACT_CMD", "").strip()
    common_paths = [
        configured,
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in common_paths:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            break

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise OCREngineError(
            "Tesseract OCR is not available. Install Tesseract OCR and make "
            "sure `tesseract.exe` is on PATH, or set TESSERACT_CMD to the "
            "full executable path."
        ) from exc
    return pytesseract


def _preprocess_image(image_path: Path):
    try:
        import cv2
    except ImportError as exc:
        raise OCREngineError(
            "opencv-python is not installed. Install dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    image = cv2.imread(str(image_path))
    if image is None:
        raise OCREngineError(f"Could not read image: {image_path}")

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    longest_edge = max(width, height)
    if longest_edge < 1800:
        scale = min(2.4, 1800 / max(1, longest_edge))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif longest_edge > 3600:
        scale = 3600 / longest_edge
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    denoised = cv2.fastNlMeansDenoising(gray, h=8)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    binary = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        12,
    )
    return binary, (width, height)


def _parse_words(raw_data: dict) -> list[OCRWord]:
    words: list[OCRWord] = []
    count = len(raw_data.get("text", []))
    for index in range(count):
        text = str(raw_data["text"][index] or "").strip()
        if not text:
            continue
        confidence = _parse_confidence(raw_data.get("conf", ["-1"])[index])
        if confidence < 0:
            continue
        words.append(
            OCRWord(
                text=text,
                confidence=confidence,
                left=int(raw_data["left"][index]),
                top=int(raw_data["top"][index]),
                width=int(raw_data["width"][index]),
                height=int(raw_data["height"][index]),
                block=int(raw_data.get("block_num", [0])[index]),
                paragraph=int(raw_data.get("par_num", [0])[index]),
                line=int(raw_data.get("line_num", [0])[index]),
            )
        )
    return words


def _parse_confidence(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _build_lines(words: list[OCRWord]) -> list[OCRLine]:
    grouped: dict[tuple[int, int, int], list[OCRWord]] = {}
    for word in words:
        grouped.setdefault((word.block, word.paragraph, word.line), []).append(word)

    lines: list[OCRLine] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda word: word.left)
        left = min(word.left for word in ordered)
        top = min(word.top for word in ordered)
        right = max(word.right for word in ordered)
        bottom = max(word.top + word.height for word in ordered)
        text = " ".join(word.text for word in ordered)
        lines.append(
            OCRLine(
                text=text,
                confidence=_average_confidence(ordered),
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
                words=tuple(ordered),
            )
        )
    return sorted(lines, key=lambda line: (line.top, line.left))


def _average_confidence(words: Iterable[OCRWord]) -> float:
    values = [word.confidence for word in words if word.confidence >= 0]
    return round(sum(values) / len(values), 1) if values else 0.0


def _extract_key_values(lines: Iterable[OCRLine]) -> list[tuple[str, str]]:
    key_values: list[tuple[str, str]] = []
    for line in lines:
        text = line.text.strip()
        match = re.match(r"^(.{1,80}?)(?:\s*[:=]\s+|\s{3,})(.+)$", text)
        if match:
            key = match.group(1).strip(" -:\t")
            value = match.group(2).strip()
            if key and value and len(key) <= 80:
                key_values.append((key, value))
    return key_values


def _extract_table_rows(lines: Iterable[OCRLine]) -> list[list[str]]:
    segmented_rows = []
    for line in lines:
        segments = _split_line_into_cells(line.words)
        if len(segments) >= 2:
            segmented_rows.append(segments)

    if len(segmented_rows) < 2:
        return []

    starts = sorted(segment["left"] for row in segmented_rows for segment in row)
    column_starts = _cluster_positions(starts)
    if len(column_starts) < 2:
        return []

    rows = []
    for segments in segmented_rows:
        row = [""] * len(column_starts)
        for segment in segments:
            column_index = min(
                range(len(column_starts)),
                key=lambda index: abs(column_starts[index] - segment["left"]),
            )
            row[column_index] = _join_cell(row[column_index], segment["text"])
        rows.append(row)

    rows = _drop_sparse_edges(rows)
    rows = _normalize_rows(rows)
    useful_rows = [row for row in rows if sum(bool(cell.strip()) for cell in row) >= 2]
    return useful_rows if len(useful_rows) >= 2 else []


def _split_line_into_cells(words: tuple[OCRWord, ...]) -> list[dict]:
    if len(words) < 2:
        return []

    ordered = sorted(words, key=lambda word: word.left)
    char_widths = [word.width / max(1, len(word.text)) for word in ordered]
    heights = [word.height for word in ordered]
    gap_threshold = max(20.0, median(char_widths) * 3.2, median(heights) * 1.25)

    groups: list[list[OCRWord]] = [[ordered[0]]]
    for word in ordered[1:]:
        previous = groups[-1][-1]
        gap = word.left - previous.right
        if gap > gap_threshold:
            groups.append([word])
        else:
            groups[-1].append(word)

    segments = []
    for group in groups:
        left = min(word.left for word in group)
        right = max(word.right for word in group)
        text = " ".join(word.text for word in group)
        segments.append({"left": left, "right": right, "text": text})
    return segments


def _cluster_positions(values: list[int]) -> list[int]:
    if not values:
        return []

    gaps = [b - a for a, b in zip(values, values[1:]) if b - a > 0]
    tolerance = max(28, int(median(gaps) * 0.45)) if gaps else 36
    clusters: list[list[int]] = []
    for value in values:
        if not clusters or abs(value - median(clusters[-1])) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [int(median(cluster)) for cluster in clusters]


def _join_cell(existing: str, value: str) -> str:
    if not existing:
        return value
    if not value:
        return existing
    return f"{existing} {value}"


def _drop_sparse_edges(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return rows
    max_cols = max(len(row) for row in rows)
    normalized = _normalize_rows(rows, max_cols)
    keep_indexes = []
    for index in range(max_cols):
        filled = sum(1 for row in normalized if row[index].strip())
        if filled >= 2 or filled / max(1, len(normalized)) >= 0.25:
            keep_indexes.append(index)
    if len(keep_indexes) < 2:
        return normalized
    return [[row[index] for index in keep_indexes] for row in normalized]


def _normalize_rows(rows: list[list[str]], width: int | None = None) -> list[list[str]]:
    max_cols = width or max((len(row) for row in rows), default=0)
    return [row + [""] * (max_cols - len(row)) for row in rows]


def _parse_delimited_lines(lines: list[str]) -> list[list[str]]:
    delimiters = ["\t", "|", ","]
    for delimiter in delimiters:
        if sum(delimiter in line for line in lines) < 2:
            continue
        parsed = []
        for line in lines:
            if delimiter == ",":
                parsed.extend(csv.reader([line]))
            else:
                parsed.append([cell.strip() for cell in line.split(delimiter)])
        widths = [len(row) for row in parsed]
        if max(widths, default=0) > 1 and len(set(widths)) <= 3:
            return _normalize_rows(parsed)
    return []
