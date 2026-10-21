#!/usr/bin/env python3
"""Проверки титульной страницы: описания турниров, календарь, карусель,
рейтинг и профили игроков.

Запуск:  python tests/test_landing.py
"""
import io
import json
import os
import re
import sys

PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(PROJECT, "data")
SCRIPTS = os.path.join(PROJECT, "scripts")

PASSED = 0
FAILED = 0


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  OK  {name}")
    else:
        FAILED += 1
        print(f"  СБОЙ {name} {detail}")


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


print("=" * 62)
print("1) Описания турниров")
print("=" * 62)
index = load_json(os.path.join(DATA, "index.json"))
tournaments = index["tournaments"]
check("в каталоге есть турниры", len(tournaments) >= 13, f"найдено {len(tournaments)}")

without_desc = [t["slug"] for t in tournaments if not t.get("description")]
check("у каждого турнира есть описание", not without_desc, f"без описания: {without_desc}")

short = [t["slug"] for t in tournaments if len(t.get("description", "")) < 80]
check("описания не слишком короткие", not short, f"короткие: {short}")

too_long = [t["slug"] for t in tournaments if len(t.get("description", "")) > 600]
check("описания не раздуты", not too_long, f"длинные: {too_long}")

# описание есть и в файле самого турнира
sample = tournaments[0]["slug"]
tour_file = load_json(os.path.join(DATA, "tournaments", f"{sample}.json"))
check("описание продублировано в файле турнира",
      tour_file.get("description") == tournaments[0].get("description"))

print()
print("=" * 62)
print("2) Календарь: slug'и и даты")
print("=" * 62)
calendar = load_json(os.path.join(DATA, "calendar.json"))
items = calendar["tournaments"]
check("календарь не пуст", len(items) > 0, f"позиций: {len(items)}")

slugs = {i.get("slug") for i in items if i.get("slug")}
catalog = {t["slug"] for t in tournaments}
check("у календаря есть slug'и", len(slugs) > 0, f"со slug: {len(slugs)}")
# в календаре бывают и турниры без отдельной вкладки (Doha, Dubai, Beijing, Wuhan) —
# важно, чтобы slug'и наших 13 турниров были среди них
our_slugs = {i.get("slug") for i in items} & catalog
check("наши турниры найдены в календаре", len(our_slugs) >= 10,
      f"совпало: {len(our_slugs)} из {len(catalog)}")

bad_dates = [i["name"] for i in items if not re.match(r"^\d{4}-\d{2}-\d{2}$", i.get("start", ""))]
check("даты в формате ISO", not bad_dates, f"кривые: {bad_dates}")

future = [i for i in items if i["start"] >= "2026-10-21"]
check("есть предстоящие турниры", len(future) > 0, f"будущих: {len(future)}")

print()
print("=" * 62)
print("3) Фронтенд: карусель, рейтинг, профили")
print("=" * 62)
app = read(os.path.join(PROJECT, "app.js"))
css = read(os.path.join(PROJECT, "styles.css"))
html = read(os.path.join(PROJECT, "index.html"))

for fn in ("renderHeroCarousel", "setupCarousel", "renderLandingRanking",
           "renderLandingPage", "openPlayerProfile", "renderTournamentHero"):
    check(f"есть функция {fn}()", f"function {fn}(" in app)

check("карусель прокручивается по центру", "scroll-snap-type: x mandatory" in css)
check("активная карточка увеличена", ".carousel-card.active" in css)
check("есть точки-индикаторы", "carousel-dot" in css and "carousel-dots" in app)
check("блок рейтинга сворачивается", "ranking-rest" in app and "collapsed" in css)
check("в рейтинге видно топ-7", "rows.slice(0, 7)" in app)
check("есть кнопка раскрытия рейтинга", "rankingToggle" in app)
check("имя игрока — ссылка на профиль", "player-link" in app and "data-player=" in app)
check("есть модальное окно профиля", "profileModal" in html and "profileModal" in app)
check("в шапке турнира есть описание", "tournament-description" in app and "tournament-description" in css)
check("переключатель результатов и сетки", 'data-view="list"' in app and 'data-view="bracket"' in app)
check("вкладка «Главная»", 'data-tab="home"' in app)

print()
print("=" * 62)
print("4) Фото турниров и профили игроков")
print("=" * 62)
photos_path = os.path.join(DATA, "tournament_photos.json")
profiles_path = os.path.join(DATA, "player_profiles.json")

if os.path.exists(photos_path):
    photos = load_json(photos_path)
    with_photo = [s for s in catalog if photos.get(s, {}).get("photo")]
    check("фото есть у большинства турниров", len(with_photo) >= len(catalog) - 2,
          f"с фото: {len(with_photo)} из {len(catalog)}")
    bad = [s for s in catalog
           if photos.get(s, {}).get("photo")
           and not photos[s]["photo"].startswith("https://")]
    check("ссылки на фото — https", not bad, f"кривые: {bad}")
else:
    print("  — файла tournament_photos.json пока нет")

if os.path.exists(profiles_path):
    profiles = load_json(profiles_path)
    check("профили игроков собраны", len(profiles) > 0, f"профилей: {len(profiles)}")
    with_sum = [p for p in profiles.values() if p.get("summary")]
    check("у профилей есть текст", len(with_sum) > len(profiles) // 2,
          f"с текстом: {len(with_sum)} из {len(profiles)}")
    with_age = [p for p in profiles.values() if p.get("age")]
    check("у профилей есть возраст", len(with_age) > len(profiles) // 2,
          f"с возрастом: {len(with_age)} из {len(profiles)}")
else:
    print("  — файла player_profiles.json пока нет")

print()
print("=" * 62)
print(f"ИТОГО: {PASSED} проверок пройдено, {FAILED} провалов")
print("=" * 62)
sys.exit(1 if FAILED else 0)
