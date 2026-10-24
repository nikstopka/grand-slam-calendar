#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генерация ICS-календаря для подписки на iOS/календарь."""

import json
import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
TOUR_DIR = os.path.join(DATA_DIR, "tournaments")
OUT_DIR = os.path.join(ROOT, "calendars")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")


def fmt_ics(dt_str):
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        return None


def escape_ics(text):
    if not text:
        return ""
    text = str(text)
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text


def make_ics(tournament, year, matches, cal_name):
    lines = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//grand-slam-calendar//tennis//RU")
    lines.append("CALSCALE:GREGORIAN")
    lines.append("METHOD:PUBLISH")
    lines.append(f"X-WR-CALNAME:{escape_ics(cal_name)}")
    lines.append("X-WR-TIMEZONE:UTC")
    lines.append("REFRESH-INTERVAL;VALUE=DURATION:PT30M")
    lines.append("X-PUBLISHED-TTL:PT30M")

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for m in matches:
        start = fmt_ics(m.get("start_time"))
        if not start:
            continue
        players = m.get("players") or []
        names = []
        for p in players:
            if isinstance(p, dict) and p.get("name"):
                names.append(p["name"])
        vs = " vs ".join(names) if len(names) == 2 else " / ".join(names)
        round_disp = m.get("round_display") or m.get("round") or ""
        tname = tournament.get("name") or ""
        title = f"{tname} {year} — {round_disp}: {vs}".strip()
        uid = f"{m.get('id') or uuid4()}@grand-slam-calendar"
        end_dt = datetime.strptime(start, "%Y%m%dT%H%M%SZ") + timedelta(hours=3)
        end = end_dt.strftime("%Y%m%dT%H%M%SZ")
        desc_lines = []
        desc_lines.append(f"Турнир: {tname} ({year})")
        desc_lines.append(f"Этап: {round_disp}")
        if vs:
            desc_lines.append(f"Матч: {vs}")
        desc_lines.append(f"Категория: {m.get('category') or tournament.get('level_label') or ''}")
        desc = "\\n".join([escape_ics(x) for x in desc_lines if x])
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now}")
        lines.append(f"DTSTART:{start}")
        lines.append(f"DTEND:{end}")
        lines.append(f"SUMMARY:{escape_ics(title)}")
        lines.append(f"DESCRIPTION:{desc}")
        lines.append(f"URL:https://nikstopka.github.io/grand-slam-calendar/#/{tournament.get('slug')}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        with open(INDEX_PATH, encoding="utf-8-sig") as f:
            index = json.load(f)
    except Exception as e:
        print(e)
        return
    tournaments = index.get("tournaments") or []
    all_matches = []
    for t in tournaments:
        slug = t.get("slug")
        path = os.path.join(TOUR_DIR, f"{slug}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            continue
        years = data.get("years") or {}
        for year, ydata in years.items():
            for gender in ["men", "women"]:
                gdata = (ydata or {}).get(gender) or {}
                for section in ["main", "secondary"]:
                    for m in gdata.get(section) or []:
                        m2 = dict(m)
                        m2["_tournament"] = data
                        m2["_year"] = year
                        all_matches.append(m2)
        # per tournament combined
        t_matches = []
        for year, ydata in years.items():
            for gender in ["men", "women"]:
                gdata = (ydata or {}).get(gender) or {}
                for section in ["main", "secondary"]:
                    t_matches.extend(gdata.get(section) or [])
        if t_matches:
            ics = make_ics(data, list(years.keys())[0] if years else "", t_matches, f"Теннис: {data.get('name')}")
            with open(os.path.join(OUT_DIR, f"{slug}.ics"), "w", encoding="utf-8") as f:
                f.write(ics)
    # combined
    ics_all = make_ics({"name": "Большой шлем и не только", "slug": "all"}, datetime.now().year, all_matches, "Теннис: все турниры")
    with open(os.path.join(OUT_DIR, "all.ics"), "w", encoding="utf-8") as f:
        f.write(ics_all)
    print("ICS generated")


if __name__ == "__main__":
    main()
