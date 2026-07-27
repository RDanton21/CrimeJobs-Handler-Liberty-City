# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

W, H = 1080, 1350
BG   = (12, 13, 16)
TXT  = (233, 231, 226)
MUT  = (139, 144, 150)
FAINT= (46, 48, 54)
ACC  = (216, 162, 74)      # Amber / Akten-Gold
RED  = (226, 60, 80)       # Broadcast-Rot
FDIR = "/usr/share/fonts/truetype/dejavu/"
ML   = 96                  # linker/rechter Rand des Inhalts

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

def draw_text_block(d, y, text):
    bf = F("DejaVuSerif.ttf", 34)
    bx = ML + 30
    maxw = (W - ML) - bx
    lines = wrap(text, bf, maxw)
    lh = int(34 * 1.55)
    d.rectangle([ML, y - 2, ML + 4, y + lh * len(lines) - 10], fill=ACC)
    for ln in lines:
        d.text((bx, y), ln, font=bf, fill=TXT)
        y += lh
    return y + 10

def draw_broadcast(d, y, message):
    x = ML
    w = W - 2 * ML
    pad = 36
    hf = F("DejaVuSansMono-Bold.ttf", 20)
    mf = F("DejaVuSansMono-Bold.ttf", 30)
    header = ">> ÜBERTRAGUNG // QUELLE UNBEKANNT"
    inner = w - 2 * pad
    mlines = wrap(message, mf, inner)
    mlh = int(30 * 1.45)
    box_h = pad + 26 + 26 + len(mlines) * mlh + pad
    # Panel
    d.rectangle([x, y, x + w, y + box_h], fill=(6, 6, 8), outline=(70, 26, 34), width=2)
    # Header (rot, zentriert, getrackt)
    hw = tracked_width(header, hf, 4)
    tracked(d, (x + (w - hw) / 2, y + pad), header, hf, RED, 4)
    # Nachricht (weiß, zentriert)
    my = y + pad + 26 + 26
    for ln in mlines:
        lw = mf.getlength(ln)
        d.text((x + (w - lw) / 2, my), ln, font=mf, fill=(240, 240, 240))
        my += mlh
    return y + box_h + 14

def make_card(date, blocks, out, bg=None):
    if isinstance(blocks, str):
        blocks = [("text", blocks)]
    if bg:
        base = Image.open(bg).convert("RGB")
        sc = max(W / base.width, H / base.height)
        base = base.resize((int(base.width * sc), int(base.height * sc)))
        l = (base.width - W) // 2; t = (base.height - H) // 2
        base = base.crop((l, t, l + W, t + H))
        base = ImageEnhance.Brightness(base).enhance(0.40)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for yy in range(H):
            a = 90
            if yy < 380:                      # Kopf/Datum dunkler
                a = max(a, int(175 * (1 - yy / 380)))
            if yy > 430:                      # Textbereich lesbar halten
                a = max(a, 120)
            od.line([(0, yy), (W, yy)], fill=(0, 0, 0, a))
        img = Image.alpha_composite(base.convert("RGBA"), ov).convert("RGB")
    else:
        img = Image.new("RGB", (W, H), BG)
        mask = Image.radial_gradient("L").resize((W, H)).point(lambda v: int(v * 0.55))
        img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, mask)
    d = ImageDraw.Draw(img)

    d.rectangle([40, 40, W - 40, H - 40], outline=FAINT, width=2)
    for cx, cy in [(40,40),(W-40,40),(40,H-40),(W-40,H-40)]:
        d.line([cx-14,cy,cx+14,cy], fill=ACC, width=2)
        d.line([cx,cy-14,cx,cy+14], fill=ACC, width=2)

    tracked(d, (ML, 80), "AKTE · LIBERTY CITY", F("DejaVuSansMono.ttf", 22), MUT, 6)
    tracked(d, (ML, 116), "CHRONIK DER STILLEN TAGE", F("DejaVuSans-Bold.ttf", 30), TXT, 4)
    d.line([ML, 170, W - ML, 170], fill=FAINT, width=2)

    tracked(d, (ML, 212), "DATUM", F("DejaVuSansMono.ttf", 20), MUT, 8)
    df = F("DejaVuSans-Bold.ttf", 86)
    d.text((ML - 2, 240), date, font=df, fill=ACC)
    dw = d.textlength(date, font=df)
    d.line([ML, 344, ML + dw, 344], fill=ACC, width=4)

    y = 440
    for kind, content in blocks:
        if kind == "broadcast":
            y = draw_broadcast(d, y, content)
        else:
            y = draw_text_block(d, y, content)

    img.save(out)
    print("gespeichert:", out)
