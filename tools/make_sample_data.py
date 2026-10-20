#!/usr/bin/env python3
"""Генератор демонстрационных данных для data/sample/.

Структура файлов 1-в-1 совпадает с боевым форматом, который создаёт
scripts/fetch_tennis.py, поэтому демо-режим сайта работает по тому же коду.

Использование:
    python tools/make_sample_data.py
    python tools/make_sample_photos.py   # подтягивает фото из Wikipedia
"""
import json
import os
import zlib

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(PROJECT, "data", "sample")
TOURN = os.path.join(OUT, "tournaments")

MEN = [
    ("Sinner, Jannik", "ITA", 1), ("Alcaraz, Carlos", "ESP", 2),
    ("Djokovic, Novak", "SRB", 3), ("Zverev, Alexander", "DEU", 4),
    ("Rublev, Andrey", "KAZ", 5), ("Rune, Casper", "DEN", 6),
    ("Fritz, Taylor", "USA", 7), ("Tsitsipas, Stefanos", "GRE", 8),
    ("Auger-Aliassime, Felix", "CAN", 9), ("Humbert, Ugo", "FRA", 10),
    ("Medvedev, Daniil", "USA", 11), ("Paul, Tommy", "USA", 12),
]
WOMEN = [
    ("Sabalenka, Aryna", "POL", 1), ("Swiatek, Iga", "POL", 2),
    ("Gauff, Coco", "USA", 3), ("Wozniacki, Caroline", "DEN", 4),
    ("Rybakina, Elena", "KAZ", 5), ("Kvitova, Petra", "CZE", 6),
    ("Raducanu, Emma", "GBR", 7), ("Alexandrova, Ekaterina", "RUS", 8),
    ("Badosa, Paula", "ESP", 9), ("Vondrousova, Marketa", "CZE", 10),
    ("Pegula, Jessica", "USA", 11), ("Zheng, Qinwen", "CHN", 12),
]

ROUNDS_MAIN = ["quarterfinal", "semifinal", "final"]
ROUNDS_EARLY = ["round_of_128", "round_of_64", "round_of_32", "round_of_16"]
ROUND_DISPLAY = {
    "quarterfinal": "Четвертьфинал", "semifinal": "Полуфинал", "final": "Финал",
    "round_of_16": "1/8 финала", "round_of_32": "1/16 финала",
    "round_of_64": "1/32 финала", "round_of_128": "1/64 финала",
}


def stable_id(name):
    """Стабильный ID игрока: одинаковый в матчах и в рейтинге."""
    return f"sr:competitor:demo{zlib.crc32(name.encode('utf-8')) % 10000:04d}"


def make_players(pool, offset, count):
    players = []
    for i in range(count):
        name, cc, seed = pool[(offset + i) % len(pool)]
        players.append({
            "id": stable_id(name),
            "name": name,
            "country_code": cc,
            "qualifier": "home" if i % 2 == 0 else "away",
            "seed": seed if i < 6 else None,
        })
    return players


def make_match(mid, players, rnd, status, start, gender, category, best_of, venue, city, tz):
    match = {
        "id": f"sr:sport_event:demo{mid}",
        "round": rnd,
        "round_display": ROUND_DISPLAY[rnd],
        "gender": gender,
        "category": category,
        "start_time": start,
        "status": status,
        "match_status": "set2" if status == "live" else ("ended" if status == "closed" else ""),
        "best_of": best_of,
        "venue": venue,
        "city": city,
        "timezone": tz,
        "players": players,
    }
    if status in ("closed", "live"):
        home, away = players[0], players[1]
        h_sets = 2 if status == "live" else 3
        a_sets = 1 if status == "live" else (0 if h_sets == 3 else 1)
        periods = []
        for s in range(1, h_sets + a_sets + 1):
            periods.append({"home": 6 if s <= h_sets else 3,
                            "away": 4 if s <= h_sets else 6, "number": s})
        match["scores"] = {"home": h_sets, "away": a_sets, "periods": periods}
        if status == "closed":
            match["winner_id"] = home["id"]
    return match


def build_tournament(name, short, icon, level, level_label, years_spec):
    years = {}
    mid = 0
    for year, spec in years_spec.items():
        genders = {}
        for gender, pool, category, best_of in (
            ("men", MEN, "ATP", 5), ("women", WOMEN, "WTA", 3)
        ):
            if gender not in spec:
                continue
            status, count_main, count_early, start_prefix = spec[gender]
            main, secondary = [], []
            for i, rnd in enumerate(ROUNDS_MAIN):
                if i >= count_main:
                    break
                players = make_players(pool, mid, 2)
                main.append(make_match(mid, players, rnd, status,
                                       f"{start_prefix}T{10 + i * 3:02d}:00:00+00:00",
                                       gender, category, best_of,
                                       "Centre Court", "Melbourne", "Australia/Melbourne"))
                mid += 1
            for i, rnd in enumerate(ROUNDS_EARLY):
                if i >= count_early:
                    break
                players = make_players(pool, mid, 2)
                secondary.append(make_match(mid, players, rnd, status,
                                            f"{start_prefix}T{8 + i * 2:02d}:30:00+00:00",
                                            gender, category, best_of,
                                            "Show Court", "Melbourne", "Australia/Melbourne"))
                mid += 1
            genders[gender] = {"main": main, "secondary": secondary}
        years[year] = genders
    return {
        "id": f"sr:competition:demo-{name}",
        "name": name, "short": short, "icon": icon,
        "level": level, "level_label": level_label,
        "genders": sorted({g for spec in years_spec.values() for g in spec}),
        "years": years,
    }


