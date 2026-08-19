#!/usr/bin/env python3
"""Generate the complete ZiloCart + ApBot project PDF from its Markdown source.

Run from the repository root:
    python Documentation/generate_documentation.py

ReportLab is intentionally the only non-project dependency used by this utility.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Documentation" / "ZiloCart_ApBot_Complete_Project_Documentation.md"
OUTPUT = ROOT / "Documentation" / "ZiloCart_ApBot_Project_Documentation.pdf"
LOGO = ROOT / "static" / "logo.png"

NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#155EEF")
CYAN = colors.HexColor("#0EA5E9")
TEAL = colors.HexColor("#0F766E")
ORANGE = colors.HexColor("#F97316")
AMBER = colors.HexColor("#FF9D00")
SOFT_ORANGE = colors.HexColor("#FFF4E8")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#5D6B82")
PALE = colors.HexColor("#EAF2FF")
LIGHT = colors.HexColor("#F5F7FB")
LINE = colors.HexColor("#D6DEEB")
WHITE = colors.white

# DejaVu improves Unicode coverage (en dash, multiplication sign, arrows).
font_dir = Path("/usr/share/fonts/truetype/dejavu")
if (font_dir / "DejaVuSans.ttf").exists():
    pdfmetrics.registerFont(TTFont("DejaVu", str(font_dir / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(font_dir / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuMono", str(font_dir / "DejaVuSansMono.ttf")))
    BODY_FONT, BOLD_FONT, MONO_FONT = "DejaVu", "DejaVu-Bold", "DejaVuMono"
else:
    BODY_FONT, BOLD_FONT, MONO_FONT = "Helvetica", "Helvetica-Bold", "Courier"


class ScreenshotPlaceholder(Flowable):
    """A clearly labelled frame that can be replaced by a final website capture."""

    def __init__(self, label: str, width: float = 158 * mm, height: float = 88 * mm):
        super().__init__()
        self.label = label
        self.width = width
        self.height = height

    def wrap(self, available_width, available_height):
        return min(self.width, available_width), self.height

    def draw(self):
        canvas = self.canv
        width, height = self.width, self.height
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#FFFBF6"))
        canvas.setStrokeColor(colors.HexColor("#F3AD62"))
        canvas.setLineWidth(1.1)
        canvas.roundRect(0, 0, width, height, 6, fill=1, stroke=1)
        canvas.setFillColor(ORANGE)
        canvas.roundRect(0, height - 5 * mm, width, 5 * mm, 6, fill=1, stroke=0)
        canvas.rect(0, height - 5 * mm, width, 2.5 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(colors.HexColor("#F6D6B5"))
        canvas.setDash(5, 4)
        canvas.line(10 * mm, 10 * mm, width - 10 * mm, height - 10 * mm)
        canvas.line(10 * mm, height - 10 * mm, width - 10 * mm, 10 * mm)
        canvas.setDash()
        canvas.setFillColor(NAVY)
        canvas.setFont(BOLD_FONT, 11)
        canvas.drawCentredString(width / 2, height / 2 + 6, "WEBSITE SCREENSHOT PLACEHOLDER")
        canvas.setFillColor(MUTED)
        canvas.setFont(BODY_FONT, 7.5)
        # Fit long captions to one centered line.
        label = self.label
        while canvas.stringWidth(label, BODY_FONT, 7.5) > width - 20 * mm and len(label) > 20:
            label = label[:-4].rstrip() + "..."
        canvas.drawCentredString(width / 2, height / 2 - 9, label)
        canvas.setFont(BODY_FONT, 7)
        canvas.drawCentredString(width / 2, 7 * mm, "Insert an authentic capture from the running ZiloCart application")
        canvas.restoreState()


class NumberedCanvasMixin:
    """Marker only; page furniture is supplied by the page template."""


class ReportDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=self.draw_page))
        self._bookmark_counter = 0

    def draw_page(self, canvas, doc):
        canvas.saveState()
        width, height = A4
        if doc.page == 1:
            canvas.setFillColor(NAVY)
            canvas.rect(0, 0, width, height, fill=1, stroke=0)
            canvas.setFillColor(ORANGE)
            canvas.rect(0, height - 8 * mm, width, 8 * mm, fill=1, stroke=0)
            canvas.setFillColor(AMBER)
            canvas.rect(0, 0, width, 6 * mm, fill=1, stroke=0)
            # Subtle brand rings provide depth without competing with the title.
            canvas.setStrokeColor(colors.Color(1, 1, 1, alpha=0.07))
            canvas.setLineWidth(1.2)
            for radius in (24, 38, 52):
                canvas.circle(width - 12 * mm, height - 48 * mm, radius * mm, fill=0, stroke=1)
        else:
            # Branded header with the real ZiloCart mark.
            if LOGO.exists():
                canvas.drawImage(ImageReader(str(LOGO)), self.leftMargin, height - 13.3 * mm,
                                 width=8.5 * mm, height=7.5 * mm, preserveAspectRatio=True,
                                 anchor="c", mask="auto")
            canvas.setFillColor(NAVY)
            canvas.setFont(BOLD_FONT, 7.4)
            canvas.drawString(self.leftMargin + 10.5 * mm, height - 10.8 * mm,
                              "ZILOCART  /  APBOT PROJECT DOCUMENTATION")
            canvas.setFillColor(MUTED)
            canvas.setFont(BODY_FONT, 7.2)
            canvas.drawRightString(width - self.rightMargin, height - 10.8 * mm,
                                   "VERSION 3.0  •  19 AUGUST 2026")
            canvas.setStrokeColor(ORANGE)
            canvas.setLineWidth(1.0)
            canvas.line(self.leftMargin, height - 15 * mm, width - self.rightMargin, height - 15 * mm)
            canvas.setStrokeColor(LINE)
            canvas.setLineWidth(0.5)
            canvas.line(self.leftMargin, 13 * mm, width - self.rightMargin, 13 * mm)
            canvas.setFillColor(MUTED)
            canvas.setFont(BODY_FONT, 7.1)
            canvas.drawString(self.leftMargin, 8.5 * mm, "AI/ML E-COMMERCE ASSISTANT  •  RECOMMENDATION SYSTEM")
            canvas.setFillColor(ORANGE)
            canvas.setFont(BOLD_FONT, 7.4)
            canvas.drawRightString(width - self.rightMargin, 8.5 * mm, f"{doc.page:02d}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            style_name = flowable.style.name
            if style_name in {"H1", "H2", "H3"}:
                level = {"H1": 0, "H2": 1, "H3": 2}[style_name]
                text = flowable.getPlainText()
                key = f"heading-{self._bookmark_counter}"
                self._bookmark_counter += 1
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)


def styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(
        "CoverKicker", parent=s["Normal"], fontName=BOLD_FONT, fontSize=10,
        leading=14, textColor=AMBER, alignment=TA_CENTER, spaceAfter=8,
    ))
    s.add(ParagraphStyle(
        "CoverTitle", parent=s["Title"], fontName=BOLD_FONT, fontSize=29,
        leading=35, textColor=WHITE, alignment=TA_CENTER, spaceAfter=9,
    ))
    s.add(ParagraphStyle(
        "CoverSubtitle", parent=s["Normal"], fontName=BODY_FONT, fontSize=13,
        leading=20, textColor=colors.HexColor("#DCE8FA"), alignment=TA_CENTER,
    ))
    s.add(ParagraphStyle(
        "CoverMeta", parent=s["Normal"], fontName=BODY_FONT, fontSize=9.5,
        leading=16, textColor=WHITE, alignment=TA_CENTER,
    ))
    s.add(ParagraphStyle(
        "H1", parent=s["Heading1"], fontName=BOLD_FONT, fontSize=18,
        leading=23, textColor=NAVY, spaceBefore=6, spaceAfter=8,
        keepWithNext=True,
    ))
    s.add(ParagraphStyle(
        "H2", parent=s["Heading2"], fontName=BOLD_FONT, fontSize=12.3,
        leading=16, textColor=colors.HexColor("#D95D00"), spaceBefore=8, spaceAfter=4,
        keepWithNext=True,
    ))
    s.add(ParagraphStyle(
        "H3", parent=s["Heading3"], fontName=BOLD_FONT, fontSize=10.5,
        leading=14, textColor=TEAL, spaceBefore=6, spaceAfter=3,
        keepWithNext=True,
    ))
    s.add(ParagraphStyle(
        "Body", parent=s["BodyText"], fontName=BODY_FONT, fontSize=8.9,
        leading=13.6, textColor=INK, spaceAfter=5.5, alignment=TA_LEFT,
    ))
    s.add(ParagraphStyle(
        "BulletCustom", parent=s["BodyText"], fontName=BODY_FONT, fontSize=8.75,
        leading=13.0, textColor=INK, leftIndent=11, firstLineIndent=-7,
        bulletIndent=1.5, spaceAfter=2.4,
    ))
    s.add(ParagraphStyle(
        "CodeCustom", parent=s["Code"], fontName=MONO_FONT, fontSize=7.1,
        leading=10, textColor=colors.HexColor("#E6EDF7"), backColor=NAVY,
        borderPadding=7, borderRadius=3, spaceBefore=4, spaceAfter=7,
    ))
    s.add(ParagraphStyle(
        "CaptionCustom", parent=s["Normal"], fontName=BODY_FONT, fontSize=7.6,
        leading=10, textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=8,
    ))
    s.add(ParagraphStyle(
        "TableHead", parent=s["Normal"], fontName=BOLD_FONT, fontSize=7.45,
        leading=9.8, textColor=WHITE,
    ))
    s.add(ParagraphStyle(
        "TableCell", parent=s["Normal"], fontName=BODY_FONT, fontSize=7.25,
        leading=9.7, textColor=INK,
    ))
    return s


STYLES = styles()


def inline_markup(text: str) -> str:
    """Escape text then support the small inline Markdown subset in the source."""
    value = html.escape(text.strip())
    value = re.sub(r"`([^`]+)`", r'<font name="%s" color="#0F766E">\1</font>' % MONO_FONT, value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    # Convert Markdown links to readable blue labels.
    value = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r'<font color="#155EEF">\1</font>', value)
    return value


def paragraph(text: str, style="Body") -> Paragraph:
    return Paragraph(inline_markup(text), STYLES[style])


def make_cover():
    cover: list[Flowable] = [Spacer(1, 21 * mm)]
    if LOGO.exists():
        logo = Image(str(LOGO), width=49 * mm, height=43 * mm)
        logo.hAlign = "CENTER"
        cover.extend([logo, Spacer(1, 6 * mm)])
    cover.extend([
        Paragraph("COMPLETE IMPLEMENTATION REPORT", STYLES["CoverKicker"]),
        Paragraph("ZiloCart", STYLES["CoverTitle"]),
        Paragraph("ApBot E-Commerce Assistant<br/>and Product Recommendation System", STYLES["CoverSubtitle"]),
        Spacer(1, 9 * mm),
        HRFlowable(width="50%", thickness=1.5, color=ORANGE, hAlign="CENTER"),
        Spacer(1, 8 * mm),
        Paragraph(
            "SRS Requirements • Full-Stack Design • Data Architecture<br/>"
            "Content, Collaborative & Hybrid Recommendations • ApBot Integration",
            STYLES["CoverMeta"],
        ),
        Spacer(1, 18 * mm),
        Paragraph("PROJECT TEAM", STYLES["CoverKicker"]),
        Paragraph("Mohammad Hamza • Ibrahim Bawany • Usman Bawany • Yousuf", STYLES["CoverMeta"]),
        Spacer(1, 10 * mm),
        Paragraph("Version 3.0  •  19 August 2026", STYLES["CoverMeta"]),
        Spacer(1, 3 * mm),
        Paragraph("Prepared against the supplied ApBot SRS and complete repository", STYLES["CoverMeta"]),
        PageBreak(),
    ])
    return cover


def parse_table(lines: list[str], available_width: float) -> Table:
    raw_rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        raw_rows.append(cells)
    # Remove Markdown separator row.
    if len(raw_rows) > 1 and all(re.fullmatch(r":?-{3,}:?", c) for c in raw_rows[1]):
        del raw_rows[1]
    ncols = max(len(r) for r in raw_rows)
    for row in raw_rows:
        row.extend([""] * (ncols - len(row)))
    data = []
    for ri, row in enumerate(raw_rows):
        style = "TableHead" if ri == 0 else "TableCell"
        data.append([Paragraph(inline_markup(cell), STYLES[style]) for cell in row])
    # Give first column slightly less width in common 2/3-column tables.
    if ncols == 2:
        col_widths = [available_width * 0.29, available_width * 0.71]
    elif ncols == 3:
        headers = [cell.strip().lower() for cell in raw_rows[0]]
        if headers[0] in {"id", "#"}:
            ratios = (0.12, 0.44, 0.44)
        elif headers[-1] == "resolution":
            ratios = (0.25, 0.35, 0.40)
        elif headers[-1] in {"status", "coverage"}:
            ratios = (0.22, 0.60, 0.18)
        else:
            ratios = (0.28, 0.44, 0.28)
        col_widths = [available_width * ratio for ratio in ratios]
    else:
        col_widths = [available_width / ncols] * ncols
    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
    ]))
    return table


def render_markdown() -> list[Flowable]:
    source_lines = SOURCE.read_text(encoding="utf-8").splitlines()
    # Everything through the first rule is represented by the designed cover.
    first_rule = source_lines.index("---")
    lines = source_lines[first_rule + 1 :]
    story: list[Flowable] = make_cover()
    paragraph_buffer: list[str] = []
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph():
        nonlocal paragraph_buffer
        if paragraph_buffer:
            text = " ".join(x.strip() for x in paragraph_buffer).strip()
            if text:
                story.append(paragraph(text))
            paragraph_buffer = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            if in_code:
                code = html.escape("\n".join(code_lines))
                story.append(Paragraph(code.replace("\n", "<br/>"), STYLES["CodeCustom"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if stripped == "[[PAGEBREAK]]":
            flush_paragraph()
            story.append(PageBreak())
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            story.extend([parse_table(table_lines, 166 * mm), Spacer(1, 5 * mm)])
            continue
        screenshot_match = re.fullmatch(r"\[\[SCREENSHOT:(.+)\]\]", stripped)
        if screenshot_match:
            flush_paragraph()
            story.extend([
                ScreenshotPlaceholder(screenshot_match.group(1).strip()),
                Paragraph(inline_markup(screenshot_match.group(1).strip()), STYLES["CaptionCustom"]),
            ])
            i += 1
            continue
        image_match = re.fullmatch(r"!\[([^]]+)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph()
            caption, relpath = image_match.groups()
            image_path = (SOURCE.parent / relpath).resolve()
            if image_path.exists():
                img = Image(str(image_path))
                max_w, max_h = 158 * mm, 112 * mm
                scale = min(max_w / img.imageWidth, max_h / img.imageHeight)
                img.drawWidth = img.imageWidth * scale
                img.drawHeight = img.imageHeight * scale
                img.hAlign = "CENTER"
                story.append(KeepTogether([img, Paragraph(inline_markup(caption), STYLES["CaptionCustom"])]))
            i += 1
            continue
        if stripped == "---":
            flush_paragraph()
            story.extend([Spacer(1, 2 * mm), HRFlowable(width="100%", thickness=0.6, color=LINE), Spacer(1, 3 * mm)])
        elif stripped.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[4:]), STYLES["H3"]))
        elif stripped.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[3:]), STYLES["H2"]))
        elif stripped.startswith("# "):
            flush_paragraph()
            # Keep a major heading with a useful amount of following content without
            # forcing sparse pages when the previous section ends near the top.
            if story and len(story) > len(make_cover()):
                story.append(CondPageBreak(58 * mm))
            story.append(Paragraph(inline_markup(stripped[2:]), STYLES["H1"]))
            story.append(HRFlowable(width="100%", thickness=1.35, color=ORANGE, spaceAfter=7))
        elif re.match(r"^[-*] ", stripped):
            flush_paragraph()
            story.append(Paragraph("• " + inline_markup(stripped[2:]), STYLES["BulletCustom"]))
        elif re.match(r"^\d+\. ", stripped):
            flush_paragraph()
            m = re.match(r"^(\d+)\. (.*)", stripped)
            story.append(Paragraph(f"<b>{m.group(1)}.</b> " + inline_markup(m.group(2)), STYLES["BulletCustom"]))
        elif not stripped:
            flush_paragraph()
        else:
            paragraph_buffer.append(line)
        i += 1
    flush_paragraph()
    return story


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = ReportDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="ZiloCart with ApBot — Complete Project and Recommendation System Documentation",
        author="Mohammad Hamza, Ibrahim Bawany, Usman Bawany, Yousuf",
        subject="Complete SRS, commerce, recommendation models and ApBot integration documentation",
        creator="ZiloCart documentation generator using ReportLab",
    )
    doc.build(render_markdown())
    print(f"Generated {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
