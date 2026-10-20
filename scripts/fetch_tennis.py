#!/usr/bin/env python3
"""
Grand Slam Calendar - Data Fetcher (v2)
=====================================================================
Собирает календарь турниров Большого шлема, Masters 1000 (ATP) и WTA 1000
из Sportradar Tennis API v3 и складывает их в data/ для GitHub Pages.

Источники данных (все — 1 запрос на единицу данных):
  GET /competitions.json                     — каталог турниров (уровень, пол, родитель)
  GET /seasons.json                          — сезоны всех турниров
  GET /seasons/{id}/summaries.json          — сетка матчей сезона + результаты
  GET /rankings.json                         — мировой рейтинг ATP и WTA
  GET /tennis-images-t3/.../manifest.json   — фотографии игроков (Images API)

Использование:
    python scripts/fetch_tennis.py

Требуется переменная окружения SPORTRADAR_API_KEY (GitHub Secrets).
Ключ можно получить бесплатно: https://developer.sportradar.com/

Лимит API: 1000 запросов в месяц на бесплатном тарифе.
Скрипт кэширует всё, что меняется редко (каталог турниров, завершённые сезоны,
фотографии), и обновляет только «живые» данные. Подробный расход — в конце прогона.
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
import urllib.request
import urllib.error

# === КОНФИГУРАЦИЯ ===

API_BASE = "https://api.sportradar.com/tennis/trial/v3/en"
IMAGES_BASE = "https://api.sportradar.com/tennis-images-t3"

# Уровни турниров, которые попадают в календарь
LEVELS = ("grand_slam", "atp_1000", "wta_1000", "wta_premier")

LEVEL_LABELS = {
    "grand_slam": "Большой шлем",
    "atp_1000": "Masters 1000",
    "wta_1000": "WTA 1000",
    "wta_premier": "WTA 1000",
}

# Окно расписания: сколько дней назад и вперёд смотрим в ежедневной сводке
DAYS_BACK = 3
DAYS_FORWARD = 13

# Как часто workflow запускает скрипт (часах). Нужно для оценки расхода лимита.
SCHEDULE_EVERY_HOURS = 6

# TTL кэша (часы)
TTL_COMPETITIONS = 24 * 7
TTL_SEASONS = 24 * 7
TTL_RANKINGS = 24
TTL_IMAGES = 24 * 30
TTL_FUTURE_SEASON = 24 * 2

# Задержка между запросами (секунды)
REQUEST_DELAY = 0.4

# Лимит бесплатного плана (запросов в месяц)
MONTHLY_REQUEST_LIMIT = 1000

# Безопасный порог: не расходуем квоту целиком, оставляя запас на дрейф лимита
MONTHLY_REQUEST_BUDGET = 850

# Метаданные тарифа: (ключ в ответе API, уровень доступа, что делать при коде)
# 403 — ключ недействителен или исчерпана квота, 429 — превышен лимит запросов
FATAL_STATUSES = (401, 403, 429)

# Провайдеры фотографий в Images API (пробуем по очереди, первый рабочий запоминаем)
IMAGE_PROVIDERS = ("usat", "getty", "ap", "reuters")

# Wikipedia / Wikimedia Commons — основной источник фотографий игроков
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_USER_AGENT = ("grand-slam-calendar/1.0 (https://github.com/nikstopka/grand-slam-calendar)")
PHOTO_THUMB_SIZE = 200      # размер превью в пикселях
PHOTO_MAX_PER_RUN = 60     # сколько новых игроков искать за один запуск
PHOTO_TTL_DAYS = 60        # как долго хранить найденное фото
PHOTO_DELAY = 0.25         # пауза между запросами к Wikipedia

# Версия схемы кэша: при изменении формата кэш сбрасывается
CACHE_VERSION = 3

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(PROJECT_DIR, ".cache")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
TOURNAMENTS_DIR = os.path.join(DATA_DIR, "tournaments")

# === СПРАВОЧНИКИ ===

# Оформление турниров: ключ — нормализованное название (совпадение по префиксу)
TOURNAMENT_META = {
    "australian open": ("Australian Open", "AO", "🇦🇺"),
    "roland garros": ("Roland Garros", "RG", "🇫🇷"),
    "french open": ("Roland Garros", "RG", "🇫🇷"),
    "wimbledon": ("Wimbledon", "WIM", "🇬🇧"),
    "us open": ("US Open", "USO", "🇺🇸"),
    "indian wells": ("Indian Wells", "IW", "🇺🇸"),
    "miami": ("Miami Open", "MIA", "🇺🇸"),
    "monte carlo": ("Monte-Carlo", "MC", "🇲🇨"),
    "madrid": ("Madrid Open", "MAD", "🇪🇸"),
    "rome": ("Internazionali di Roma", "ROM", "🇮🇹"),
    "internazionali bnl": ("Internazionali di Roma", "ROM", "🇮🇹"),
    "toronto": ("Toronto", "TOR", "🇨🇦"),
    "montreal": ("Montreal", "MON", "🇨🇦"),
    "cincinnati": ("Cincinnati", "CIN", "🇺🇸"),
    "shanghai": ("Shanghai", "SHA", "🇨🇳"),
    "paris": ("Paris Masters", "PAR", "🇫🇷"),
    "doha": ("Doha", "DOH", "🇶🇦"),
    "dubai": ("Dubai", "DUB", "🇦🇪"),
    "beijing": ("Beijing", "BEI", "🇨🇳"),
    "wuhan": ("Wuhan", "WUH", "🇨🇳"),
    "guangzhou": ("Guangzhou", "GZH", "🇨🇳"),
    "riyadh": ("Riyadh", "RIY", "🇸🇦"),
    "cluj": ("Cluj-Napoca", "CLJ", "🇷🇴"),
    "memphis": ("Memphis", "MEM", "🇺🇸"),
    "montpellier": ("Montpellier", "MTP", "🇫🇷"),
    "sydney": ("Sydney", "SYD", "🇦🇺"),
    "acela": ("Aceleа", "ACE", "🇺🇸"),
    "los angeles": ("Los Angeles", "LAX", "🇺🇸"),
    "wta finals": ("WTA Finals", "WTF", "🇦🇪"),
    "atp finals": ("ATP Finals", "ATF", "🇮🇹"),
    "next gen": ("Next Gen Finals", "NGF", "🇦🇪"),
}

# Названия раундов на русском
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
    "first_round": "round_of_128",
    "second_round": "round_of_64",
    "third_round": "round_of_32",
    "fourth_round": "round_of_16",
    "fifth_round": "quarterfinal",
    "sixth_round": "semifinal",
    "seventh_round": "final",
    "quarter_final": "quarterfinal",
    "quarterfinals": "quarterfinal",
    "qf": "quarterfinal",
    "semi_final": "semifinal",
    "semifinals": "semifinal",
    "sf": "semifinal",
    "qualifying_round_1": "qualification_round_1",
    "qualifying_round_2": "qualification_round_2",
    "qualifying_round_3": "qualification_round_3",
}

GENDER_MAP = {
    "female": "women", "women": "women", "woman": "women", "wta": "women", "f": "women",
    "male": "men", "men": "men", "man": "men", "atp": "men", "m": "men",
}

# Раунды, которые считаются «основными» (четвертьфиналы и дальше)
MAIN_ROUNDS = {"quarterfinal", "semifinal", "final"}

# === HTTP ===

_api_key = None
_request_count = 0
_budget = {"month": "", "used": 0}
_fatal_error = None


def get_api_key():
    global _api_key
    if _api_key is None:
        _api_key = os.environ.get("SPORTRADAR_API_KEY")
        if not _api_key:
            print("Ключ SPORTRADAR_API_KEY не задан — будет использован бесплатный провайдер.")
            return None
    return _api_key


# --- учёт месячной квоты ---

def load_budget():
    """Загружает счётчик расхода квоты за текущий календарный месяц."""
    global _budget
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    entry = cache_read("budget.json")
    if entry and entry.get("d", {}).get("month") == month:
        _budget = entry["d"]
    else:
        _budget = {"month": month, "used": 0}
    return _budget


def save_budget():
    cache_write("budget.json", _budget)


def budget_left():
    return MONTHLY_REQUEST_BUDGET - _budget.get("used", 0)


def api_get(path, params=None, base=None, allow_error=False):
    """GET-запрос к API. Возвращает (data, error)."""
    global _request_count, _fatal_error

    if _fatal_error:
        return None, _fatal_error

    if budget_left() <= 0:
        message = (f"исчерпан месячный бюджет запросов ({MONTHLY_REQUEST_BUDGET}) — "
                   "данные обновляются в следующем месяце")
        _fatal_error = message
        return None, message

    base = base or API_BASE
    query = {}
    if params:
        query.update(params)
    key = get_api_key()
    if not key:
        message = "API-ключ Sportradar не задан"
        _fatal_error = message
        return None, message
    query["api_key"] = key
    url = f"{base}{path}.json?{urlencode(query)}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    _request_count += 1
    _budget["used"] = _budget.get("used", 0) + 1

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        message = f"HTTP {e.code} ({e.reason})"
        if e.code == 429:
            message += " — превышен лимит запросов API"
            time.sleep(5)
        elif e.code in (401, 403):
            message += (" — ключ недействителен или исчерпана месячная квота "
                        "Sportradar (лимит 1000 запросов)")
        if e.code in FATAL_STATUSES:
            # Дальше ходить бессмысленно — экономим остаток квоты
            _fatal_error = message
        if not allow_error:
            print(f"  Ошибка API: {message} для {path}")
        return None, message
    except urllib.error.URLError as e:
        if not allow_error:
            print(f"  Ошибка сети: {e.reason} для {path}")
        return None, str(e.reason)
    except Exception as e:  # noqa: BLE001
        if not allow_error:
            print(f"  Непредвиденная ошибка для {path}: {e}")
        return None, str(e)


# === КЭШ ===

def cache_path(name):
    return os.path.join(CACHE_DIR, name)


def cache_read(name):
    path = cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    if payload.get("v") != CACHE_VERSION:
        return None
    return payload


def cache_write(name, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path(name), "w", encoding="utf-8") as f:
            json.dump({"v": CACHE_VERSION, "ts": datetime.now(timezone.utc).isoformat(), "d": data},
                      f, ensure_ascii=False)
    except OSError as e:
        print(f"  Не удалось сохранить кэш {name}: {e}")


def cached_json(name, ttl_hours, loader):
    """Возвращает данные из кэша либо загружает и кэширует их."""
    entry = cache_read(name)
    if entry:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(entry["ts"])).total_seconds()
        except ValueError:
            age = 1e9
        if age < ttl_hours * 3600:
            return entry["d"], True
    data, error = loader()
    if data is None:
        # Откатываемся на устаревший кэш, если он есть
        return (entry["d"], True) if entry else (None, False)
    cache_write(name, data)
    return data, False


# === НОРМАЛИЗАЦИЯ ===

def normalize_round(raw_round):
    if not raw_round:
        return ""
    key = str(raw_round).strip().lower().replace(" ", "_").replace("-", "_")
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
    """Приводит название турнира к виду «Indian Wells» (без пола и типа)."""
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
    """Ключ для поиска в справочнике: только буквы и цифры, через пробел."""
    key = str(name or "").lower()
    key = re.sub(r"[^a-z0-9]+", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def tournament_meta(base_name):
    """Возвращает (display, short, icon) для турнира."""
    key = normalize_key(base_name)
    # Сначала самые длинные ключи, чтобы «monte carlo» не перебивался «miami»
    for candidate in sorted(TOURNAMENT_META, key=len, reverse=True):
        if key == candidate or key.startswith(candidate + " ") or key.startswith(candidate):
            return TOURNAMENT_META[candidate]
    return (base_name, base_name[:3].upper(), "🎾")


def slugify(name):
    slug = normalize_key(name).replace(" ", "-")
    return slug or "tournament"


# === НОРМАЛИЗАЦИЯ МАТЧА ===

def normalize_match(summary):
    """Приводит summary из API к компактному внутреннему формату."""
    sport_event = summary.get("sport_event", {}) or {}
    status_block = summary.get("sport_event_status", {}) or {}
    context = sport_event.get("sport_event_context", {}) or {}
    competitors = sport_event.get("competitors", []) or []

    round_name = normalize_round((context.get("round", {}) or {}).get("name", ""))
    stage = context.get("stage", {}) or {}
    is_qualification = stage.get("phase") == "qualification" or round_name.startswith("qualification")

    competition = context.get("competition", {}) or {}
    gender = normalize_gender(competition.get("gender", ""))
    category = normalize_category((context.get("category", {}) or {}).get("name", ""), gender)

    status = status_block.get("status", "not_started")

    players = []
    for comp in competitors:
        if comp.get("virtual"):
            continue
        player = {
            "id": comp.get("id", ""),
            "name": comp.get("name", "TBD"),
            "country_code": comp.get("country_code", "") or "",
            "qualifier": comp.get("qualifier", ""),
        }
        if comp.get("seed"):
            player["seed"] = comp["seed"]
        players.append(player)

    match = {
        "id": sport_event.get("id", ""),
        "round": round_name,
        "round_display": round_display_name(round_name),
        "gender": gender,
        "category": category,
        "start_time": sport_event.get("start_time", ""),
        "status": status,
        "match_status": status_block.get("match_status", "") or "",
        "best_of": (context.get("mode", {}) or {}).get("best_of", 3),
        "players": players,
    }

    if is_qualification:
        match["is_qualification"] = True

    venue = sport_event.get("venue", {}) or {}
    if venue.get("name"):
        match["venue"] = venue["name"]
    if venue.get("city_name"):
        match["city"] = venue["city_name"]
    if venue.get("timezone"):
        match["timezone"] = venue["timezone"]

    if status in ("closed", "live", "ended") and status_block.get("period_scores"):
        periods = []
        for ps in status_block["period_scores"]:
            period = {
                "home": ps.get("home_score", 0),
                "away": ps.get("away_score", 0),
                "number": ps.get("number", 0),
            }
            if ps.get("home_tiebreak_score") is not None:
                period["home_tb"] = ps["home_tiebreak_score"]
                period["away_tb"] = ps.get("away_tiebreak_score", 0)
            periods.append(period)
        match["scores"] = {
            "home": status_block.get("home_score", 0),
            "away": status_block.get("away_score", 0),
            "periods": periods,
        }

    if status_block.get("winner_id"):
        match["winner_id"] = status_block["winner_id"]

    return match


def is_main_round(match):
    return match.get("round") in MAIN_ROUNDS


# === КАТАЛОГ ТУРНИРОВ ===

def load_competitions():
    """Каталог турниров: id, название, уровень, пол, родительская группа."""
    data, from_cache = cached_json(
        "competitions.json", TTL_COMPETITIONS,
        lambda: api_get("/competitions"),
    )
    if not data:
        return None

    groups = {}
    for comp in data.get("competitions", []) or []:
        if (comp.get("type") or "").lower() != "singles":
            continue
        level = (comp.get("level") or "").lower()
        if level not in LEVELS:
            continue

        gender = normalize_gender(comp.get("gender", ""))
        base = normalize_name(comp.get("name", ""))
        parent = comp.get("parent_id") or f"name:{normalize_key(base)}"

        group = groups.setdefault(parent, {
            "id": parent,
            "level": level,
            "base_names": [],
            "genders": set(),
            "competitions": [],
        })
        if base not in group["base_names"]:
            group["base_names"].append(base)
        group["genders"].add(gender)
        group["competitions"].append({
            "id": comp.get("id", ""),
            "name": comp.get("name", ""),
            "gender": gender,
            "level": level,
        })

    tournaments = []
    for group in groups.values():
        bases = group["base_names"]
        # Турниры с разными названиями в одной группе (Toronto/Montreal) — объединяем
        if len(bases) == 1:
            base = bases[0]
        else:
            base = " / ".join(sorted(bases))
        display, short, icon = tournament_meta(bases[0])
        tournaments.append({
            "id": group["id"],
            "base": base,
            "name": display,
            "short": short,
            "icon": icon,
            "level": group["level"],
            "level_label": LEVEL_LABELS.get(group["level"], group["level"]),
            "genders": sorted(group["genders"]),
            "competitions": group["competitions"],
        })

    # Большой шлем — первыми, внутри — по алфавиту
    order = {"grand_slam": 0, "atp_1000": 1, "wta_1000": 2, "wta_premier": 2}
    tournaments.sort(key=lambda t: (order.get(t["level"], 9), t["name"]))
    return tournaments


def load_seasons():
    """Все сезоны всех турниров: {competition_id: [season, ...]}."""
    data, from_cache = cached_json(
        "seasons.json", TTL_SEASONS,
        lambda: api_get("/seasons"),
    )
    if not data:
        return None

    by_competition = {}
    for season in data.get("seasons", []) or []:
        comp_id = season.get("competition_id")
        if not comp_id:
            continue
        by_competition.setdefault(comp_id, []).append({
            "id": season.get("id", ""),
            "name": season.get("name", ""),
            "year": str(season.get("year", "") or ""),
            "start_date": season.get("start_date", ""),
            "end_date": season.get("end_date", ""),
        })
    return by_competition


def season_year(season):
    """Год сезона: 4-значный из поля year, иначе из start_date."""
    year = str(season.get("year", "") or "")
    if re.fullmatch(r"(19|20)\d{2}", year):
        return year
    start = season.get("start_date", "")
    if re.match(r"(19|20)\d{2}", start):
        return start[:4]
    return ""


def season_is_active(season, today):
    start = season.get("start_date", "")
    end = season.get("end_date", "")
    if not start or not end:
        return True
    return start <= today <= end


# === СЕТКА МАТЧЕЙ ===

def fetch_season_matches(season, today):
    """Все матчи сезона (с постраничным обходом) в нормализованном виде."""
    season_id = season["id"]
    cache_name = f"season_{season_id.replace(':', '_')}.json"

    def loader():
        return load_season_summaries(season_id)

    entry = cache_read(cache_name)
    if entry:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(entry["ts"])).total_seconds()
        except ValueError:
            age = 1e9
        active = season_is_active(season, today)
        ttl = 0 if active else (TTL_FUTURE_SEASON if season.get("start_date", "") > today else 10 ** 7)
        if age < ttl * 3600:
            return entry["d"], True

    data, error = loader()
    if data is None:
        return (entry["d"], True) if entry else (None, False)
    cache_write(cache_name, data)
    return data, False


def load_season_summaries(season_id):
    """Постранично забирает summaries сезона и нормализует матчи.

    Возвращает кортеж (matches, error).
    """
    matches = []
    seen = set()
    start = 0
    limit = 200

    while True:
        data, error = api_get(f"/seasons/{season_id}/summaries", {"limit": limit, "start": start})
        if not data:
            return None, error or "не удалось загрузить сезон"
        summaries = data.get("summaries", []) or []
        for summary in summaries:
            match = normalize_match(summary)
            if not match["id"] or match["id"] in seen:
                continue
            seen.add(match["id"])
            matches.append(match)
        if len(summaries) < limit:
            break
        start += limit
        if start > 2000:  # защита от бесконечного цикла
            break
        time.sleep(REQUEST_DELAY)
    return matches, None


# === РЕЙТИНГ ===

def load_rankings():
    """Мировой рейтинг ATP и WTA (по одному запросу)."""
    data, from_cache = cached_json(
        "rankings.json", TTL_RANKINGS,
        lambda: api_get("/rankings"),
    )
    if not data:
        return None

    result = {"men": [], "women": []}
    for league in data.get("rankings", []) or []:
        gender = normalize_gender(league.get("gender", "men"))
        bucket = result.setdefault(gender, [])
        for row in league.get("competitor_rankings", []) or []:
            competitor = row.get("competitor", {}) or {}
            bucket.append({
                "rank": row.get("rank", 0),
                "movement": row.get("movement", 0),
                "points": row.get("points", 0),
                "played": row.get("competitions_played", 0),
                "id": competitor.get("id", ""),
                "name": competitor.get("name", ""),
                "country_code": competitor.get("country_code", "") or "",
            })
    for bucket in result.values():
        bucket.sort(key=lambda r: r["rank"])
    return result


# === ФОТОГРАФИИ ===

def extract_assets(data):
    """Достаёт список изображений из манифеста Images API (формат может различаться)."""
    if not isinstance(data, dict):
        return []
    for key in ("assets", "players", "images"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return value
    assetlist = data.get("assetlist")
    if isinstance(assetlist, dict):
        for value in assetlist.values():
            if isinstance(value, list) and value:
                return value
    # Рекурсивный поиск первого списка объектов с полем id
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            if node and isinstance(node[0], dict) and "id" in node[0]:
                return node
            stack.extend(node)
    return []


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def extract_assets(data):
    """Достаёт список изображений из манифеста Images API (формат может различаться)."""
    if not isinstance(data, dict):
        return []
    for key in ("assets", "players", "images"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return value
    assetlist = data.get("assetlist")
    if isinstance(assetlist, dict):
        for value in assetlist.values():
            if isinstance(value, list) and value:
                return value
    # Рекурсивный поиск первого списка объектов с полем id
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            if node and isinstance(node[0], dict) and "id" in node[0]:
                return node
            stack.extend(node)
    return []


# === ФОТОГРАФИИ ИГРОКОВ ===

def wikipedia_get(params):
    """Запрос к Wikipedia API. Возвращает (data, error)."""
    query = {"format": "json", "formatversion": "1"}
    query.update(params)
    url = f"{WIKIPEDIA_API}?{urlencode(query)}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": WIKIPEDIA_USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def wiki_pages(data):
    if not data:
        return []
    query = data.get("query", {}) or {}
    pages = query.get("pages", {}) or {}
    if isinstance(pages, dict):
        return [p for p in pages.values() if isinstance(p, dict)]
    return [p for p in as_list(pages) if isinstance(p, dict)]


def clean_image_url(url):
    """Убирает трекинговые utm-параметры из ссылки на изображение."""
    if not url:
        return ""
    return url.split("?")[0]


def page_looks_like_player(page):
    """Проверяет, что страница — про теннисиста."""
    description = (page.get("description") or "").lower()
    title = (page.get("title") or "").lower()
    if "tennis" in description:
        return True
    # У статьи может не быть короткого описания — смотрим на заголовок
    return title.endswith("(tennis)") or " tennis" in title


def player_article_title(name):
    """'Sinner, Jannik' -> 'Jannik Sinner'"""
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

    # 1. Прямой запрос статьи: сначала основная, затем с уточнением (tennis)
    candidates = [article, f"{article} (tennis)"]
    for title in candidates:
        data, _error = wikipedia_get({
            "action": "query",
            "titles": title,
            "prop": "pageimages|description",
            "piprop": "thumbnail|original",
            "pithumbsize": str(PHOTO_THUMB_SIZE),
            "redirects": "1",
        })
        for page in wiki_pages(data):
            if "missing" in page:
                continue
            if not page_looks_like_player(page):
                continue
            url = clean_image_url((page.get("thumbnail") or {}).get("source"))
            if url:
                return url
        time.sleep(PHOTO_DELAY)

    # 2. У статьи может не быть фото — пробуем страницу со статистикой
    data, _error = wikipedia_get({
        "action": "query",
        "titles": f"{article} career statistics",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": str(PHOTO_THUMB_SIZE),
        "redirects": "1",
    })
    for page in wiki_pages(data):
        url = clean_image_url((page.get("thumbnail") or {}).get("source"))
        if url:
            return url
    time.sleep(PHOTO_DELAY)

    # 3. Поиск по имени
    data, _error = wikipedia_get({
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{article} tennis",
        "gsrlimit": "5",
        "prop": "pageimages|description",
        "piprop": "thumbnail|original",
        "pithumbsize": str(PHOTO_THUMB_SIZE),
        "redirects": "1",
    })
    best = ""
    for page in wiki_pages(data):
        if not page_looks_like_player(page):
            continue
        url = clean_image_url((page.get("thumbnail") or {}).get("source"))
        if url:
            title = (page.get("title") or "").lower()
            # приоритет: точное совпадение названия
            if title == article.lower() or title == f"{article.lower()} (tennis)":
                return url
            best = best or url
    return best


def collect_players(tournament_files):
    """Собирает уникальных игроков: {competitor_id: (имя, число матчей)}."""
    players = {}
    for data in tournament_files:
        for year_data in (data.get("years") or {}).values():
            for gender_data in year_data.values():
                for key in ("main", "secondary"):
                    for match in gender_data.get(key, []):
                        for player in match.get("players", []):
                            pid = player.get("id")
                            if not pid:
                                continue
                            entry = players.setdefault(pid, [player.get("name", ""), 0])
                            entry[1] += 1
    return {pid: (name, count) for pid, (name, count) in players.items()}


def load_player_photos(players):
    """Карта {competitor_id: url_фото}.

    Сначала пробуем Images API Sportradar, затем — Wikipedia.
    """
    photos = {}

    # --- Sportradar Images API (если есть доступ) ---
    entry = cache_read("photos_sportradar.json")
    manifest_ok = False
    if entry:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(entry["ts"])).total_seconds()
        except ValueError:
            age = 1e9
        if age < TTL_IMAGES * 3600:
            manifest_ok = entry["d"].get("ok", False)
            photos.update(entry["d"].get("photos", {}))

    if not manifest_ok:
        year = datetime.now(timezone.utc).year
        found = {}
        for provider in IMAGE_PROVIDERS:
            base = f"{IMAGES_BASE}/{provider}/tennis/headshots/players"
            data, error = api_get(f"/{year}/manifest", base=base, allow_error=True)
            if not data:
                continue
            for asset in extract_assets(data):
                if not isinstance(asset, dict):
                    continue
                asset_id = asset.get("id", "")
                if not asset_id:
                    continue
                href = None
                for link in as_list(asset.get("links")):
                    if not isinstance(link, dict):
                        continue
                    link_href = link.get("href", "")
                    if "crop" in link_href or link_href.endswith((".jpg", ".png")):
                        href = link_href
                        break
                if not href:
                    continue
                competitor_id = None
                for ref in as_list(asset.get("refs")):
                    if not isinstance(ref, dict):
                        continue
                    srid = ref.get("sportradar_id", "")
                    if srid.startswith("sr:competitor:"):
                        competitor_id = srid
                        break
                if competitor_id:
                    found[competitor_id] = f"{base}{href}"
            if found:
                break
        photos.update(found)
        cache_write("photos_sportradar.json", {"ok": bool(found), "photos": found})
        if found:
            print(f"  Фотографии Sportradar: {len(found)} изображений")
        else:
            print("  Фотографии Sportradar: Images API недоступен, используем Wikipedia")

    # --- Wikipedia ---
    wiki_entry = cache_read("photos_wiki.json")
    wiki_cache = dict(wiki_entry["d"]) if wiki_entry and isinstance(wiki_entry.get("d"), dict) else {}
    now_ts = datetime.now(timezone.utc).isoformat()

    # Убираем протухшие записи
    fresh = {}
    for pid, item in wiki_cache.items():
        if not isinstance(item, dict):
            continue
        try:
            age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(item.get("t", ""))).days
        except ValueError:
            age_days = 999
        if age_days < PHOTO_TTL_DAYS:
            fresh[pid] = item
    wiki_cache = fresh

    missing = []
    for pid, (name, _count) in players.items():
        if pid in photos:
            continue
        if pid in wiki_cache:
            url = wiki_cache[pid].get("u", "")
            if url:
                photos[pid] = url
                continue
            # в кэше есть запись «фото не найдено» — не ищем повторно
            continue
        missing.append((pid, name))

    # Сначала обслуживаем самых частых игроков — их видно чаще всего
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
            except Exception as e:  # noqa: BLE001
                print(f"    {name}: ошибка {e}")
                url = ""
            wiki_cache[pid] = {"u": url, "t": now_ts, "n": name}
            if url:
                photos[pid] = url
        cache_write("photos_wiki.json", wiki_cache)
        found_count = sum(1 for v in wiki_cache.values() if v.get("u"))
        print(f"  Wikipedia: найдено {found_count} фото всего, за этот запуск — {done}")

    return photos


# === СБОРКА ===

def build_tournament_file(tournament, seasons_by_comp, today):
    """Собирает файл турнира: годы → пол → основные/второстепенные."""
    years = {}

    for comp in tournament["competitions"]:
        seasons = seasons_by_comp.get(comp["id"], []) or []
        for season in seasons:
            year = season_year(season)
            if not year:
                continue
            matches, from_cache = fetch_season_matches(season, today)
            if not matches:
                continue
            for match in matches:
                match["gender"] = comp["gender"]
                match["category"] = normalize_category(match.get("category"), comp["gender"])
                bucket = years.setdefault(year, {}).setdefault(
                    comp["gender"], {"main": [], "secondary": []}
                )
                bucket["main" if is_main_round(match) else "secondary"].append(match)

    # Сортировка: по времени, live первее, завершённые — свежие сверху
    for year_data in years.values():
        for gender_data in year_data.values():
            for key in ("main", "secondary"):
                gender_data[key].sort(key=lambda m: (m.get("start_time") or ""))

    return {
        "id": tournament["id"],
        "name": tournament["name"],
        "short": tournament["short"],
        "icon": tournament["icon"],
        "level": tournament["level"],
        "level_label": tournament["level_label"],
        "genders": tournament["genders"],
        "years": years,
    }


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def main():
    print("=" * 60)
    print("  Tennis Calendar - Обновление данных")
    print("=" * 60)
    print()

    load_budget()
    print(f"Квота API: {_budget.get('used', 0)} из {MONTHLY_REQUEST_BUDGET} "
          f"использовано в {_budget.get('month')}")
    print()

    try:
        run()
    finally:
        save_budget()


def run():
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    print("Каталог турниров...")
    tournaments = load_competitions()
    if not tournaments:
        print()
        print("Sportradar недоступен:", _fatal_error or "нет данных о турнирах")
        print("Переключаемся на бесплатный провайдер "
              "(TennisMyLife + SportScore + Wikipedia)...")
        print()
        import free_provider
        free_provider.run()
        sys.exit(0)
    print(f"  Турниров: {len(tournaments)}")

    print("Сезоны...")
    seasons_by_comp = load_seasons()
    if not seasons_by_comp:
        print()
        print("Sportradar недоступен:", _fatal_error or "нет данных о сезонах")
        print("Переключаемся на бесплатный провайдер "
              "(TennisMyLife + SportScore + Wikipedia)...")
        print()
        import free_provider
        free_provider.run()
        sys.exit(0)

    print("Рейтинг ATP/WTA...")
    rankings = load_rankings()
    if rankings:
        print(f"  ATP: {len(rankings.get('men', []))}, WTA: {len(rankings.get('women', []))}")

    print("Сетки матчей...")
    index = []
    tournament_files = []
    for tournament in tournaments:
        data = build_tournament_file(tournament, seasons_by_comp, today)
        slug = slugify(data["name"])
        write_json(os.path.join(TOURNAMENTS_DIR, f"{slug}.json"), data)
        tournament_files.append(data)

        counts = {"main": 0, "secondary": 0, "years": 0}
        for year_data in data["years"].values():
            counts["years"] += 1
            for gender_data in year_data.values():
                counts["main"] += len(gender_data["main"])
                counts["secondary"] += len(gender_data["secondary"])

        index.append({
            "slug": slug,
            "name": data["name"],
            "short": data["short"],
            "icon": data["icon"],
            "level": data["level"],
            "level_label": data["level_label"],
            "genders": data["genders"],
            "years": sorted(data["years"].keys(), reverse=True),
            "counts": counts,
        })
        print(f"  {data['name']}: {counts['years']} год(а), "
              f"основных {counts['main']}, второстепенных {counts['secondary']}")

    print("Фотографии игроков...")
    players = collect_players(tournament_files)
    # Игроки из рейтинга тоже нужны — у них высокий приоритет
    for row in (rankings or {}).get("men", []) + (rankings or {}).get("women", []):
        pid = row.get("id")
        if pid and pid not in players:
            players[pid] = (row.get("name", ""), 100)
    photos = load_player_photos(players)

    # Убираем устаревшие файлы турниров, которых больше нет в каталоге
    valid = {f"{t['slug']}.json" for t in index}
    if os.path.isdir(TOURNAMENTS_DIR):
        for filename in os.listdir(TOURNAMENTS_DIR):
            if filename.endswith(".json") and filename not in valid:
                os.remove(os.path.join(TOURNAMENTS_DIR, filename))
                print(f"  Удалён устаревший файл: {filename}")

    write_json(os.path.join(DATA_DIR, "index.json"), {
        "last_updated": now.isoformat(),
        "tournaments": index,
    })
    write_json(os.path.join(DATA_DIR, "rankings.json"), {
        "last_updated": now.isoformat(),
        "men": (rankings or {}).get("men", []),
        "women": (rankings or {}).get("women", []),
    })
    write_json(os.path.join(DATA_DIR, "players.json"), photos)

    # Старый формат больше не используется
    legacy = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(legacy):
        os.remove(legacy)

    runs_per_day = 24 / SCHEDULE_EVERY_HOURS
    # Одновременно идут обычно 2-3 крупных турнира — их сетки обновляем каждый запуск;
    # будущие сезоны перепроверяются раз в TTL_FUTURE_SEASON суток
    per_day = (
        3 * runs_per_day
        + 6 * (24 / TTL_FUTURE_SEASON)
        + 1        # рейтинг
        + 0.5      # каталоги турниров и сезонов
    )
    monthly = per_day * 30
    print()
    print(f"Данные сохранены в {DATA_DIR}")
    print(f"Запросов за этот прогон: {_request_count}")
    print(f"Квота за {_budget.get('month')}: {_budget.get('used', 0)} из {MONTHLY_REQUEST_BUDGET} "
          f"(лимит Sportradar — {MONTHLY_REQUEST_LIMIT})")
    print(f"Прогноз расхода: ~{monthly:.0f} запросов/месяц")
    print("\nГотово!")


if __name__ == "__main__":
    main()
