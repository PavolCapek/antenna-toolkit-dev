#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import fitz

fitz.TOOLS.mupdf_display_errors(False)
fitz.TOOLS.mupdf_display_warnings(False)

THIS_DIR = Path(__file__).resolve().parent
MYRIAD_FONT_DIR = THIS_DIR / "Fonts" / "Myriad Pro"
MYRIAD_FONT_FILES = {
    "MyriadPro-Regular": MYRIAD_FONT_DIR / "MYRIADPRO-REGULAR.OTF",
    "MyriadPro-Bold": MYRIAD_FONT_DIR / "MYRIADPRO-BOLD.OTF",
    "MyriadPro-Semibold": MYRIAD_FONT_DIR / "MYRIADPRO-SEMIBOLD.OTF",
    "MyriadPro-Light": MYRIAD_FONT_DIR / "MyriadPro-Light.otf",
    "MyriadPro-Cond": MYRIAD_FONT_DIR / "MYRIADPRO-COND.OTF",
    "MyriadPro-BoldCond": MYRIAD_FONT_DIR / "MYRIADPRO-BOLDCOND.OTF",
    "MyriadPro-BoldCondIt": MYRIAD_FONT_DIR / "MYRIADPRO-BOLDCONDIT.OTF",
    "MyriadPro-BoldIt": MYRIAD_FONT_DIR / "MYRIADPRO-BOLDIT.OTF",
    "MyriadPro-CondIt": MYRIAD_FONT_DIR / "MYRIADPRO-CONDIT.OTF",
    "MyriadPro-SemiboldIt": MYRIAD_FONT_DIR / "MYRIADPRO-SEMIBOLDIT.OTF",
}
LOREM_WORDS = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt "
    "ut labore et dolore magna aliqua"
).split()
TITLE_TEXT = "Antenna name"


@dataclass(frozen=True)
class TextSpan:
    text: str
    bbox: fitz.Rect
    origin: tuple[float, float]
    font: str
    size: float
    color: tuple[float, float, float]
    direction: tuple[float, float]


class LoremGenerator:
    def __init__(self) -> None:
        self._index = 0

    def next_text(self, original: str, *, uppercase: bool = False) -> str:
        stripped = original.strip()
        if not stripped:
            return original
        if stripped == "Product Datasheet":
            return "Lorem ipsum"
        if stripped == "Product ID:":
            return "Dolor sit:"
        if stripped == "AH60WB":
            return "Amet"
        if stripped.lower() == "www.rfelements.com":
            return "loremipsum.com"

        prefix = ""
        if stripped.startswith("\u2022"):
            prefix = "\u2022 "
            stripped = stripped[1:].strip()

        target = max(1, len(stripped))
        if target <= 4:
            text = "lore"[:target]
        else:
            parts: list[str] = []
            total = 0
            while total < target:
                word = LOREM_WORDS[self._index % len(LOREM_WORDS)]
                self._index += 1
                addition = word if not parts else f" {word}"
                if total + len(addition) > target + 3 and parts:
                    break
                parts.append(addition)
                total += len(addition)
            text = "".join(parts).strip()
            if len(text) > target:
                text = text[:target].rstrip()
            if not text:
                text = "lorem"[:target]

        if uppercase:
            text = text.upper()
        return f"{prefix}{text}".strip()


def _font_path(display_font: str) -> Path | None:
    path = MYRIAD_FONT_FILES.get(display_font)
    if path and path.exists():
        return path
    return None


def _resolve_font_name(page: fitz.Page, display_font: str) -> str:
    matches: list[str] = []
    type1_matches: list[str] = []
    for font in page.get_fonts(full=True):
        base_font = str(font[3] or "")
        resource_name = str(font[4] or "")
        if not resource_name:
            continue
        if base_font == display_font or base_font.endswith(f"+{display_font}"):
            matches.append(resource_name)
            if resource_name.startswith("T1_"):
                type1_matches.append(resource_name)
    if type1_matches:
        return type1_matches[0]
    if matches:
        return matches[0]
    return "helv"


def _measure_font(font_name: str, font_path: Path | None) -> fitz.Font:
    try:
        if font_path is not None:
            return fitz.Font(fontfile=str(font_path))
        return fitz.Font(fontname=font_name)
    except Exception:
        return fitz.Font(fontname="helv")


def _extract_spans(page: fitz.Page) -> list[TextSpan]:
    spans: list[TextSpan] = []
    seen: set[tuple[object, ...]] = set()
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            direction = tuple(float(value) for value in line.get("dir", (1.0, 0.0)))
            for span in line.get("spans", []):
                text = str(span.get("text", "")).strip()
                if not text:
                    continue
                bbox = fitz.Rect(span["bbox"])
                key = (
                    text,
                    str(span.get("font", "helv")),
                    round(float(span.get("size", 7.0)), 2),
                    round(bbox.x0, 1),
                    round(bbox.y0, 1),
                    round(bbox.x1, 1),
                    round(bbox.y1, 1),
                )
                if key in seen:
                    continue
                seen.add(key)
                color = int(span.get("color", 0))
                spans.append(
                    TextSpan(
                        text=text,
                        bbox=bbox,
                        origin=tuple(float(v) for v in span.get("origin", (span["bbox"][0], span["bbox"][3] - 1.0))),
                        font=str(span.get("font", "helv")),
                        size=float(span.get("size", 7.0)),
                        color=((color >> 16 & 0xFF) / 255.0, (color >> 8 & 0xFF) / 255.0, (color & 0xFF) / 255.0),
                        direction=direction,
                    )
                )
    return spans


