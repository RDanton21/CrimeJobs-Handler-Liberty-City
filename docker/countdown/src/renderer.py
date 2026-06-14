"""SEKTOR-Countdown-Karte (Pillow).

render_card() erzeugt ein PNG im SEKTOR-Design: dunkle Card, NR.-Badge,
Titel/Subtitle, drei Zeit-Boxen (Tage/Std/Min). Wird vom Bot ins Discord-Embed
eingebettet.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ASSETS = Path(__file__).parent / "assets"

# ── SEKTOR-Design-Tokens ─────────────────────────────────
S = 3                       # Supersampling
LW, LH = 900, 416           # Karte fuellt das Embed nahezu komplett
W, H = LW * S, LH * S


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


CARD   = _hex("110b1f")
CARD2  = _hex("17112a")
BORDER = _hex("2c2c4a")
PINK   = _hex("e64560")
CYAN   = _hex("02eaff")
PURPLE = _hex("7040c0")
TEXT   = _hex("f5f3ff")
MUTED  = _hex("9aa0b4")


def _font(names: list[str], size: int):
    """Schriftart laden — erst assets/, dann Windows-Segoe, dann Default."""
    candidates: list[Path] = []
    for n in names:
        candidates.append(ASSETS / n)
        candidates.append(Path(r"C:\Windows\Fonts") / n)
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size * S)
            except Exception:
                continue
    return ImageFont.load_default()


F_NUM   = _font(["Inter-Light.ttf", "segoeuil.ttf", "segoeui.ttf"], 74)
F_TITLE = _font(["Inter-Light.ttf", "segoeuil.ttf", "segoeui.ttf"], 47)
F_SUB   = _font(["Inter-Regular.ttf", "segoeui.ttf"], 19)
F_BADGE = _font(["Inter-SemiBold.ttf", "seguisb.ttf", "segoeuib.ttf", "segoeui.ttf"], 15)
F_DATE  = _font(["Inter-Regular.ttf", "segoeui.ttf"], 17)
F_LABEL = _font(["Inter-Regular.ttf", "segoeui.ttf"], 14)
F_LIVE  = _font(["Inter-SemiBold.ttf", "seguisb.ttf", "segoeuib.ttf", "segoeui.ttf"], 52)


def _hgrad(w: int, h: int, stops: list[tuple]) -> Image.Image:
    """Horizontaler Mehrstop-Verlauf."""
    g = Image.new("RGB", (max(w, 1), max(h, 1)))
    px = g.load()
    n = len(stops) - 1
    for x in range(g.width):
        t = x / max(g.width - 1, 1) * n
        i = min(int(t), n - 1)
        f = t - i
        c1, c2 = stops[i], stops[i + 1]
        col = tuple(int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3))
        for y in range(g.height):
            px[x, y] = col
    return g


def _tracked(d: ImageDraw.ImageDraw, cx: float, y: float, text: str,
             fnt, fill, track: float) -> None:
    """Zentrierter Text mit Buchstaben-Abstand."""
    track *= S
    widths = [d.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=fnt, fill=fill)
        x += w + track


def _ctext(d: ImageDraw.ImageDraw, cx: float, cy: float, text: str, fnt, fill) -> None:
    """Text um (cx, cy) zentriert."""
    b = d.textbbox((0, 0), text, font=fnt)
    d.text((cx - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]),
           text, font=fnt, fill=fill)


def render_card(now: datetime, target: datetime, *,
                badge: str, title: str, subtitle: str, date_str: str) -> io.BytesIO:
    """SEKTOR-Countdown-Karte rendern. Drei Boxen: Tage / Std / Min."""
    live = now >= target
    secs = max(0, int((target - now).total_seconds()))
    days = secs // 86400
    hours = (secs % 86400) // 3600
    minutes = (secs % 3600) // 60
    units = [(f"{days:02d}", "TAGE"), (f"{hours:02d}", "STD"), (f"{minutes:02d}", "MIN")]

    # Transparenter Hintergrund — nur die abgerundete Karte ist deckend,
    # damit die Ecken im Discord-Embed sauber rund wirken.
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def _glow(draw_fn, blur: float) -> None:
        nonlocal canvas
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(layer))
        layer = layer.filter(ImageFilter.GaussianBlur(int(blur * S)))
        canvas = Image.alpha_composite(canvas, layer)

    # ── Karte ────────────────────────────────────────────
    m = 6 * S
    card = (m, m, W - m, H - m)
    rad = 30 * S
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(card, radius=rad, fill=CARD + (255,),
                        outline=BORDER + (255,), width=max(1, S))

    # Gradient-Hairline am oberen Kartenrand
    hair = _hgrad(card[2] - card[0] - 4 * rad, 2 * S, [PURPLE, PINK, CYAN])
    canvas.paste(hair, (card[0] + 2 * rad, m + S))

    PADX = 46 * S
    d = ImageDraw.Draw(canvas)

    # ── NR.-Badge (oben links) ───────────────────────────
    btrack = 2 * S
    bt = [d.textlength(c, font=F_BADGE) for c in badge]
    bwidth = sum(bt) + btrack * (len(badge) - 1)
    pill_w = bwidth + 36 * S
    pill_h = 38 * S
    bx, by = card[0] + PADX, m + 30 * S
    pill = (bx, by, bx + pill_w, by + pill_h)
    _glow(lambda g: g.rounded_rectangle(pill, radius=pill_h // 2,
          outline=PINK + (200,), width=3 * S), blur=5)
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(pill, radius=pill_h // 2, fill=_hex("1c1024") + (255,),
                        outline=PINK + (255,), width=max(1, S))
    bb = F_BADGE.getbbox(badge)
    _tracked(d, (pill[0] + pill[2]) / 2,
             pill[1] + (pill_h - (bb[3] - bb[1])) / 2 - bb[1],
             badge, F_BADGE, PINK, 2)

    # ── Datum (oben rechts) ──────────────────────────────
    dw = d.textlength(date_str, font=F_DATE)
    dbb = F_DATE.getbbox(date_str)
    d.text((card[2] - PADX - dw, pill[1] + (pill_h - (dbb[3] - dbb[1])) / 2 - dbb[1]),
           date_str, font=F_DATE, fill=MUTED)

    # ── Titel + Subtitle ─────────────────────────────────
    _ctext(d, W // 2, m + 118 * S, title, F_TITLE, TEXT)
    _ctext(d, W // 2, m + 168 * S, subtitle, F_SUB, MUTED)

    # ── Countdown-Boxen  /  Live-Zustand ─────────────────
    if not live:
        inner_w = (card[2] - PADX) - (card[0] + PADX)
        gap = 18 * S
        box_w = (inner_w - gap * 2) / 3
        box_h = 165 * S
        box_y = m + 205 * S
        brad = 16 * S
        for i, (num, lab) in enumerate(units):
            x0 = card[0] + PADX + i * (box_w + gap)
            box = (x0, box_y, x0 + box_w, box_y + box_h)
            _glow(lambda g, b=box: g.rounded_rectangle(
                (b[0] + 8 * S, b[1], b[2] - 8 * S, b[1] + 6 * S),
                radius=3 * S, fill=PINK + (180,)), blur=6)
            d = ImageDraw.Draw(canvas)
            d.rounded_rectangle(box, radius=brad, fill=CARD2 + (255,),
                                outline=BORDER + (255,), width=max(1, S))
            acc = _hgrad(int(box_w - 16 * S), 4 * S, [PURPLE, PINK])
            mask = Image.new("L", acc.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, acc.size[0] - 1, acc.size[1] - 1), radius=2 * S, fill=255)
            canvas.paste(acc, (int(box[0] + 8 * S), int(box[1] + 3 * S)), mask)
            d = ImageDraw.Draw(canvas)
            _ctext(d, (box[0] + box[2]) / 2, box[1] + 66 * S, num, F_NUM, TEXT)
            _tracked(d, (box[0] + box[2]) / 2, box[1] + 118 * S, lab, F_LABEL, MUTED, 3)
    else:
        # "JETZT LIVE"-Pill (Cyan + Glow) statt der Boxen
        cy = m + 287 * S
        ltxt = "JETZT LIVE"
        d = ImageDraw.Draw(canvas)
        lws = [d.textlength(c, font=F_LIVE) for c in ltxt]
        ltextw = sum(lws) + 4 * S * (len(ltxt) - 1)
        lbb = F_LIVE.getbbox(ltxt)
        lth = lbb[3] - lbb[1]
        lph = lth + 50 * S
        lpw = ltextw + 110 * S
        lpill = (W / 2 - lpw / 2, cy - lph / 2, W / 2 + lpw / 2, cy + lph / 2)
        _glow(lambda g: g.rounded_rectangle(lpill, radius=lph / 2,
              outline=CYAN + (220,), width=4 * S), blur=12)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle(lpill, radius=lph / 2, fill=_hex("081a20") + (255,),
                            outline=CYAN + (255,), width=max(1, S))
        _tracked(d, W / 2, cy - lth / 2 - lbb[1], ltxt, F_LIVE, CYAN, 4)

    out = canvas.resize((LW, LH), Image.LANCZOS)   # bleibt RGBA (Transparenz)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


if __name__ == "__main__":
    from datetime import timezone
    _now = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    _target = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)
    _buf = render_card(_now, _target, badge="NR. 02", title="Announcement #2",
                       subtitle="Premiere auf YouTube",
                       date_str="05.07.2026  ·  16:00 MESZ")
    _out = Path(__file__).parent / "preview.png"
    _out.write_bytes(_buf.getvalue())
    print(f"Wrote {_out}")
