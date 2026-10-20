#!/usr/bin/env python3
"""Краткая сводка по данным для отчёта GitHub Actions.

Использование:
    python scripts/summarize.py
"""

import json
import os

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load(path, default=None):
    full = os.path.join(PROJECT, path)
    if not os.path.exists(full):
        return default
    try:
        with open(full, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main():
    index = load("data/index.json", {}) or {}
    tournaments = index.get("tournaments", []) or []
    rankings = load("data/rankings.json", {}) or {}
    photos = load("data/players.json", {}) or {}

    print(f"- Обновлено: {index.get('last_updated') or '—'}")
    print(f"- Турниров: {len(tournaments)}")
    for t in tournaments:
        counts = t.get("counts", {}) or {}
        print(f"  - {t.get('icon', '')} {t.get('name', '')} "
              f"({t.get('level_label', '')}): {counts.get('years', 0)} г., "
              f"основных {counts.get('main', 0)}, второстепенных {counts.get('secondary', 0)}")
    print(f"- Рейтинг: ATP {len(rankings.get('men', []) or [])}, "
          f"WTA {len(rankings.get('women', []) or [])}")
    print(f"- Фотографий игроков: {len(photos)}")


if __name__ == "__main__":
    main()
