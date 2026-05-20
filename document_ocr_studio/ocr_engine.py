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
    candidates, image_size = _preprocess_candidates(image_path)
    config = "--oem 3 --psm 6 -c preserve_interword_spaces=1"

    best_result = None
    last_error: Exception | None = None
    for _name, processed in candidates:
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
            last_error = exc
            continue

        words = _parse_words(raw_data)
        lines = _build_lines(words)
        table_rows = _extract_table_rows(lines)
        key_values = _extract_key_values(lines)
        confidence = _average_confidence(words)
        text = raw_text or "\n".join(line.text for line in lines)
        score = _score_ocr_candidate(text, words, lines, table_rows)

        candidate = (score, text, confidence, words, lines, table_rows, key_values)
        if best_result is None or candidate[0] > best_result[0]:
            best_result = candidate

    if best_result is None:
        raise OCREngineError(f"Tesseract OCR failed: {last_error}") from last_error

    _, text, confidence, words, lines, table_rows, key_values = best_result

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


def _preprocess_candidates(image_path: Path):
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

    candidates = [("gray", gray)]

    longest_edge = max(width, height)
    if longest_edge < 1400:
        scale = min(2.4, 1800 / max(1, longest_edge))
        candidates.append(("scaled-gray", cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)))

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates.append(("otsu", otsu))

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
    candidates.append(("adaptive", binary))
    return candidates, (width, height)


def _score_ocr_candidate(
    text: str,
    words: Iterable[OCRWord],
    lines: Iterable[OCRLine],
    table_rows: Iterable[Iterable[str]],
) -> float:
    line_list = list(lines)
    word_list = list(words)
    table_list = [list(row) for row in table_rows]
    date_lines = sum(1 for line in line_list if _line_starts_with_date(line))
    money_words = sum(1 for word in word_list if _looks_like_money(word.text))
    header_bonus = 0
    text_lower = text.lower()
    for keyword in ("date", "description", "withdraw", "deposit", "balance"):
        if keyword in text_lower:
            header_bonus += 8
    table_bonus = len(table_list) * 6
    width_bonus = max((len(row) for row in table_list), default=0) * 4
    junk_penalty = len(re.findall(r"[_\[\]{}|]{2,}", text)) * 2
    return _average_confidence(word_list) + date_lines * 10 + money_words * 1.5 + header_bonus + table_bonus + width_bonus - junk_penalty


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
    financial_rows = _extract_financial_statement_rows(lines)
    if financial_rows:
        return financial_rows

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


def _extract_financial_statement_rows(lines: Iterable[OCRLine]) -> list[list[str]]:
    line_list = list(lines)
    dated_lines = [line for line in line_list if _line_starts_with_date(line)]
    if len(dated_lines) < 3:
        return []

    numeric_columns = _financial_numeric_columns(dated_lines)
    if len(numeric_columns) < 2:
        return []

    labels = _financial_column_labels(numeric_columns)
    headers = ["Date", "Description", "Ref.", "Withdrawals", "Deposits", "Balance"]
    rows = [headers]

    for line in dated_lines:
        row = _financial_row_from_line(line, numeric_columns, labels)
        if row:
            rows.append(row)

    for line in line_list:
        if "total" not in line.text.lower():
            continue
        row = _financial_total_row_from_line(line, numeric_columns, labels)
        if row:
            rows.append(row)

    return rows if len(rows) > 2 else []


def _financial_numeric_columns(lines: list[OCRLine]) -> list[float]:
    description_start = _median_description_start(lines)
    right_edge = max((word.right for line in lines for word in line.words), default=0)
    min_numeric_x = description_start + max(160, (right_edge - description_start) * 0.36)
    positions = []
    for line in lines:
        for word in line.words:
            if word.center_x < min_numeric_x:
                continue
            if _looks_like_money(word.text) or _looks_like_ref(word.text):
                positions.append(int(word.center_x))
    return [float(pos) for pos in _cluster_positions(sorted(positions))]


def _financial_column_labels(columns: list[float]) -> dict[int, str]:
    if len(columns) >= 4:
        selected = columns[-4:]
        return {
            columns.index(selected[0]): "Ref.",
            columns.index(selected[1]): "Withdrawals",
            columns.index(selected[2]): "Deposits",
            columns.index(selected[3]): "Balance",
        }
    if len(columns) == 3:
        return {0: "Withdrawals", 1: "Deposits", 2: "Balance"}
    return {len(columns) - 2: "Deposits", len(columns) - 1: "Balance"}


