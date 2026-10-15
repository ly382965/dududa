"""Render submission PDFs in the isolated worker, with embedded Chinese text."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def render_pdf(content: str) -> bytes:
    from markdown_it import MarkdownIt
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    candidates = [
        Path(os.environ.get("DUDUDA_HOMEWORK_FONT", "/nonexistent")),
        Path(sys.prefix).parent / "fonts/uming.ttc",
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
    ]
    font = next((path for path in candidates if path.is_file()), None)
    if font is None:
        raise ValueError("homework_pdf_font_missing")
    name = "HomeworkCJK"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(font), subfontIndex=0))
        pdfmetrics.registerFontFamily(
            name, normal=name, bold=name, italic=name, boldItalic=name
        )
    body = ParagraphStyle(
        "Body", fontName=name, fontSize=11, leading=18, wordWrap="CJK", spaceAfter=8
    )
    heading = ParagraphStyle(
        "Heading",
        parent=body,
        fontSize=14,
        leading=22,
        spaceBefore=10,
        keepWithNext=True,
    )
    title = ParagraphStyle(
        "Title", parent=heading, fontSize=17, leading=25, spaceAfter=14
    )
    code = ParagraphStyle(
        "Code",
        parent=body,
        fontSize=9,
        leading=13,
        backColor=colors.HexColor("#f3f4f5"),
    )
    cell = ParagraphStyle("Cell", parent=body, fontSize=9, leading=14, spaceAfter=2)

    def inline(tokens):
        parts = []
        links = []
        for token in tokens or []:
            if token.type in {"text", "code_inline", "html_inline"}:
                parts.append(escape(token.content))
            elif token.type in {"softbreak", "hardbreak"}:
                parts.append("<br/>")
            elif token.type in {"strong_open", "strong_close", "em_open", "em_close"}:
                parts.append(
                    {
                        "strong_open": "<b>",
                        "strong_close": "</b>",
                        "em_open": "<i>",
                        "em_close": "</i>",
                    }[token.type]
                )
            elif token.type == "image":
                raise ValueError("homework_pdf_image_requires_review")
            elif token.type == "link_open":
                links.append(token.attrGet("href") or "")
            elif token.type == "link_close" and links:
                parts.append(" (" + escape(links.pop()) + ")")
        return "".join(parts)

    tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(content)
    story, lists = [], []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            rows, row = [], []
            index += 1
            while tokens[index].type != "table_close":
                current = tokens[index]
                if current.type == "tr_open":
                    row = []
                elif current.type == "inline":
                    row.append(Paragraph(inline(current.children), cell))
                elif current.type == "tr_close":
                    rows.append(row)
                index += 1
            if rows:
                table = Table(
                    rows,
                    colWidths=[(A4[0] - 100) / len(rows[0])] * len(rows[0]),
                    repeatRows=1,
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cdd2")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f5")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.extend([table, Spacer(1, 8)])
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            lists.append(
                None
                if token.type == "bullet_list_open"
                else int(token.attrGet("start") or 1)
            )
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
        elif token.type == "inline":
            previous = tokens[index - 1]
            style = (
                title
                if previous.tag == "h1"
                else heading
                if previous.type == "heading_open"
                else body
            )
            text = inline(token.children)
            if (
                lists
                and previous.type == "paragraph_open"
                and index >= 2
                and tokens[index - 2].type == "list_item_open"
            ):
                prefix = "- " if lists[-1] is None else f"{lists[-1]}. "
                text = prefix + text
                if lists[-1] is not None:
                    lists[-1] += 1
            story.append(Paragraph(text, style))
        elif token.type in {"fence", "code_block"}:
            for line in token.content.rstrip("\n").split("\n"):
                story.append(
                    Paragraph(escape(line).replace(" ", "&#160;") or "&#160;", code)
                )
        elif token.type == "hr":
            story.append(Spacer(1, 10))
        index += 1
    if not story:
        raise ValueError("homework_pdf_empty")
    buffer = io.BytesIO()

    def footer(canvas, doc):
        canvas.setFont(name, 9)
        canvas.drawCentredString(A4[0] / 2, 27, str(doc.page))

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=42,
        bottomMargin=45,
        title=content.splitlines()[0].lstrip("# "),
        author="",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
