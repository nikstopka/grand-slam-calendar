#!/usr/bin/env python3
"""Общие утилиты для сборщиков данных календаря.

Используются обоими провайдерами: Sportradar (scripts/fetch_tennis.py)
и бесплатным (scripts/free_provider.py).
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(PROJECT_DIR, ".cache")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")

# === HTTP ===

def http_get(url, headers=None, timeout=45, retries=3):
    """GET-запрос с повторами. Возвращает (text, error)."""
    headers = dict(headers or {})
    headers.setdefault("Accept", "application/json")
    headers.setdefault("User-Agent", "grand-slam-calendar/1.0 (https://github.com/nikstopka/grand-slam-calendar)")
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace"), None
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} ({e.reason})"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            break
    return None, last


def http_get_json(url, headers=None, timeout=45, retries=3):
    """GET-запрос с разбором JSON. Возвращает (data, error)."""
    text, error = http_get(url, headers=headers, timeout=timeout, retries=retries)
    if text is None:
        return None, error
    try:
        return json.loads(text), None
    except ValueError as e:
        return None, f"не удалось разобрать JSON: {e}"


# === КЭШ ===

def cache_path(name):
    return os.path.join(CACHE_DIR, name)


def cache_read(name):
    path = cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def cache_write(name, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


# === НОРМАЛИЗАЦИЯ ===

ROUND_DISPLAY_NAMES = {
    "qualification_round_1": "Квалификация. Раунд 1",
    "qualification_round_2": "Квалификация. Раунд 2",
    "qualification_round_3": "Квалификация. Раунд 3",
    "qualification_round_4": "Квалификация. Раунд 4",
    "round_of_128": "1/64 финала",
    "round_of_64": "1/32 финала",
    "round_of_32": "1/16 финала",
    "round_of_16": "1/8 финала",
    "quarterfinal": "Четвертьфинал",
    "semifinal": "Полуфинал",
    "final": "Финал",
}

ROUND_ALIASES = {
    "r128": "round_of_128",
    "r64": "round_of_64",
    "r32": "round_of_32",
    "r16": "round_of_16",
    "qf": "quarterfinal",
    "sf": "semifinal",
    "f": "final",
    "rr": "round_robin",
    "first_round": "round_of_128",
    "second_round": "round_of_64",
    "third_round": "round_of_32",
    "fourth_round": "round_of_16",
    "fifth_round": "quarterfinal",
    "sixth_round": "semifinal",
    "seventh_round": "final",
    "quarter_final": "quarterfinal",
    "quarterfinals": "quarterfinal",
    "semi_final": "semifinal",
    "semifinals": "semifinal",
    "qualification_round_1": "qualification_round_1",
    "qualification_round_2": "qualification_round_2",
    "qualification_round_3": "qualification_round_3",
    "qualifying_round_1": "qualification_round_1",
    "qualifying_round_2": "qualification_round_2",
    "qualifying_round_3": "qualification_round_3",
}

GENDER_MAP = {
    "female": "women", "women": "women", "woman": "women", "wta": "women", "f": "women",
    "male": "men", "men": "men", "man": "men", "atp": "men", "m": "men",
}

MAIN_ROUNDS = {"quarterfinal", "semifinal", "final"}


def normalize_round(raw_round):
    if not raw_round:
        return ""
    key = str(raw_round).strip().lower()
    key = key.replace(" ", "_").replace("-", "_")
    key = re.sub(r"_+", "_", key).strip("_")
    return ROUND_ALIASES.get(key, key)


def round_display_name(round_name):
    return ROUND_DISPLAY_NAMES.get(round_name, round_name or "Раунд")


def normalize_gender(raw):
    return GENDER_MAP.get(str(raw or "").strip().lower(), "men")


def normalize_category(raw, gender):
    category = str(raw or "").strip().upper()
    if category in ("ATP", "WTA"):
        return category
    return "WTA" if gender == "women" else "ATP"


def normalize_name(raw):
    """«Australian Open Men Singles» → «Australian Open»."""
    name = str(raw or "").strip()
    for suffix in (" Men Singles", " Women Singles", " Men Doubles", " Women Doubles",
                   " Men", " Women", " Singles", " Doubles"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    for prefix in ("WTA ", "ATP ", "ITF "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip(" ,-")
    return name or str(raw or "").strip()


def normalize_key(name):
    key = str(name or "").lower()
    key = re.sub(r"[^a-z0-9]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def slugify(name):
    slug = normalize_key(name).replace(" ", "-")
    return slug or "tournament"


# === ФОТОГРАФИИ (Wikipedia / Wikimedia Commons) ===

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
PHOTO_THUMB_SIZE = 200
PHOTO_MAX_PER_RUN = 60
PHOTO_TTL_DAYS = 60
PHOTO_DELAY = 0.25


def _wiki_get(params):
    query = {"format": "json", "formatversion": "1"}
    query.update(params)
    from urllib.parse import urlencode
    url = f"{WIKIPEDIA_API}?{urlencode(query)}"
    data, error = http_get_json(url, headers={"Accept": "application/json"}, timeout=30)
    return data or {}


def _wiki_pages(data):
    pages = ((data.get("query") or {}).get("pages") or {}) if isinstance(data, dict) else {}
    if isinstance(pages, dict):
        return [p for p in pages.values() if isinstance(p, dict)]
    return [p for p in pages if isinstance(p, dict)]


def _clean_image_url(url):
    return url.split("?")[0] if url else ""


def _page_looks_like_player(page):
    description = (page.get("description") or "").lower()
    title = (page.get("title") or "").lower()
    if "tennis" in description:
        return True
    return title.endswith("(tennis)") or " tennis" in title


def player_article_title(name):
    """«Sinner, Jannik» → «Jannik Sinner»."""
    raw = str(name or "").strip()
    if "," in raw:
        last, first = raw.split(",", 1)
        raw = f"{first.strip()} {last.strip()}"
    return re.sub(r"\s+", " ", raw).strip()


def wikipedia_photo(name):
    """Ищет фотографию игрока в Wikipedia. Возвращает URL или ''."""
    article = player_article_title(name)
    if not article:
        return ""

    for title in (article, f"{article} (tennis)"):
        data = _wiki_get({
            "action": "query", "titles": title,
            "prop": "pageimages|description",
            "piprop": "thumbnail|original",
            "pithumbsize": str(PHOTO_THUMB_SIZE),
            "redirects": "1",
        })
        for page in _wiki_pages(data):
            if "missing" in page or not _page_looks_like_player(page):
                continue
            url = _clean_image_url((page.get("thumbnail") or {}).get("source"))
            if url:
                return url
        time.sleep(PHOTO_DELAY)

    # В основной статье фото может не быть — пробуем страницу со статистикой
    data = _wiki_get({
        "action": "query", "titles": f"{article} career statistics",
        "prop": "pageimages", "piprop": "thumbnail",
        "pithumbsize": str(PHOTO_THUMB_SIZE), "redirects": "1",
    })
    for page in _wiki_pages(data):
        url = _clean_image_url((page.get("thumbnail") or {}).get("source"))
        if url:
            return url
    time.sleep(PHOTO_DELAY)

    # Последний шанс — поиск по имени
    data = _wiki_get({
        "action": "query", "generator": "search",
        "gsrsearch": f"{article} tennis", "gsrlimit": "5",
        "prop": "pageimages|description", "piprop": "thumbnail|original",
        "pithumbsize": str(PHOTO_THUMB_SIZE), "redirects": "1",
    })
    best = ""
    for page in _wiki_pages(data):
        if not _page_looks_like_player(page):
            continue
        url = _clean_image_url((page.get("thumbnail") or {}).get("source"))
        if url:
            title = (page.get("title") or "").lower()
            if title in (article.lower(), f"{article.lower()} (tennis)"):
                return url
            best = best or url
    return best


def load_player_photos(players, cache_name="photos_wiki.json"):
    """Карта {id: {u: url, t: ts}} — с кэшем на PHOTO_TTL_DAYS."""
    cache = cache_read(cache_name) or {}
    now = datetime.now(timezone.utc)
    fresh = {}
    for pid, item in cache.items():
        if not isinstance(item, dict):
            continue
        try:
            age_days = (now - datetime.fromisoformat(item.get("t", ""))).days
        except ValueError:
            age_days = 999
        if age_days < PHOTO_TTL_DAYS:
            fresh[pid] = item
    cache = fresh

    missing = [(pid, name) for pid, name in players.items() if pid not in cache]
    missing.sort(key=lambda item: -players[item[0]][1])

    if missing:
        print(f"  Wikipedia: ищем фото для {len(missing)} игроков (максимум {PHOTO_MAX_PER_RUN} за запуск)")
        done = 0
        for pid, name in missing:
            if done >= PHOTO_MAX_PER_RUN:
                break
            done += 1
            try:
                url = wikipedia_photo(name)
            except Exception:  # noqa: BLE001
                url = ""
            cache[pid] = {"u": url, "t": now.isoformat(), "n": name}
            if url:
                print(f"    {name} → найдено")
        cache_write(cache_name, cache)
    return cache


# === ВЫВОД ===

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def count_matches(years):
    counts = {"main": 0, "secondary": 0, "years": len(years)}
    for year_data in years.values():
        for gender_data in year_data.values():
            counts["main"] += len(gender_data.get("main", []))
            counts["secondary"] += len(gender_data.get("secondary", []))
    return counts