TOURNAMENTS = [
    ("australian-open", "Australian Open", "AO", "🇦🇺", "grand_slam", "Большой шлем"),
    ("roland-garros", "Roland Garros", "RG", "🇫🇷", "grand_slam", "Большой шлем"),
    ("wimbledon", "Wimbledon", "WIM", "🇬🇧", "grand_slam", "Большой шлем"),
    ("us-open", "US Open", "USO", "🇺🇸", "grand_slam", "Большой шлем"),
    ("shanghai", "Shanghai", "SHA", "🇨🇳", "atp_1000", "Masters 1000"),
    ("paris-masters", "Paris Masters", "PAR", "🇫🇷", "atp_1000", "Masters 1000"),
    ("cincinnati", "Cincinnati", "CIN", "🇺🇸", "atp_1000", "Masters 1000"),
]

SPECS = {
    "australian-open": {
        "2027": {"men": ("not_started", 3, 2, "2027-01-20"),
                 "women": ("not_started", 3, 2, "2027-01-22")},
        "2026": {"men": ("closed", 3, 2, "2026-01-19"),
                 "women": ("closed", 3, 2, "2026-01-21")},
        "2025": {"men": ("closed", 3, 2, "2025-01-20"),
                 "women": ("closed", 3, 2, "2025-01-22")},
    },
    "roland-garros": {
        "2026": {"men": ("closed", 3, 2, "2026-05-25"),
                 "women": ("closed", 3, 2, "2026-05-27")},
        "2025": {"men": ("closed", 3, 2, "2025-05-26"),
                 "women": ("closed", 3, 2, "2025-05-28")},
    },
    "wimbledon": {
        "2026": {"men": ("closed", 3, 2, "2026-07-06"),
                 "women": ("closed", 3, 2, "2026-07-08")},
        "2025": {"men": ("closed", 3, 2, "2025-07-07"),
                 "women": ("closed", 3, 2, "2025-07-09")},
    },
    "us-open": {
        "2026": {"men": ("closed", 3, 2, "2026-08-31"),
                 "women": ("closed", 3, 2, "2026-09-02")},
        "2025": {"men": ("closed", 3, 2, "2025-09-01"),
                 "women": ("closed", 3, 2, "2025-09-03")},
    },
    "shanghai": {
        "2026": {"men": ("closed", 3, 2, "2026-10-05")},
        "2025": {"men": ("closed", 3, 2, "2025-10-06")},
    },
    "paris-masters": {
        "2026": {"men": ("not_started", 3, 2, "2026-11-01")},
    },
    "cincinnati": {
        "2026": {"men": ("closed", 3, 2, "2026-08-09"),
                 "women": ("closed", 3, 2, "2026-08-11")},
    },
}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def main():
    os.makedirs(TOURN, exist_ok=True)
    index = []
    for slug, name, short, icon, level, level_label in TOURNAMENTS:
        data = build_tournament(name, short, icon, level, level_label, SPECS[slug])
        counts = {"main": 0, "secondary": 0, "years": len(data["years"])}
        for year_data in data["years"].values():
            for gender_data in year_data.values():
                counts["main"] += len(gender_data["main"])
                counts["secondary"] += len(gender_data["secondary"])
        write_json(os.path.join(TOURN, f"{slug}.json"), data)
        index.append({
            "slug": slug, "name": name, "short": short, "icon": icon,
            "level": level, "level_label": level_label,
            "genders": data["genders"], "years": sorted(data["years"].keys(), reverse=True),
            "counts": counts,
        })
        print(f"  {name}: {counts}")

    write_json(os.path.join(OUT, "index.json"),
               {"last_updated": "2026-10-20T09:00:00+00:00", "tournaments": index})

    def ranking(pool, points_start):
        rows = []
        for i, (name, cc, _seed) in enumerate(pool):
            rows.append({
                "rank": i + 1,
                "movement": (i % 5) - 2,
                "points": points_start - i * 420,
                "played": 18 - (i % 7),
                "id": stable_id(name),
                "name": name,
                "country_code": cc,
            })
        return rows

    write_json(os.path.join(OUT, "rankings.json"), {
        "last_updated": "2026-10-19T00:00:00+00:00",
        "week": "42",
        "men": ranking(MEN, 13450),
        "women": ranking(WOMEN, 11225),
    })

    print("\nДемо-данные записаны в", OUT)
    print("Затем выполните: python tools/make_sample_photos.py")


if __name__ == "__main__":
    main()
