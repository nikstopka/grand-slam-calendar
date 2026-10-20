"""Локальная проверка поиска фото в Wikipedia + генерация photos.json для демо-данных.

Использование:
    python tools/make_sample_photos.py
"""
import importlib.util
import json
import os
import sys

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
spec = importlib.util.spec_from_file_location(
    "fetch_tennis", os.path.join(PROJECT, "scripts", "fetch_tennis.py")
)
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)

# Собираем игроков из демо-данных: из матчей и из рейтинга
players = {}
sample_dir = os.path.join(PROJECT, "data", "sample", "tournaments")
for filename in sorted(os.listdir(sample_dir)):
    if not filename.endswith(".json"):
        continue
    with open(os.path.join(sample_dir, filename), encoding="utf-8") as f:
        data = json.load(f)
    for year_data in data.get("years", {}).values():
        for gender_data in year_data.values():
            for key in ("main", "secondary"):
                for match in gender_data.get(key, []):
                    for player in match.get("players", []):
                        pid = player.get("id")
                        if pid and pid not in players:
                            players[pid] = player.get("name", "")

# Игроки из рейтинга
rankings_path = os.path.join(PROJECT, "data", "sample", "rankings.json")
if os.path.exists(rankings_path):
    with open(rankings_path, encoding="utf-8") as f:
        rankings = json.load(f)
    for row in rankings.get("men", []) + rankings.get("women", []):
        pid = row.get("id")
        if pid and pid not in players:
            players[pid] = row.get("name", "")

print(f"уникальных игроков в демо-данных: {len(players)}")

photos = {}
failed = []
for i, (pid, name) in enumerate(players.items(), 1):
    url = ft.wikipedia_photo(name)
    if url:
        photos[pid] = url
        print(f"  [{i}/{len(players)}] {name} -> OK")
    else:
        failed.append(name)
        print(f"  [{i}/{len(players)}] {name} -> не найдено")

out = os.path.join(PROJECT, "data", "sample", "players.json")
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(photos, f, ensure_ascii=False, indent=1)
print(f"\nЗаписано {len(photos)} фото в {out}")
if failed:
    print("не найдено:", ", ".join(failed))
