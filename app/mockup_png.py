"""Render a mockup tree as a PNG wireframe, on the server.

The browser draws mockups as DOM (public/js/mockup/render.js); this draws the
same component tree as an image, for downloads and for the Agile Tracker,
which only accepts pictures. It is a small layout engine: components stack
top to bottom, grids share a row, text wraps. Grey on white, like the page.

Every renderer takes (node, x, y, width) and returns the height it used; with
`draw=None` it only measures, so containers can size themselves first.
"""
from __future__ import annotations

import io
import math
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .mockups import Annotation, Component, Tree

WIDTH = 1024
PAD = 24
GAP = 14
MAX_HEIGHT = 8000
INK, LINE, SOFT, MUTED, WHITE = (43, 47, 51), (154, 160, 166), (236, 238, 240), (107, 113, 120), (255, 255, 255)

FONT_CANDIDATES = {
    "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf"],
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "/Library/Fonts/Arial Bold.ttf"],
}


@lru_cache(maxsize=32)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """A system font when there is one, else Pillow's bundled font (no bold, same glyphs)."""
    configured = os.environ.get("MOCKUP_FONT_BOLD" if bold else "MOCKUP_FONT", "").strip()
    for path in [configured, *FONT_CANDIDATES["bold" if bold else "regular"]]:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def wrap(text: str, fnt: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if fnt.getlength(candidate) <= width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


class Painter:
    def __init__(self, draw: ImageDraw.ImageDraw | None):
        self.d = draw
        self.boxes: dict[str, tuple[float, float, float, float]] = {}  # id -> x, y, w, h

    # --- primitives -------------------------------------------------------

    def text(self, x, y, width, value, size=14, bold=False, fill=INK, underline=False) -> int:
        fnt = font(size, bold)
        line_height = int(size * 1.4)
        lines = wrap(value, fnt, width)
        if self.d:
            for i, line in enumerate(lines):
                self.d.text((x, y + i * line_height), line, font=fnt, fill=fill)
                if underline:
                    w = fnt.getlength(line)
                    base = y + i * line_height + size + 2
                    self.d.line((x, base, x + w, base), fill=fill)
        return line_height * len(lines)

    def box(self, x, y, w, h, fill=None, outline=LINE, dashed=False, radius=4) -> None:
        if not self.d:
            return
        if dashed:
            self.d.rounded_rectangle((x, y, x + w, y + h), radius, fill=fill)
            for start, end, fixed, horizontal in ((x, x + w, y, True), (x, x + w, y + h, True),
                                                  (y, y + h, x, False), (y, y + h, x + w, False)):
                for pos in range(int(start), int(end), 8):
                    seg = (pos, fixed, min(pos + 4, end), fixed) if horizontal else (fixed, pos, fixed, min(pos + 4, end))
                    self.d.line(seg, fill=outline)
        else:
            self.d.rounded_rectangle((x, y, x + w, y + h), radius, fill=fill, outline=outline)

    # Ticks and carets are drawn as shapes: not every system font has the glyphs.
    def tick(self, x, y, size=10, fill=MUTED) -> None:
        if self.d:
            self.d.line((x, y + size * 0.55, x + size * 0.4, y + size, x + size, y), fill=fill, width=2)

    def caret(self, x, y, fill=MUTED) -> None:
        if self.d:
            self.d.polygon((x, y, x + 10, y, x + 5, y + 6), fill=fill)

    def button(self, x, y, label, variant) -> tuple[int, int]:
        fnt = font(14, variant != "link")
        w = int(fnt.getlength(label)) + (0 if variant == "link" else 28)
        if variant == "link":
            self.text(x, y, w + 4, label, underline=True)
            return w, 20
        if self.d:
            primary = variant in (None, "primary")
            self.d.rounded_rectangle((x, y, x + w, y + 32), 4, fill=INK if primary else WHITE, outline=INK)
            self.d.text((x + 14, y + 7), label, font=fnt, fill=WHITE if primary else INK)
        return w, 32

    # --- components -------------------------------------------------------

    def stack(self, nodes: list[Component], x, y, w, gap=10) -> int:
        top = y
        for i, node in enumerate(nodes):
            y += self.node(node, x, y, w) + (gap if i < len(nodes) - 1 else 0)
        return y - top

    def node(self, n: Component, x, y, w, min_height: int = 0) -> int:
        method = getattr(self, f"c_{n.type}", self.c_text)
        h = method(n, x, y, w, min_height) if n.type in ("card", "price_card") else method(n, x, y, w)
        self.boxes[n.id] = (x, y, w, h)
        return h

    def c_header(self, n, x, y, w):
        inner = self.inline(n.children or [], x, y, w - 32, measure_only=True)
        h = max(48, inner + 20)
        self.box(x, y, w, h, fill=SOFT)
        self.text(x + 14, y + (h - 20) // 2, w / 3, n.text or "", bold=True)
        width = self.inline_width(n.children or [])
        self.inline(n.children or [], x + w - 14 - width, y + (h - 32) // 2, width)
        return h

    def inline_width(self, nodes) -> int:
        total = 0
        for c in nodes:
            if c.type == "nav":
                total += sum(int(font(14).getlength(i)) + 16 for i in c.items or [])
            elif c.type == "button":
                total += int(font(14, c.variant != "link").getlength(c.text or "")) + 28 + 12
        return total

    def inline(self, nodes, x, y, w, measure_only=False) -> int:
        """Header contents in one row: nav links and buttons."""
        if measure_only:
            return 32
        cx = x
        for c in nodes:
            start = cx
            if c.type == "nav":
                for item in c.items or []:
                    self.text(cx, y + 7, 400, item, underline=True)
                    cx += int(font(14).getlength(item)) + 16
            elif c.type == "button":
                bw, _ = self.button(cx, y, c.text or "", c.variant)
                cx += bw + 12
            self.boxes[c.id] = (start, y, cx - start, 32)
        return 32

    def c_nav(self, n, x, y, w):
        cx, row, h = x, y, 20
        for item in n.items or []:
            iw = int(font(14).getlength(item)) + 16
            if cx + iw > x + w and cx > x:
                cx, row = x, row + 24
            self.text(cx, row, iw, item, underline=True)
            cx += iw
        return row - y + h

    def c_heading(self, n, x, y, w):
        return self.text(x, y, w, n.text or "", size={1: 26, 2: 20, 3: 16}[n.level or 2], bold=True)

    def c_text(self, n, x, y, w):
        return self.text(x, y, w, n.text or n.secondary or f"[{n.type}]")

    def c_note(self, n, x, y, w):
        return self.text(x, y, w, n.text or "", size=12, fill=MUTED)

    def c_image(self, n, x, y, w):
        h = 140
        self.box(x, y, w, h, fill=(247, 248, 249))
        if self.d:
            self.d.line((x, y, x + w, y + h), fill=LINE)
            self.d.line((x, y + h, x + w, y), fill=LINE)
            label = n.text or ""
            lw = font(12).getlength(label)
            self.d.rectangle((x + w / 2 - lw / 2 - 6, y + h / 2 - 10, x + w / 2 + lw / 2 + 6, y + h / 2 + 10), fill=(247, 248, 249))
            self.d.text((x + w / 2 - lw / 2, y + h / 2 - 8), label, font=font(12), fill=MUTED)
        return h

    def _card_body(self, n, x, y, w, price=False) -> int:
        top = y
        if n.text:
            y += self.text(x, y, w, n.text, bold=True) + 4
        if price and n.secondary:
            y += self.text(x, y, w, n.secondary, size=20, bold=True) + 4
        elif n.secondary:
            y += self.text(x, y, w, n.secondary, fill=MUTED) + 4
        if price:
            for item in n.items or []:
                self.tick(x, y + 4)
                y += self.text(x + 18, y, w - 18, item, size=13) + 2
        if n.children:
            y += 6 + self.stack(n.children, x, y, w, gap=8)
        return y - top

    def c_card(self, n, x, y, w, min_height=0, price=False):
        h = max(min_height, Painter(None)._card_body(n, x + 12, y + 12, w - 24, price) + 24)
        self.box(x, y, w, h)
        self._card_body(n, x + 12, y + 12, w - 24, price)
        return h

    def c_price_card(self, n, x, y, w, min_height=0):
        return self.c_card(n, x, y, w, min_height, price=True)

    def c_grid(self, n, x, y, w):
        cols = max(1, min(n.columns or 3, 4))
        gap = 12
        cw = (w - gap * (cols - 1)) / cols
        children = n.children or []
        top = y
        for start in range(0, len(children), cols):
            row = children[start:start + cols]
            heights = [Painter(None).node(c, 0, 0, cw) for c in row]
            rh = max(heights)
            for i, c in enumerate(row):
                self.node(c, x + i * (cw + gap), y, cw, min_height=rh)
            y += rh + gap
        return y - top - gap if children else 0

    def c_list(self, n, x, y, w):
        top = y
        for item in n.items or []:
            y += self.text(x + 8, y, w - 8, f"•  {item}") + 2
        return y - top

    def c_table(self, n, x, y, w):
        cols = n.items or []
        if not cols:
            return 0
        cw = w / len(cols)
        top = y
        for r, row in enumerate([cols, *(n.rows or [])]):
            heights = [Painter(None).text(0, 0, cw - 16, cell, bold=r == 0) for cell in row]
            rh = max(heights) + 12
            for i, cell in enumerate(row):
                self.box(x + i * cw, y, cw, rh, fill=SOFT if r == 0 else None, radius=0)
                self.text(x + i * cw + 8, y + 6, cw - 16, cell, bold=r == 0)
            y += rh
        return y - top

    def c_form(self, n, x, y, w):
        inner = Painter(None)._form_body(n, x + 12, y + 12, w - 24)
        h = inner + 24
        self.box(x, y, w, h, dashed=True)
        self._form_body(n, x + 12, y + 12, w - 24)
        return h

    def _form_body(self, n, x, y, w):
        top = y
        if n.text:
            y += self.text(x, y, w, n.text, bold=True) + 6
        return y - top + self.stack(n.children or [], x, y, w, gap=10)

    def c_input(self, n, x, y, w):
        label = (n.text or "") + (" *" if n.required else "")
        if n.variant == "checkbox":
            self.box(x, y + 3, 14, 14, outline=INK, radius=2)
            return max(20, self.text(x + 22, y, w - 22, label, size=13, bold=True))
        top = y
        y += self.text(x, y, w, label, size=13, bold=True) + 4
        fh = 64 if n.variant == "textarea" else 32
        self.box(x, y, w, fh, fill=WHITE, radius=3)
        if n.secondary:
            self.text(x + 8, y + 8, w - 32, n.secondary, size=13, fill=(163, 168, 173))
        if n.variant == "select":
            self.caret(x + w - 22, y + 13)
        return y + fh - top

    def c_button(self, n, x, y, w):
        return self.button(x, y, n.text or "", n.variant)[1]

    def c_footer(self, n, x, y, w):
        if self.d:
            self.d.line((x, y, x + w, y), fill=LINE)
        h = 10 + self.text(x + 12, y + 10, w - 24, n.text or "", size=12, fill=MUTED)
        if n.children:
            h += 8 + self.stack(n.children, x + 12, y + h + 8, w - 24)
        return h + 8

    def c_section(self, n, x, y, w):
        top = y
        if n.text:
            y += self.text(x, y, w, n.text.upper(), size=12, bold=True, fill=MUTED) + 6
        return y - top + self.stack(n.children or [], x, y, w)

    def c_notice(self, n, x, y, w):
        icons = {"warning": "!", "error": "×"}
        inner = Painter(None).text(0, 0, w - 60, n.text or "")
        h = max(40, inner + 20)
        self.box(x, y, w, h, fill=SOFT)
        if self.d:
            self.d.rectangle((x, y, x + 4, y + h), fill=INK)
            self.d.ellipse((x + 16, y + h / 2 - 10, x + 36, y + h / 2 + 10), outline=INK)
            if n.variant == "success":
                self.tick(x + 21, y + h / 2 - 5, size=10, fill=INK)
            else:
                self.d.text((x + 23, y + h / 2 - 9), icons.get(n.variant or "", "i"), font=font(13, True), fill=INK)
        self.text(x + 46, y + (h - inner) // 2, w - 60, n.text or "")
        return h

    def c_steps(self, n, x, y, w):
        cx = x
        for i, item in enumerate(n.items or []):
            label = f"{i + 1}. {item}"
            pw = int(font(12).getlength(label)) + 20
            if self.d:
                self.d.rounded_rectangle((cx, y, cx + pw, y + 24), 12, outline=LINE)
                self.d.text((cx + 10, y + 5), label, font=font(12), fill=INK)
            cx += pw + 6
        return 24


MARK_COLORS = {"red": (224, 49, 49), "blue": (28, 126, 214), "green": (47, 158, 68)}
NOTE_FILL = (255, 243, 191)


def absolute(mark: Annotation, boxes: dict[str, tuple[float, float, float, float]]) -> list[tuple[float, float]]:
    """A mark's points on this rendering: relative to its anchor's box, or to the view."""
    ox, oy = boxes[mark.anchor][:2] if mark.anchor in boxes else (0, 0)
    return [(ox + x, oy + y) for x, y in mark.points]


def draw_marks(draw: ImageDraw.ImageDraw, marks: list[Annotation], boxes) -> None:
    for mark in marks:
        points = absolute(mark, boxes)
        color = MARK_COLORS[mark.color]
        if mark.tool == "rect":
            (x1, y1), (x2, y2) = points
            draw.rectangle((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)), outline=color, width=3)
        elif mark.tool == "pen":
            draw.line(points, fill=color, width=3, joint="curve")
        elif mark.tool == "arrow":
            (x1, y1), (x2, y2) = points
            draw.line((x1, y1, x2, y2), fill=color, width=3)
            angle = math.atan2(y2 - y1, x2 - x1)
            for side in (-0.5, 0.5):
                draw.line((x2, y2, x2 - 14 * math.cos(angle + side), y2 - 14 * math.sin(angle + side)), fill=color, width=3)
        elif mark.tool == "note":
            (x, y), fnt = points[0], font(13)
            lines = wrap(mark.text or "", fnt, 200)
            h = 10 + 18 * len(lines)
            draw.rectangle((x, y, x + 216, y + h), fill=NOTE_FILL, outline=color, width=2)
            for i, line in enumerate(lines):
                draw.text((x + 8, y + 5 + i * 18), line, font=fnt, fill=INK)


def render_png(tree: Tree, annotations: list[Annotation] | None = None) -> bytes:
    """The whole view as PNG bytes, as tall as its content (and its annotations)."""
    width = WIDTH - 2 * PAD
    measure = Painter(None)
    height = PAD * 2 + measure.stack(tree.components, PAD, PAD, width, gap=GAP)
    for mark in annotations or []:  # a mark below the content makes the image taller
        lowest = max(y for _, y in absolute(mark, measure.boxes))
        height = max(height, int(lowest) + (120 if mark.tool == "note" else 20))
    height = min(MAX_HEIGHT, height)
    image = Image.new("RGB", (WIDTH, height), WHITE)
    painter = Painter(ImageDraw.Draw(image))
    painter.stack(tree.components, PAD, PAD, width, gap=GAP)
    draw_marks(ImageDraw.Draw(image), annotations or [], painter.boxes)
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
