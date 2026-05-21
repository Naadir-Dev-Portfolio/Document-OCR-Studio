from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "portfolio"
CARD = ROOT / "repo-card.png"


COLORS = {
    "bg": "#070909",
    "panel": "#0d1113",
    "panel_alt": "#111518",
    "panel_soft": "#182024",
    "border": "#232b2f",
    "accent": "#1fa99a",
    "accent_2": "#b8842a",
    "text": "#eef4f2",
    "muted": "#94a19d",
    "muted_2": "#65716d",
    "canvas": "#050708",
}


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_button(draw, xy, text, fill, color="#eef4f2", w=130):
    x, y = xy
    rounded(draw, (x, y, x + w, y + 42), 8, fill, None)
    draw.text((x + 18, y + 10), text, fill=color, font=font(15, True))


def draw_doc(draw, box):
    x1, y1, x2, y2 = box
    rounded(draw, box, 8, "#f7f8fb", "#d7dde6", 2)
    draw.text((x1 + 46, y1 + 48), "INVOICE", fill="#14213d", font=font(32, True))
    draw.text((x2 - 210, y1 + 52), "Invoice #  INV-0424", fill="#2b3440", font=font(14))
    draw.text((x2 - 210, y1 + 78), "Date       May 20, 2026", fill="#2b3440", font=font(14))
    draw.text((x1 + 46, y1 + 112), "Bill To:", fill="#2b3440", font=font(14, True))
    for i, line in enumerate(["Acme Corporation", "123 Business Rd.", "New York, NY 10001"]):
        draw.text((x1 + 46, y1 + 136 + i * 22), line, fill="#2b3440", font=font(14))

    table_x = x1 + 42
    table_y = y1 + 232
    col_widths = [55, 145, 55, 88, 88]
    headers = ["Item", "Description", "Qty", "Unit Price", "Amount"]
    rows = [
        ["1", "Website Design", "1", "$1,200.00", "$1,200.00"],
        ["2", "Development", "40", "$80.00", "$3,200.00"],
        ["3", "SEO Optimization", "1", "$600.00", "$600.00"],
    ]
    x = table_x
    for width, header in zip(col_widths, headers):
        draw.rectangle((x, table_y, x + width, table_y + 38), fill="#e8eef6", outline="#9aa8b8")
        draw.text((x + 8, table_y + 10), header, fill="#1c2733", font=font(11, True))
        x += width
    for r, row in enumerate(rows):
        y = table_y + 38 + r * 40
        x = table_x
        for width, cell in zip(col_widths, row):
            draw.rectangle((x, y, x + width, y + 40), fill="#ffffff", outline="#c7d0db")
            draw.text((x + 8, y + 12), cell, fill="#27323d", font=font(11))
            x += width
    draw.text((x1 + 46, y2 - 58), "Thank you for your business.", fill="#2b3440", font=font(13))


def draw_grid(draw, box):
    x1, y1, x2, y2 = box
    rounded(draw, box, 8, COLORS["panel_alt"], COLORS["border"], 1)
    draw.text((x1 + 18, y1 + 16), "Data Grid", fill=COLORS["text"], font=font(20, True))
    headers = ["Item", "Description", "Qty", "Unit Price", "Amount"]
    rows = [
        ["1", "Website Design", "1", "$1,200.00", "$1,200.00"],
        ["2", "Development", "40", "$80.00", "$3,200.00"],
        ["3", "SEO Optimization", "1", "$600.00", "$600.00"],
        ["", "Subtotal", "", "", "$5,000.00"],
        ["", "Tax 8.5%", "", "", "$425.00"],
    ]
    widths = [70, 210, 80, 130, 140]
    table_x = x1 + 18
    table_y = y1 + 64
    x = table_x
    for header, width in zip(headers, widths):
        draw.rectangle((x, table_y, x + width, table_y + 42), fill=COLORS["panel_soft"], outline=COLORS["border"])
        draw.text((x + 10, table_y + 12), header, fill=COLORS["text"], font=font(13, True))
        x += width
    for r, row in enumerate(rows):
        y = table_y + 42 + r * 42
        x = table_x
        for cell, width in zip(row, widths):
            fill = "#0f1517" if r % 2 else "#11181b"
            draw.rectangle((x, y, x + width, y + 42), fill=fill, outline="#252f33")
            draw.text((x + 10, y + 12), cell, fill=COLORS["text"], font=font(13))
            x += width
    draw.text((x1 + 18, y2 - 48), "Double-click cells to edit. Export edited rows to CSV.", fill=COLORS["muted"], font=font(15))