def _rotation_for_direction(direction: tuple[float, float]) -> int:
    rounded = (round(direction[0], 3), round(direction[1], 3))
    if rounded == (1.0, 0.0):
        return 0
    if rounded == (0.0, -1.0):
        return 90
    if rounded == (-1.0, 0.0):
        return 180
    if rounded == (0.0, 1.0):
        return 270
    return 0


def _max_text_extent(span: TextSpan) -> float:
    rotation = _rotation_for_direction(span.direction)
    if rotation in {90, 270}:
        return max(1.0, span.bbox.height + 1.0)
    return max(1.0, span.bbox.width + 1.0)


def _placeholder_text(span: TextSpan, lorem: LoremGenerator, *, page_number: int) -> str:
    if page_number == 0 and span.size >= 20:
        return TITLE_TEXT
    uppercase = span.text.isupper() and any(ch.isalpha() for ch in span.text)
    return lorem.next_text(span.text, uppercase=uppercase)


def _fit_text(span: TextSpan, text: str, font_name: str, font_path: Path | None) -> tuple[str, float]:
    font = _measure_font(span.font, font_path)
    max_extent = _max_text_extent(span)
    fitted = text.strip() or "l"
    size = span.size
    while fitted and font.text_length(fitted, fontsize=size) > max_extent:
        fitted = fitted[:-1].rstrip()
    if not fitted:
        fitted = "l"
    while size > max(span.size * 0.75, 4.0) and font.text_length(fitted, fontsize=size) > max_extent:
        size -= 0.25
    return fitted, size


def _insert_known_font(page: fitz.Page, font_name: str) -> tuple[str, str | None]:
    font_path = _font_path(font_name)
    if font_path is not None:
        page.insert_font(fontname=font_name, fontfile=str(font_path))
        return font_name, str(font_path)
    return "helv", None


def _rewrite_header_metadata(page: fitz.Page) -> None:
    page.draw_rect(fitz.Rect(28.0, 40.0, 140.0, 70.0), color=None, fill=(1.0, 1.0, 1.0), overlay=True)
    semibold_name, semibold_file = _insert_known_font(page, "MyriadPro-Semibold")
    light_name, light_file = _insert_known_font(page, "MyriadPro-Light")
    regular_name, regular_file = _insert_known_font(page, "MyriadPro-Regular")
    page.insert_text((35.0, 54.0), "Lorem ipsum", fontsize=12.0, fontname=semibold_name, fontfile=semibold_file, color=(0.35, 0.35, 0.35))
    page.insert_text((35.0, 66.0), "Dolor sit:", fontsize=8.0, fontname=light_name, fontfile=light_file, color=(0.55, 0.55, 0.55))
    page.insert_text((71.0, 66.0), "Amet", fontsize=8.0, fontname=regular_name, fontfile=regular_file, color=(0.35, 0.35, 0.35))


def build_datasheet_template_pdf(template: Path, output: Path) -> Path:
    template = template.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lorem = LoremGenerator()

    with fitz.open(template) as doc:
        for page_number, page in enumerate(doc):
            spans = _extract_spans(page)
            replacements = [(span, _placeholder_text(span, lorem, page_number=page_number)) for span in spans]
            registered_fonts: set[str] = set()

            for span, _ in replacements:
                expand = 1.0 if _rotation_for_direction(span.direction) else 0.6
                rect = fitz.Rect(span.bbox.x0 - expand, span.bbox.y0 - 0.5, span.bbox.x1 + expand, span.bbox.y1 + 0.5)
                page.add_redact_annot(rect, fill=(1.0, 1.0, 1.0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            for span, replacement in replacements:
                rotation = _rotation_for_direction(span.direction)
                font_path = _font_path(span.font)
                font_name = span.font
                fontfile = None
                if font_path is not None:
                    fontfile = str(font_path)
                    if font_name not in registered_fonts:
                        page.insert_font(fontname=font_name, fontfile=fontfile)
                        registered_fonts.add(font_name)
                else:
                    font_name = _resolve_font_name(page, span.font)
                fitted_text, fontsize = _fit_text(span, replacement, font_name, font_path)
                page.insert_text(
                    span.origin,
                    fitted_text,
                    fontsize=fontsize,
                    fontname=font_name,
                    fontfile=fontfile,
                    color=span.color,
                    rotate=rotation,
                )
            _rewrite_header_metadata(page)

        doc.save(output, garbage=3, deflate=True)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a lorem ipsum datasheet template PDF.")
    parser.add_argument(
        "--template",
        type=Path,
        default=THIS_DIR / "Datasheet.pdf",
        help="Source PDF to transform.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=THIS_DIR / "Datasheet_template.pdf",
        help="Output PDF path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_datasheet_template_pdf(template=args.template, output=args.output)
    print(f"Wrote template PDF to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
