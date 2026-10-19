"""Render the same course list as a legible, shareable PNG."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path


def render_report(report):
    from PIL import Image, ImageDraw, ImageFont

    candidates = [
        Path(os.environ.get("DUDUDA_HOMEWORK_FONT", "/nonexistent")),
        Path(sys.prefix).parent / "fonts/uming.ttc",
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
    ]
    font_path = next((p for p in candidates if p.is_file()), None)
    if font_path is None:
        raise ValueError("course_report_font_missing")
    fonts = {
        size: ImageFont.truetype(str(font_path), size, index=0)
        for size in (22, 26, 32, 44)
    }
    width, margin = 1120, 52
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def wrap(text, size, available):
        lines = []
        for paragraph in str(text).splitlines() or [""]:
            line = ""
            for char in paragraph:
                if (
                    line
                    and measure.textlength(line + char, font=fonts[size]) > available
                ):
                    lines.append(line)
                    line = ""
                line += char
            lines.append(line)
        return lines

    blocks, y = [], 190
    palette = ["#186b52", "#3d6591", "#984960", "#776324"]
    for index, section in enumerate(report["sections"]):
        heading = wrap(f"{index + 1:02d}  {section['title']}", 32, width - 2 * margin)
        blocks.append(("heading", y, heading, palette[index % len(palette)]))
        y += len(heading) * 44 + 16
        for line in section["lines"]:
            lines = wrap(line, 26, width - 2 * margin - 28)
            blocks.append(("body", y, lines, "#262d34"))
            y += len(lines) * 38 + 12
        blocks.append(("rule", y + 8, [], "#dbe0e4"))
        y += 42
    for note in report.get("notes", []):
        lines = wrap(note, 22, width - 2 * margin)
        blocks.append(("note", y, lines, "#65717a"))
        y += len(lines) * 32 + 8
    canvas = Image.new("RGB", (width, y + 40), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width, 145), fill="#edf3f1")
    draw.rectangle((0, 0, 12, 145), fill="#186b52")
    draw.text((margin, 30), report["title"], font=fonts[44], fill="#1c3229")
    draw.text((margin, 93), report["subtitle"], font=fonts[22], fill="#52675e")
    for kind, top, lines, color in blocks:
        if kind == "rule":
            draw.line((margin, top, width - margin, top), fill=color, width=1)
            continue
        size, height = (
            (32, 44) if kind == "heading" else (22, 32) if kind == "note" else (26, 38)
        )
        left = margin + 28 if kind == "body" else margin
        if kind == "body":
            draw.text((margin, top), "-", font=fonts[26], fill="#65717a")
        for line in lines:
            draw.text((left, top), line, font=fonts[size], fill=color)
            top += height
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