def build_screenshot(size=(1440, 900)) -> Image.Image:
    image = Image.new("RGB", size, COLORS["bg"])
    draw = ImageDraw.Draw(image)
    w, h = size

    draw.text((42, 34), "Document OCR Studio", fill=COLORS["text"], font=font(40, True))
    draw.text((44, 88), "Local OCR to editable text, sections and CSV-ready grids", fill=COLORS["muted"], font=font(20))
    draw_button(draw, (930, 42), "Open Image", COLORS["panel_soft"], w=150)
    draw_button(draw, (1096, 42), "Scan", COLORS["accent"], color="#061312", w=100)
    draw_button(draw, (1212, 42), "Export CSV", COLORS["panel_soft"], w=150)

    left = (42, 138, 650, 824)
    right = (680, 138, 1398, 824)
    rounded(draw, left, 10, COLORS["panel"], COLORS["border"], 2)
    rounded(draw, right, 10, COLORS["panel"], COLORS["border"], 2)
    draw.text((66, 160), "Original", fill=COLORS["text"], font=font(20, True))
    draw.text((704, 160), "Extracted Workspace", fill=COLORS["text"], font=font(20, True))
    draw_doc(draw, (92, 218, 600, 764))
    draw_grid(draw, (704, 218, 1374, 764))

    for x, label in [(704, "Text"), (792, "Data Grid"), (910, "Sections")]:
        fill = COLORS["panel_soft"] if label == "Data Grid" else COLORS["panel_alt"]
        rounded(draw, (x, 196, x + 104, 228), 6, fill, COLORS["border"], 1)
        draw.text((x + 16, 204), label, fill=COLORS["text"] if label == "Data Grid" else COLORS["muted"], font=font(13, True))

    draw.text((42, 852), "No cloud calls. No generative AI.", fill=COLORS["muted_2"], font=font(16))
    return image


def build_repo_card(source: Image.Image) -> Image.Image:
    card = Image.new("RGB", (1240, 560), "#050708")
    draw = ImageDraw.Draw(card)
    rounded(draw, (28, 28, 1212, 532), 22, "#0a0d0f", "#232b2f", 2)
    crop = source.resize((610, 382), Image.Resampling.LANCZOS)
    rounded(draw, (586, 82, 1168, 468), 16, "#111518", "#232b2f", 2)
    card.paste(crop.crop((0, 0, 582, 386)), (586, 82))
    draw.rectangle((586, 82, 1168, 468), outline="#232b2f", width=2)
    draw.text((78, 86), "Document OCR Studio", fill=COLORS["text"], font=font(48, True))
    draw.text((82, 166), "Local deterministic OCR for images,", fill=COLORS["muted"], font=font(24))
    draw.text((82, 200), "editable grids and CSV exports.", fill=COLORS["muted"], font=font(24))
    for i, tag in enumerate(["PYTHON", "OCR", "DESKTOP"]):
        x = 82 + i * 142
        rounded(draw, (x, 294, x + 118, 336), 8, "#111518", "#232b2f", 1)
        draw.text((x + 18, 305), tag, fill=COLORS["accent"], font=font(15, True))
    draw.text((82, 426), "Open image -> Scan -> Edit -> Export CSV", fill=COLORS["text"], font=font(22, True))
    return card


def main() -> None:
    PORTFOLIO.mkdir(exist_ok=True)
    screenshot = build_screenshot()
    screenshot.save(PORTFOLIO / "document-ocr-studio-full.png", optimize=True)
    screenshot.resize((1200, 960), Image.Resampling.LANCZOS).save(PORTFOLIO / "document-ocr-studio.png", optimize=True)
    screenshot.resize((1440, 660), Image.Resampling.LANCZOS).save(
        PORTFOLIO / "document-ocr-studio-featured.png",
        optimize=True,
    )
    build_repo_card(screenshot).save(CARD, optimize=True)


if __name__ == "__main__":
    main()
