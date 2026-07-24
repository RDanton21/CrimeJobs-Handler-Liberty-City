#!/usr/bin/env python3
"""Schlanker Markdown->PDF-Konverter mit reportlab (CYQORE-Look).

Aufruf:  python md_to_pdf.py QUELLE.md ZIEL.pdf ["Fusszeilen-Titel"]

Deckt die Elemente ab, die in den docs/*.md vorkommen: Ueberschriften
(#..####), Absaetze, **fett**, `code`, [links](x) (als Text, ohne URL),
- Listen, 1. Listen, > Blockquote, ```codebloecke```, | Tabellen |.

reportlab liegt nur im crime-backend-Container, nicht auf dem Host —
daher wird dieses Skript dort ausgefuehrt (siehe Memory crime-docs-pdf-rule).
"""
import re
import sys
import html

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Preformatted, HRFlowable, ListFlowable, ListItem,
)

SRC, OUT = sys.argv[1], sys.argv[2]
FOOTER_TITLE = sys.argv[3] if len(sys.argv) > 3 else "SEKT6R Crime Automation"

# Farben — an das dunkle CYQORE/Pink-Thema angelehnt, aber auf Weiss lesbar
PINK = colors.HexColor("#E7095B")
DARK = colors.HexColor("#1a1a1a")
GREY = colors.HexColor("#555555")
LIGHTBG = colors.HexColor("#f4f4f5")
BORDER = colors.HexColor("#d4d4d8")
CODEBG = colors.HexColor("#282a36")

ss = getSampleStyleSheet()
styles = {
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=20, spaceBefore=6,
                         spaceAfter=10, textColor=PINK, leading=24),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=15, spaceBefore=16,
                         spaceAfter=7, textColor=DARK, leading=19),
    "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontSize=12.5, spaceBefore=11,
                         spaceAfter=5, textColor=PINK, leading=16),
    "h4": ParagraphStyle("h4", parent=ss["Heading4"], fontSize=11, spaceBefore=9,
                         spaceAfter=4, textColor=DARK),
    "body": ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=14.5,
                           spaceAfter=6, textColor=DARK),
    "li": ParagraphStyle("li", parent=ss["BodyText"], fontSize=9.5, leading=14,
                         textColor=DARK),
    "quote": ParagraphStyle("quote", parent=ss["BodyText"], fontSize=9.5, leading=14.5,
                            leftIndent=10, textColor=GREY, borderPadding=(2, 2, 2, 8),
                            spaceAfter=6),
    "cell": ParagraphStyle("cell", parent=ss["BodyText"], fontSize=8.3, leading=11,
                           textColor=DARK),
    "cellh": ParagraphStyle("cellh", parent=ss["BodyText"], fontSize=8.3, leading=11,
                            textColor=colors.white, fontName="Helvetica-Bold"),
}


def inline(text):
    """Markdown-Inline -> reportlab-Mini-HTML."""
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`",
                  r'<font face="Courier" size="8.5" color="#c7254e">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  r'<font color="#185FA5">\1</font>', text)
    return text


def flush_para(buf, story):
    if buf:
        story.append(Paragraph(inline(" ".join(buf)), styles["body"]))
        buf.clear()


def make_table(rows):
    # rows: list of list[str]; erste Zeile Header, zweite ist Trennstrich (raus)
    header, *body = rows
    if body and all(set(c.strip()) <= set("-: ") for c in body[0] if c.strip() or True):
        body = body[1:]
    data = [[Paragraph(inline(c), styles["cellh"]) for c in header]]
    for r in body:
        data.append([Paragraph(inline(c), styles["cell"]) for c in r])
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PINK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHTBG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


lines = open(SRC, encoding="utf-8").read().split("\n")
story = []
para, tbl, code, lst = [], [], [], []
in_code = False
code_lang = ""

i = 0
while i < len(lines):
    line = lines[i]

    # Codeblock
    if line.strip().startswith("```"):
        if in_code:
            flush_para(para, story)
            story.append(Preformatted(
                "\n".join(code),
                ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=9.8,
                               textColor=colors.HexColor("#e6e6e6"), backColor=CODEBG,
                               borderPadding=(6, 6, 6, 6), leftIndent=0),
            ))
            story.append(Spacer(1, 6))
            code = []
            in_code = False
        else:
            flush_para(para, story)
            in_code = True
        i += 1
        continue
    if in_code:
        code.append(line)
        i += 1
        continue

    # Tabelle
    if line.strip().startswith("|") and "|" in line.strip()[1:]:
        tbl.append(split_row(line))
        i += 1
        continue
    elif tbl:
        flush_para(para, story)
        story.append(make_table(tbl))
        story.append(Spacer(1, 8))
        tbl = []

    stripped = line.strip()

    # Horizontale Linie
    if stripped in ("---", "***", "___"):
        flush_para(para, story)
        story.append(Spacer(1, 3))
        story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER))
        story.append(Spacer(1, 6))
        i += 1
        continue

    # Ueberschriften
    m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
    if m:
        flush_para(para, story)
        lvl = len(m.group(1))
        story.append(Paragraph(inline(m.group(2)), styles[f"h{lvl}"]))
        i += 1
        continue

    # Blockquote
    if stripped.startswith(">"):
        flush_para(para, story)
        story.append(Paragraph(inline(stripped.lstrip(">").strip()), styles["quote"]))
        i += 1
        continue

    # Listen (- oder 1.)
    m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
    if m:
        flush_para(para, story)
        story.append(Paragraph(inline(m.group(3)), styles["li"],
                               bulletText="•" if m.group(2) in "-*" else m.group(2)))
        i += 1
        continue

    # Leerzeile
    if not stripped:
        flush_para(para, story)
        i += 1
        continue

    para.append(stripped)
    i += 1

flush_para(para, story)
if tbl:
    story.append(make_table(tbl))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, 12 * mm, FOOTER_TITLE)
    canvas.drawRightString(190 * mm, 12 * mm, f"Seite {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=18 * mm, bottomMargin=18 * mm,
    title="Beziehungs-Erhebung", author="SEKT6R Crime Automation",
)
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("PDF erzeugt:", OUT)
