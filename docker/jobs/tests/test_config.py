# -*- coding: utf-8 -*-
"""Unit-Tests fuer die EVENT_PERIODS-Parserei."""
from src.config import _parse_periods


def test_einzelner_zeitraum_mit_label():
    p = _parse_periods("2026-08-07T18:00~2026-08-16T23:50:Liberty erwacht...")
    assert len(p) == 1
    assert p[0]["label"] == "Liberty erwacht..."
    assert p[0]["start"].hour == 18


def test_mehrere_zeitraeume_sortiert():
    p = _parse_periods(
        "2026-08-07T18:00~2026-08-16T23:50:B,2026-07-19T00:00~2026-07-26T23:59:A"
    )
    assert [x["label"] for x in p] == ["A", "B"]


def test_muell_wird_ignoriert():
    assert _parse_periods("quatsch") == []
    assert _parse_periods("") == []
    # Ende vor Start -> verwerfen
    assert _parse_periods("2026-08-16T00:00~2026-08-07T00:00") == []


def test_label_optional():
    p = _parse_periods("2026-08-07T18:00~2026-08-16T23:50")
    assert len(p) == 1 and p[0]["label"] == ""
