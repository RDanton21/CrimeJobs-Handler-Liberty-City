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
OUT = os.path.join(ROOT, "docs", "chronik_cards")
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


def main():
    head = open(CHRON, encoding="utf-8").read().split("## Gruppen-Lagebild")[0]
    entries = []
    for line in head.splitlines():
        m = re.match(r"^\*\*(\d{2}\.\d{2})\.\*\*\s*[—-]\s*(.*)$", line)
        if m:
            entries.append((m.group(1), clean(m.group(2))))

    items = [(d, blocks_for(d, body)) for d, body in entries]

    os.makedirs(OUT, exist_ok=True)
    for d, bl in items:
        H = c.body_end_y(bl) + PAD          # Auto-Hoehe: passt sich dem Text an
        fn = os.path.join(OUT, f"chronik_{d.replace('.', '-')}.png")
        c.make_card(f"{d}.2026", bl, fn, height=H)
    print(f"{len(items)} Karten (Auto-Hoehe, Breite 1080) -> {OUT}")


if __name__ == "__main__":
    main()