def _financial_row_from_line(
    line: OCRLine,
    columns: list[float],
    labels: dict[int, str],
) -> list[str] | None:
    words = sorted(line.words, key=lambda word: word.left)
    if not words:
        return None

    date = _extract_date(words[0].text)
    if not date:
        return None

    cells = {"Date": date, "Description": "", "Ref.": "", "Withdrawals": "", "Deposits": "", "Balance": ""}
    description_words: list[str] = []
    for word in words[1:]:
        column_index = _nearest_financial_column(word, columns)
        label = labels.get(column_index) if column_index is not None else None
        if label and (_looks_like_money(word.text) or _looks_like_ref(word.text)):
            cells[label] = _join_cell(cells[label], _clean_financial_value(word.text, label))
        else:
            description_words.append(word.text)

    cells["Description"] = _clean_description(" ".join(description_words))
    if not cells["Description"] and not any(cells[key] for key in ("Ref.", "Withdrawals", "Deposits", "Balance")):
        return None
    return [cells["Date"], cells["Description"], cells["Ref."], cells["Withdrawals"], cells["Deposits"], cells["Balance"]]


def _financial_total_row_from_line(
    line: OCRLine,
    columns: list[float],
    labels: dict[int, str],
) -> list[str] | None:
    cells = {"Date": "", "Description": "", "Ref.": "", "Withdrawals": "", "Deposits": "", "Balance": ""}
    description_words: list[str] = []
    for word in sorted(line.words, key=lambda item: item.left):
        column_index = _nearest_financial_column(word, columns)
        label = labels.get(column_index) if column_index is not None else None
        if label and _looks_like_money(word.text):
            cells[label] = _join_cell(cells[label], _clean_financial_value(word.text, label))
        elif not _looks_like_money(word.text):
            description_words.append(word.text)
    cells["Description"] = _clean_description(" ".join(description_words)) or "Totals"
    return [cells["Date"], cells["Description"], cells["Ref."], cells["Withdrawals"], cells["Deposits"], cells["Balance"]]


def _line_starts_with_date(line: OCRLine) -> bool:
    if not line.words:
        return False
    return bool(_extract_date(line.words[0].text))


def _extract_date(value: str) -> str:
    match = re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", value)
    return match.group(0).replace("/", "-") if match else ""


def _median_description_start(lines: list[OCRLine]) -> float:
    starts = []
    for line in lines:
        words = sorted(line.words, key=lambda word: word.left)
        if len(words) >= 2:
            starts.append(words[1].left)
    return float(median(starts)) if starts else 0.0


def _nearest_financial_column(word: OCRWord, columns: list[float]) -> int | None:
    if not columns:
        return None
    distances = [abs(word.center_x - column) for column in columns]
    nearest_index = min(range(len(columns)), key=lambda index: distances[index])
    gaps = [b - a for a, b in zip(columns, columns[1:]) if b - a > 0]
    tolerance = max(56.0, (median(gaps) * 0.42) if gaps else 64.0)
    return nearest_index if distances[nearest_index] <= tolerance else None


def _looks_like_ref(value: str) -> bool:
    cleaned = re.sub(r"\D", "", value)
    return bool(re.fullmatch(r"\d{3,6}", cleaned))


def _looks_like_money(value: str) -> bool:
    text = _normalize_ocr_number_text(value)
    return bool(re.search(r"\d+[,.]\d{2}", text))


def _clean_financial_value(value: str, label: str) -> str:
    if label == "Ref.":
        return re.sub(r"\D", "", value)

    text = _normalize_ocr_number_text(value)
    negative = text.startswith("-") or text.startswith("~") or text.startswith("−")
    text = text.lstrip("-~−")
    text = re.sub(r"[^0-9,.\s]", "", text).strip()
    text = re.sub(r"\s+", "", text)

    if "," in text and "." not in text:
        head, tail = text.rsplit(",", 1)
        if len(tail) == 2:
            text = f"{head}.{tail}"
    if text.count(".") > 1:
        first, *rest = text.split(".")
        text = first + "." + "".join(rest)

    if negative:
        text = f"-{text}"
    return text


def _normalize_ocr_number_text(value: str) -> str:
    return (
        value.strip()
        .replace("§", "5")
        .replace("з", "5")
        .replace("З", "5")
        .replace("−", "-")
        .replace("—", "-")
        .replace("_", "")
        .replace("[", "")
        .replace("]", "")
        .replace("|", "")
    )


def _clean_description(value: str) -> str:
    text = value.replace("_", " ").replace("|", " ").replace("[", " ").replace("]", " ")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"^[=\-.\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("** Totals ***", "*** Totals ***")
    return text


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
