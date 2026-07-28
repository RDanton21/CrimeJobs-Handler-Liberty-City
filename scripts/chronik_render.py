#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rendert aus docs/CITY_CHRONIK.md pro Tages-Eintrag eine einheitliche
Discord-Karte. Die Hoehe wird EINMAL berechnet (so hoch wie der laengste
Eintrag braucht) und fuer ALLE Karten verwendet -> kuerzer, aber einheitlich.

Aufruf:  python3 scripts/chronik_render.py
Ausgabe: docs/chronik_cards/chronik_TT-MM.png  (nicht versioniert)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import chronik_card as c

CHRON = os.path.join(ROOT, "docs", "CITY_CHRONIK.md")
# Ausgabe ins geteilte data-Volume, damit Backend und Bot dieselben Karten sehen.
OUT = os.path.join(ROOT, "data", "chronik_cards")
PAD = 80   # Abstand Textende -> unterer Rand (Auto-Hoehe je Karte)


def clean(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    return t.replace("`", "").strip()


def blocks_for(d, body):
    if d == "05.07":
        return [
            ("text", "Es beginnt mit einer Zeile auf jedem Bildschirm und einem leeren Stuhl."),
            ("broadcast", "Schlaft gut — solange ihr noch könnt. Von jetzt an zählt, wer zuerst aufwacht."),
            ("text", "3 Stunden später brennen am Pier 41 drei Container. Am Morgen fehlt Mr. Camino zum ersten Mal seit 26 Jahren. Frankie Maloney macht den Tee trotzdem."),
        ]
    return [("text", body)]


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "extra"


def main():
    txt = open(CHRON, encoding="utf-8").read()
    head = txt.split("## Gruppen-Lagebild")[0]
    items = []  # (filename, date_display, blocks)

    # Haupt-Karten (Tages-Eintraege)
    for line in head.splitlines():
        m = re.match(r"^\*\*(\d{2}\.\d{2})\.\*\*\s*[—-]\s*(.*)$", line)
        if m:
            d = m.group(1)
            items.append((f"chronik_{d.replace('.', '-')}.png", d, blocks_for(d, clean(m.group(2)))))

    # Zusatzkarten (## Sonderkarten, manuell)
    if "## Sonderkarten" in txt:
        sec = txt.split("## Sonderkarten", 1)[1].split("\n## ", 1)[0]
        for line in sec.splitlines():
            m = re.match(r"^\*\*(\d{2}\.\d{2})\.\s*·\s*(.+?)\*\*\s*[—-]\s*(.*)$", line)
            if m:
                d, label, body = m.group(1), m.group(2).strip(), clean(m.group(3))
                items.append((f"chronik_{d.replace('.', '-')}_{slug(label)}.png", d, [("text", body)]))

    # Optionale Argumente = Dateinamen -> nur diese Karten rendern
    wanted = {a.strip() for a in sys.argv[1:] if a.strip()}
    if wanted:
        items = [it for it in items if it[0] in wanted]
        if not items:
            print(f"Keine passenden Karten fuer {sorted(wanted)}")
            return

    os.makedirs(OUT, exist_ok=True)
    for fn, d, bl in items:
        H = c.body_end_y(bl) + PAD          # Auto-Hoehe: passt sich dem Text an
        c.make_card(f"{d}.2026", bl, os.path.join(OUT, fn), height=H)
    print(f"{len(items)} Karte(n) gerendert -> {OUT}")


if __name__ == "__main__":
    main()
