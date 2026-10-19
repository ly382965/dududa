"""Affinity card renderer. Runs under a Pillow-capable interpreter (``python -I render.py``).

Reads one JSON request from stdin and writes a PNG to stdout. Kept free of Host imports.
Request: {"kind": "ranking"|"all", "fonts": {"regular": path, "bold": path}, ...}; see ``main``.
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys

from PIL import Image, ImageDraw, ImageFont

S = 2  # Render at 2x so QQ previews stay sharp.
W = 720
BG = (255, 250, 247)
PANEL = (255, 255, 255)
BORDER = (238, 226, 222)
TEXT = (51, 43, 48)
MUTED = (150, 138, 144)
ACCENT = (232, 106, 166)
TIERS = {
    "讨厌": (214, 86, 86),
    "不反感": (232, 160, 72),
    "普通": (150, 150, 158),
    "喜欢": (96, 170, 220),
    "非常喜欢": (232, 106, 166),
    "最喜欢的姐姐": (205, 84, 160),
}
BANDS = [(-100, -51, "讨厌"), (-50, -11, "不反感"), (-10, 30, "普通"), (31, 60, "喜欢"), (61, 100, "非常喜欢")]
# Noto Sans CJK has no emoji glyphs; drop them instead of drawing empty boxes.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u20E3]")


def drawable(value: str) -> str:
    return EMOJI.sub("", value).strip()


class Canvas:
    def __init__(self, height: int, fonts: dict):
        self.image = Image.new("RGB", (W * S, height * S), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = fonts
        self._cache: dict[tuple, ImageFont.FreeTypeFont] = {}

    def font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        key = (size, bold)
        if key not in self._cache:
            path = self.fonts.get("bold" if bold else "regular") or self.fonts.get("regular")
            self._cache[key] = ImageFont.truetype(path, size * S)
        return self._cache[key]

    def text(self, xy, value, size=14, fill=TEXT, bold=False, anchor="la"):
        value = drawable(value) or "?"
        self.draw.text((xy[0] * S, xy[1] * S), value, font=self.font(size, bold), fill=fill, anchor=anchor)

    def rect(self, box, fill=None, outline=None, radius=0, width=1):
        self.draw.rounded_rectangle([v * S for v in box], radius=radius * S, fill=fill, outline=outline,
                                    width=width * S)

    def fit(self, value: str, size: int, limit: float, bold: bool = False) -> str:
        font = self.font(size, bold)
        if font.getlength(value) <= limit * S:
            return value
        while value and font.getlength(value + "…") > limit * S:
            value = value[:-1]
        return value + "…"

    def avatar(self, center, radius, data: str | None, name: str, color):
        x, y = center
        box = [round((x - radius) * S), round((y - radius) * S), round((x + radius) * S), round((y + radius) * S)]
        size = radius * 2 * S
        picture = None
        if data:
            try:
                picture = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB").resize((size, size))
            except Exception:  # noqa: BLE001 -- A broken avatar falls back to initials.
                picture = None
        if picture is not None:
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
            self.image.paste(picture, (box[0], box[1]), mask)
        else:
            self.draw.ellipse(box, fill=tuple(int(c * 0.25 + 255 * 0.75) for c in color))
            self.text((x, y), (name or "?")[:1], size=int(radius * 0.95), fill=color, bold=True, anchor="mm")
        self.draw.ellipse(box, outline=BORDER, width=S)

    def png(self) -> bytes:
        buffer = io.BytesIO()
        self.image.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()


def score_text(score: float) -> str:
    return str(round(score))


def row(canvas: Canvas, x, y, width, item):
    color = TIERS.get(item["tier"], MUTED)
    canvas.avatar((x + 16, y), 14, item.get("avatar"), item["name"], color)
    canvas.text((x + 40, y), str(item["rank"]), size=13, fill=MUTED, anchor="lm")
    name = canvas.fit(item["name"], 14, width - 190)
    canvas.text((x + 66, y), name, size=14, anchor="lm")
    canvas.text((x + width, y), f"{score_text(item['score'])} {item['tier']}", size=14, fill=color, bold=True,
                anchor="rm")


def ranking(request: dict) -> bytes:
    split = not request.get("single")
    rows = max(len(request["top"]), len(request["low"])) if split else max(1, len(request["top"]))
    pinned = request.get("pinned")
    top_y = 70 + (54 if pinned else 0)
    list_height = 30 + rows * 38
    height = top_y + list_height + 74
    canvas = Canvas(height, request["fonts"])
    canvas.rect([12, 12, W - 12, height - 12], fill=PANEL, outline=BORDER, radius=22, width=2)
    canvas.text((40, 48), "嘟嘟哒的亲密度排行", size=22, bold=True, anchor="ls")
    canvas.text((W - 40, 48), f"{request['title']} · 共 {request['count']} 人", size=13, fill=MUTED, anchor="rs")
    if pinned:
        color = TIERS["最喜欢的姐姐"]
        canvas.rect([40, 66, W - 40, 106], outline=color, radius=12, width=2)
        canvas.avatar((62, 86), 13, pinned.get("avatar"), pinned["name"], color)
        canvas.text((84, 86), canvas.fit(pinned["name"], 15, 300), size=15, fill=color, bold=True, anchor="lm")
        canvas.text((W - 58, 86), "最喜欢的姐姐 · 120", size=15, fill=color, bold=True, anchor="rm")
    if split:
        canvas.text((40, top_y + 18), "最亲近 Top 5", size=15, fill=TIERS["非常喜欢"], bold=True, anchor="ls")
        canvas.text((376, top_y + 18), "最疏远 Low 5", size=15, fill=TIERS["讨厌"], bold=True, anchor="ls")
        for index, item in enumerate(request["top"]):
            row(canvas, 40, top_y + 46 + index * 38, 300, item)
        for index, item in enumerate(request["low"]):
            row(canvas, 376, top_y + 46 + index * 38, 304, item)
    else:
        canvas.text((40, top_y + 18), "本群排行", size=15, fill=ACCENT, bold=True, anchor="ls")
        for index, item in enumerate(request["top"]):
            row(canvas, 40, top_y + 46 + index * 38, W - 80, item)
        if not request["top"]:
            canvas.text((40, top_y + 46), "还没有群友上榜，多来找嘟嘟哒聊天吧～", size=14, fill=MUTED, anchor="lm")
    legend(canvas, top_y + list_height + 36)
    return canvas.png()


def legend(canvas: Canvas, y: int) -> None:
    canvas.draw.line([(40 * S, (y - 22) * S), ((W - 40) * S, (y - 22) * S)], fill=BORDER, width=2 * S)
    x = 40
    for low, high, label in BANDS:
        color = TIERS[label]
        canvas.draw.ellipse([x * S, (y - 5) * S, (x + 10) * S, (y + 5) * S], fill=color)
        caption = f"{label} {low}~{high}"
        canvas.text((x + 16, y), caption, size=11, fill=MUTED, anchor="lm")
        x += 22 + canvas.font(11).getlength(caption) / S + 18

def everyone(request: dict) -> bytes:
    """Every person in two columns, highest first."""
    items = request["items"]
    per_column = max(1, (len(items) + 1) // 2)
    row_height = 44
    pinned = request.get("pinned")
    pinned_height = 54 if pinned else 0
    top_y = 104 + pinned_height
    height = top_y + per_column * row_height + 80
    canvas = Canvas(height, request["fonts"])
    canvas.rect([12, 12, W - 12, height - 12], fill=PANEL, outline=BORDER, radius=22, width=2)
    canvas.text((40, 48), request.get("title") or "全部亲密度", size=22, bold=True, anchor="ls")
    canvas.text((W - 40, 48), f"共 {request['count']} 人", size=13, fill=MUTED, anchor="rs")
    if pinned:
        color = TIERS["最喜欢的姐姐"]
        canvas.rect([40, 66, W - 40, 106], outline=color, radius=12, width=2)
        canvas.avatar((62, 86), 13, pinned.get("avatar"), pinned["name"], color)
        canvas.text((84, 86), canvas.fit(pinned["name"], 15, 300), size=15, fill=color, bold=True, anchor="lm")
        canvas.text((W - 58, 86), "最喜欢的姐姐 · 120", size=15, fill=color, bold=True, anchor="rm")
    counts_y = 80 + pinned_height
    x = 40
    for label, count in request["counts"].items():
        caption = f"{label} {count}"
        canvas.text((x, counts_y), caption, size=13, fill=TIERS[label], bold=True, anchor="ls")
        x += canvas.font(13, True).getlength(caption) / S + 22
    if not items:
        canvas.text((40, top_y + 20), "还没有任何亲密度记录。", size=14, fill=MUTED, anchor="lm")
    for index, item in enumerate(items):
        column, line = divmod(index, per_column)
        left = 40 + column * 336
        y = top_y + line * row_height + row_height / 2
        color = TIERS.get(item["tier"], MUTED)
        canvas.avatar((left + 14, y), 13, item.get("avatar"), item["name"], color)
        canvas.text((left + 34, y), str(item["rank"]), size=12, fill=MUTED, anchor="lm")
        canvas.text((left + 62, y - 8), canvas.fit(item["name"], 13, 150), size=13, anchor="lm")
        canvas.text((left + 62, y + 10), item["qq"], size=10, fill=MUTED, anchor="lm")
        canvas.text((left + 304, y), f"{item['score']:.1f} {item['tier']}", size=13, fill=color, bold=True,
                    anchor="rm")
    legend(canvas, height - 40)
    return canvas.png()


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    png = ranking(request) if request["kind"] == "ranking" else everyone(request)
    sys.stdout.buffer.write(png)


if __name__ == "__main__":
    main()
