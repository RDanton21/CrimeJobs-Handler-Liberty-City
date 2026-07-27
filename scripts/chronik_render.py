#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rendert aus docs/CITY_CHRONIK.md pro Tages-Eintrag eine einheitliche
Discord-Karte (1080x1350, Dossier-Look, Datum an fixer Position).

Aufruf:  python3 scripts/chronik_render.py
Ausgabe: docs/chronik_cards/chronik_TT-MM.png  (nicht versioniert)

05.07. bekommt den roten Broadcast-Kasten fuer die Botschaft.
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


def clean(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    return t.replace("`", "").strip()


def main():
    head = open(CHRON, encoding="utf-8").read().split("## Gruppen-Lagebild")[0]
    entries = []
    for line in head.splitlines():
        m = re.match(r"^\*\*(\d{2}\.\d{2})\.\*\*\s*[—-]\s*(.*)$", line)
        if m:
            entries.append((m.group(1), clean(m.group(2))))

    os.makedirs(OUT, exist_ok=True)
    for d, body in entries:
        date = f"{d}.2026"
        fn = os.path.join(OUT, f"chronik_{d.replace('.', '-')}.png")
        if d == "05.07":
            blocks = [
                ("text", "Es beginnt mit einer Zeile auf jedem Bildschirm und einem leeren Stuhl."),
                ("broadcast", "Schlaft gut — solange ihr noch könnt. Von jetzt an zählt, wer zuerst aufwacht."),
                ("text", "3 Stunden später brennen am Pier 41 drei Container. Am Morgen fehlt Mr. Camino zum ersten Mal seit 26 Jahren. Frankie Maloney macht den Tee trotzdem."),
            ]
            c.make_card(date, blocks, fn)
        else:
            c.make_card(date, body, fn)
    print(f"{len(entries)} Karten -> {OUT}")


if __name__ == "__main__":
    main()
