# -*- coding: utf-8 -*-
"""Renderer fuer Chronik-Karten (einheitliche Discord-Bilder).

Breite ist fix (1080). Die Hoehe kann pro Aufruf gesetzt werden (height=) —
so kann der Batch EINE gemeinsame Hoehe fuer ALLE Karten verwenden, die dem
laengsten Eintrag entspricht (kuerzer als frueher, aber einheitlich).
Layout/Datum sitzen immer an derselben Stelle.
"""
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

W        = 1080
H_DEF    = 1200
BG       = (12, 13, 16)
TXT      = (233, 231, 226)
MUT      = (139, 144, 150)
FAINT    = (46, 48, 54)
ACC      = (216, 162, 74)      # Amber / Akten-Gold
RED      = (226, 60, 80)       # Broadcast-Rot
FDIR     = "/usr/share/fonts/truetype/dejavu/"
ML       = 96                  # Rand
BODY_Y0  = 440                 # fixer Start des Fliesstexts
BODY_LH  = int(34 * 1.55)

def F(name, size):
    return ImageFont.truetype(FDIR + name, size)

def tracked(d, pos, text, font, fill, tracking):
    x, y = pos
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking
    return x - tracking

def tracked_width(text, font, tracking):
    return sum(font.getlength(c) + tracking for c in text) - tracking

def wrap(text, font, maxw):
    lines = []
    for para in text.split("\n"):
        words, cur = para.split(), ""
        for w in words:
            t = (cur + " " + w).strip()
            if font.getlength(t) <= maxw:
                cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        lines.append(cur)
    return lines

def _text_lines(content):
    bf = F("DejaVuSerif.ttf", 34)
    return wrap(content, bf, (W - ML) - (ML + 30))

def _broadcast_mlines(content):
    mf = F("DejaVuSansMono-Bold.ttf", 30)
    return wrap(content, mf, (W - 2 * ML) - 2 * 36)

def _broadcast_h(content):
    return 36 + 26 + 26 + len(_broadcast_mlines(content)) * int(30 * 1.45) + 36

def body_end_y(blocks):
    """Berechnet (ohne zu zeichnen), bei welchem y der Fliesstext endet."""
    if isinstance(blocks, str):
        blocks = [("text", blocks)]
    y = BODY_Y0
    for kind, content in blocks:
        if kind == "broadcast":
            y += _broadcast_h(content) + 14
        else:
            y += BODY_LH * len(_text_lines(content)) + 10
    return y

def draw_text_block(d, y, text):
    bf = F("DejaVuSerif.ttf", 34)
    bx = ML + 30
    lines = _text_lines(text)
    d.rectangle([ML, y - 2, ML + 4, y + BODY_LH * len(lines) - 10], fill=ACC)
    for ln in lines:
        d.text((bx, y), ln, font=bf, fill=TXT)
        y += BODY_LH
    return y + 10

def draw_broadcast(d, y, message):
    x, w, pad = ML, W - 2 * ML, 36
    hf = F("DejaVuSansMono-Bold.ttf", 20)
    mf = F("DejaVuSansMono-Bold.ttf", 30)
    header = ">> ÜBERTRAGUNG // QUELLE UNBEKANNT"
    mlines = _broadcast_mlines(message)
    box_h = _broadcast_h(message)
    d.rectangle([x, y, x + w, y + box_h], fill=(6, 6, 8), outline=(70, 26, 34), width=2)
    hw = tracked_width(header, hf, 4)
    tracked(d, (x + (w - hw) / 2, y + pad), header, hf, RED, 4)
    my = y + pad + 52
    for ln in mlines:
        lw = mf.getlength(ln)
        d.text((x + (w - lw) / 2, my), ln, font=mf, fill=(240, 240, 240))
        my += int(30 * 1.45)
    return y + box_h + 14

def make_card(date, blocks, out, bg=None, height=None):
    if isinstance(blocks, str):
        blocks = [("text", blocks)]
    H = height or H_DEF

    if bg:
        base = Image.open(bg).convert("RGB")
        sc = max(W / base.width, H / base.height)
        base = base.resize((int(base.width * sc), int(base.height * sc)))
        l = (base.width - W) // 2; t = (base.height - H) // 2
        base = ImageEnhance.Brightness(base.crop((l, t, l + W, t + H))).enhance(0.40)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        for yy in range(H):
            a = 90
            if yy < 380: a = max(a, int(175 * (1 - yy / 380)))
            if yy > 430: a = max(a, 120)
            od.line([(0, yy), (W, yy)], fill=(0, 0, 0, a))
        img = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    else:
        img = Image.new("RGB", (W, H), BG)
        mask = Image.radial_gradient("L").resize((W, H)).point(lambda v: int(v * 0.55))
        img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, mask)
    d = ImageDraw.Draw(img)

    d.rectangle([40, 40, W - 40, H - 40], outline=FAINT, width=2)
    for cx, cy in [(40, 40), (W - 40, 40), (40, H - 40), (W - 40, H - 40)]:
        d.line([cx - 14, cy, cx + 14, cy], fill=ACC, width=2)
        d.line([cx, cy - 14, cx, cy + 14], fill=ACC, width=2)

    tracked(d, (ML, 80), "AKTE · LIBERTY CITY", F("DejaVuSansMono.ttf", 22), MUT, 6)
    tracked(d, (ML, 116), "CHRONIK DER STILLEN TAGE", F("DejaVuSans-Bold.ttf", 30), TXT, 4)
    d.line([ML, 170, W - ML, 170], fill=FAINT, width=2)

    tracked(d, (ML, 212), "DATUM", F("DejaVuSansMono.ttf", 20), MUT, 8)
    df = F("DejaVuSans-Bold.ttf", 86)
    d.text((ML - 2, 240), date, font=df, fill=ACC)
    d.line([ML, 344, ML + d.textlength(date, font=df), 344], fill=ACC, width=4)

    y = BODY_Y0
    for kind, content in blocks:
        y = draw_broadcast(d, y, content) if kind == "broadcast" else draw_text_block(d, y, content)

    img.save(out)
