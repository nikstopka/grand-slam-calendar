#!/usr/bin/env python3
"""Бесплатный провайдер данных — используется, когда ключ Sportradar недоступен.

Источники (все без API-ключа):
  • TennisMyLife  — https://stats.tennismylife.org/data/  (результаты ATP/WTA по годам)
  • SportScore    — https://sportscore.com/api/widget/   (live, расписание, фото игроков)
  • Wikipedia     — фото игроков и текущий мировой рейтинг ATP/WTA

Формат выходных файлов совпадает с форматом провайдера Sportradar,
поэтому фронтенд работает с обоими без изменений.
"""
import csv
import io
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

# Чтобы sibling-модуль common находился при любом способе запуска
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from common import (DATA_DIR, TOURNAMENTS_DIR, cache_read, cache_write, count_matches,
                    http_get, http_get_json, load_player_photos, normalize_key,
                    round_display_name, slugify, write_json)

# === ИСТОЧНИКИ ===

TML_BASE = "https://stats.tennismylife.org/data"
SPORTSCORE_MATCHES = "https://sportscore.com/api/widget/matches/?sport=tennis&limit=40"

WIKI_RANKINGS = {
    "men": ("ATP_rankings", 8),
    "women": ("WTA_rankings", 3),
}

# Сколько лет истории тянуть (текущий + предыдущие)
HISTORY_YEARS = 3

# === МАППИНГ ТУРНИРОВ ===

# Название турнира в TennisMyLife → (название, короткое, флаг, уровень)
GRAND_SLAM_KEYS = {"australian open", "roland garros", "wimbledon", "us open"}

TML_TOURNAMENTS = {
    "australian open": ("Australian Open", "AO", "🇦🇺", "grand_slam"),
    "roland garros": ("Roland Garros", "RG", "🇫🇷", "grand_slam"),
    "wimbledon": ("Wimbledon", "WIM", "🇬🇧", "grand_slam"),
    "us open": ("US Open", "USO", "🇺🇸", "grand_slam"),
    "indian wells masters": ("Indian Wells", "IW", "🇺🇸", "masters"),
    "indian wells": ("Indian Wells", "IW", "🇺🇸", "masters"),
    "miami masters": ("Miami Open", "MIA", "🇺🇸", "masters"),
    "miami": ("Miami Open", "MIA", "🇺🇸", "masters"),
    "monte carlo": ("Monte-Carlo", "MC", "🇲🇨", "masters"),
    "madrid masters": ("Madrid Open", "MAD", "🇪🇸", "masters"),
    "madrid": ("Madrid Open", "MAD", "🇪🇸", "masters"),
    "rome masters": ("Internazionali di Roma", "ROM", "🇮🇹", "masters"),
    "rome": ("Internazionali di Roma", "ROM", "🇮🇹", "masters"),
    "canada masters": ("Toronto / Montreal", "TOR", "🇨🇦", "masters"),
    "toronto": ("Toronto / Montreal", "TOR", "🇨🇦", "masters"),
    "montreal": ("Toronto / Montreal", "TOR", "🇨🇦", "masters"),
    "cincinnati masters": ("Cincinnati", "CIN", "🇺🇸", "masters"),
    "shanghai": ("Shanghai", "SHA", "🇨🇳", "masters"),
    "paris masters": ("Paris Masters", "PAR", "🇫🇷", "masters"),
    "doha": ("Doha", "DOH", "🇶🇦", "masters"),
    "dubai": ("Dubai", "DUB", "🇦🇪", "masters"),
    "beijing": ("Beijing", "BEI", "🇨🇳", "masters"),
    "wuhan": ("Wuhan", "WUH", "🇨🇳", "masters"),
}

# Короткие описания турниров для титульной страницы и карточки турнира.
# Текст вручную: машинный перевод википедии читается хуже.
TOURNAMENT_DESCRIPTIONS = {
    "australian-open":
        "Открывает сезон и Большой шлем: первый турнир года проходит в Мельбурне "
        "на хардовом покрытии в середине января. Здесь традиционно разыгрываются "
        "первые очки и рейтинг Большого шлема, а все четыре лидера мирового рейтинга "
        "выступают с первого круга.",
    "roland-garros":
        "Второй Большой шлем сезона, единственный, который играют на грунте. "
        "Проводится на кортах Ролан-Гаррос в Париже, знаменитых глиняной пылью "
        "и медленной подачей: здесь выигрывают игроки с выносливостью и терпением "
        "в длинных розыгрышах.",
    "wimbledon":
        "Третий Большой шлем и единственный турнир на траве. Лондонский чемпионат "
        "с самой длинной историей и главным правилом — все матчи играются до полного "
        "счёта. Титул здесь считается самым престижным в мире тенниса.",
    "us-open":
        "Закрывает сезон Большого шлема: проходит в Нью-Йорке на хардовом покрытии "
        "в конце августа — начале сентября. Считается самым быстрым из четырёх — "
        "подача решает эпизод за несколько ударов, а трибуны заполнены "
        "по окончании финала.",
    "indian-wells":
        "Первый Masters 1000 сезона и самый престижный в серии. Проходит в Калифорнии "
        "на харде в марте в «саду тенниса Indian Wells» — крупнейшем стадионе мира. "
        "32 лучших игрока планеты играют здесь по сокращённой сетке.",
    "miami-open":
        "Второй по престижу Masters 1000 и самый посещаемый теннисный турнир в мире. "
        "Играют в Miami Gardens во Флориде на харде, зрительские трибуны "
        "вместимостью десятки тысяч и знаменитые вечерние сессии под открытым небом.",
    "monte-carlo":
        "Первый турнир на грунте среди Masters 1000. Соревнования проходят на "
        "территории Моно-Карло — княжества на Лазурном берегу, откуда и название. "
        "Победа здесь особенно ценна: она даёт кредит на грунтовую часть сезона.",
    "madrid-open":
        "Второй грунтовый Masters 1000 и самый высокий по рейтингу из всех: за "
        "победу здесь дают больше очков, чем в большинстве других турниров. "
        "Проходит в Мадриде на специально построенной арене Caja Mágica — корты "
        "быстрые, поэтому грунтовые матчи часто решаются подачей.",
    "internazionali-di-roma":
        "Третий грунтовый Masters 1000 и самый посещаемый в Европе. Играют на "
        "Foro Italico — историческом римском стадионе, где проходил олимпийский "
        "теннис. Стартует прямо перед Ролан-Гаррос, поэтому очки здесь ценятся "
        "особенно высоко.",
    "toronto-montreal":
        "Турнир Masters 1000 в Канаде, ежегодно меняющий город: один год — Торонто, "
        "другой — Монреаль. Играют на харде в августе, между Уимблдоном и US Open, "
        "и традиционно привлекают лучших игроков планеты.",
    "cincinnati":
        "Мастерс, который открывает североамериканскую часть сезона. Проходит в "
        "Цинциннати на харде в августе, известен скоростью кортов и громкой "
        "атмосферой. Победа здесь — последняя серьёзная репетиция перед US Open.",
    "shanghai":
        "Последний Masters 1000 года, открывающий азиатский отрезок календаря. "
        "Проходит в октябре в Шанхае на кортах Qizhong Forest Sports City Arena. "
        "Победитель получает путёвку на итоговый турнир ATP.",
    "paris-masters":
        "Закрывает серию Masters 1000 — последний турнир регулярного сезона. "
        "Проходит в Париже в ноябре на новой арене La Défense Arena. Победители "
        "этого турнира едут на итоговый турнир ATP.",
}

# Рейтинг ATP/WTA: топ-100 с TennisExplorer (без ключа) и топ-20 с Википедии
TENNISEXPLORER_RANKINGS = {
    "men": "https://www.tennisexplorer.com/ranking/atp-men/",
    "women": "https://www.tennisexplorer.com/ranking/wta-women/",
}

# Ключевое слово в названии турнира SportScore → наш турнир
SPORTSCORE_TOURNAMENTS = [
    ("australian open", "Australian Open"),
    ("roland garros", "Roland Garros"),
    ("french open", "Roland Garros"),
    ("wimbledon", "Wimbledon"),
    ("us open", "US Open"),
    ("indian wells", "Indian Wells"),
    ("miami", "Miami Open"),
    ("monte-carlo", "Monte-Carlo"),
    ("monte carlo", "Monte-Carlo"),
    ("madrid", "Madrid Open"),
    ("rome", "Internazionali di Roma"),
    ("toronto", "Toronto / Montreal"),
    ("montreal", "Toronto / Montreal"),
    ("cincinnati", "Cincinnati"),
    ("shanghai", "Shanghai"),
    ("paris", "Paris Masters"),
    ("doha", "Doha"),
    ("dubai", "Dubai"),
    ("beijing", "Beijing"),
    ("wuhan", "Wuhan"),
]

# Раунды TennisMyLife → внутренние названия
TML_ROUNDS = {
    "R128": "round_of_128",
    "R64": "round_of_64",
    "R32": "round_of_32",
    "R16": "round_of_16",
    "QF": "quarterfinal",
    "SF": "semifinal",
    "F": "final",
}

# Уровни турниров в TennisMyLife
TML_LEVELS = {"G": "grand_slam", "M": "masters"}

MAIN_ROUNDS = {"quarterfinal", "semifinal", "final"}


# === ПАРСИНГ ===

def name_to_last_first(name):
    """«Arthur Fery» → «Fery, Arthur»."""
    raw = str(name or "").strip()
    if not raw or "," in raw:
        return raw
    parts = raw.split()
    if len(parts) < 2:
        return raw
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def parse_score(score):
    """«7-6(1) 6-4 6-1» → [{'home': 7, 'away': 6}, ...] (с точки зрения победителя)."""
    periods = []
    for token in str(score or "").split():
        match = re.match(r"^(\d+)-(\d+)(?:\((\d+)\))?$", token)
        if not match:
            continue
        period = {"home": int(match.group(1)), "away": int(match.group(2))}
        if match.group(3) is not None:
            period["home_tb"] = int(match.group(3))
        periods.append(period)
    return periods


def parse_date(raw):
    """«20260118» → «2026-01-18T12:00:00+00:00»."""
    text = str(raw or "").strip()
    if not re.fullmatch(r"\d{8}", text):
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}T12:00:00+00:00"


# === TENNISMYLIFE ===

def fetch_tml_year(year, tour, ongoing=False):
    """CSV за год и тур. tour: 'atp' | 'wta'. ongoing — текущие турниры."""
    if ongoing:
        name = "wta_ongoing_tourneys.csv" if tour == "wta" else "ongoing_tourneys.csv"
    else:
        name = f"{year}_wta.csv" if tour == "wta" else f"{year}.csv"
    url = f"{TML_BASE}/{name}"
    cache_name = f"tml_{tour}_{'ongoing' if ongoing else year}.csv"

    cached = cache_read(cache_name)
    if cached and cached.get("data"):
        try:
            age_h = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(cached["ts"])).total_seconds() / 3600
        except ValueError:
            age_h = 999
        if age_h < (2 if ongoing else 12):
            return cached["data"]

    text, error = http_get(url, headers={"Accept": "text/csv"}, timeout=120)
    if text is None:
        print(f"  TennisMyLife {tour.upper()} {name}: ошибка — {error}")
        return cached.get("data") if cached else None

    cache_write(cache_name, {"ts": datetime.now(timezone.utc).isoformat(), "data": text})
    return text


def parse_tml(text, tour):
    """CSV → список матчей в нашем формате."""
    if not text:
        return []
    matches = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        tourney = (row.get("tourney_name") or "").strip()
        key = normalize_key(tourney)
        meta = TML_TOURNAMENTS.get(key)
        if not meta:
            continue
        level = TML_LEVELS.get((row.get("tourney_level") or "").strip())
        if not level or level != meta[3]:
            continue

        round_name = TML_ROUNDS.get((row.get("round") or "").strip())
        if not round_name:
            continue

        gender = "women" if tour == "wta" else "men"
        category = "WTA" if gender == "women" else "ATP"

        winner_id = f"tml:{tour}:{row.get('winner_id') or row.get('winner_name')}"
        loser_id = f"tml:{tour}:{row.get('loser_id') or row.get('loser_name')}"
        match_id = f"tml:{tour}:{row.get('tourney_id')}:{row.get('match_num')}"

        home = {
            "id": winner_id,
            "name": name_to_last_first(row.get("winner_name")),
            "country_code": (row.get("winner_ioc") or "").strip(),
            "qualifier": "home",
        }
        away = {
            "id": loser_id,
            "name": name_to_last_first(row.get("loser_name")),
            "country_code": (row.get("loser_ioc") or "").strip(),
            "qualifier": "away",
        }
        for player, seed_key in ((home, "winner_seed"), (away, "loser_seed")):
            seed = (row.get(seed_key) or "").strip()
            if seed:
                player["seed"] = seed

        periods = parse_score(row.get("score"))
        match = {
            "id": match_id,
            "round": round_name,
            "round_display": round_display_name(round_name),
            "gender": gender,
            "category": category,
            "start_time": parse_date(row.get("tourney_date")),
            "status": "closed",
            "match_status": "ended",
            "best_of": int(row.get("best_of") or 3),
            "players": [home, away],
            "winner_id": winner_id,
            "_tourney": meta[0],
            "_level": meta[3],
        }
        if periods:
            match["scores"] = {
                "home": sum(1 for p in periods if p["home"] > p["away"]),
                "away": sum(1 for p in periods if p["away"] > p["home"]),
                "periods": periods,
            }
        matches.append(match)
    return matches


# === SPORTSCORE ===

def fetch_sportscore():
    """Live и предстоящие матчи (с коротким кэшем, чтобы не долбить источник)."""
    cached = cache_read("sportscore.json")
    if cached and cached.get("data") is not None:
        try:
            age_min = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(cached["ts"])).total_seconds() / 60
        except ValueError:
            age_min = 999
        if age_min < 10:
            return cached["data"]

    data, error = http_get_json(SPORTSCORE_MATCHES, timeout=30, retries=2)
    if not data:
        print(f"  SportScore: недоступен — {error}")
        return cached.get("data") if cached else []
    matches = []
    for item in data.get("matches", []) or []:
        competition = (item.get("competition") or "").lower()
        tourney = None
        for keyword, name in SPORTSCORE_TOURNAMENTS:
            if keyword in competition:
                tourney = name
                break
        if not tourney:
            continue

        status = item.get("status") or ""
        if status not in ("live", "upcoming"):
            continue

        gender = "women" if "wta" in competition else "men"
        category = "WTA" if gender == "women" else "ATP"
        home = {
            "id": f"ss:{normalize_key(item.get('home'))}",
            "name": item.get("home") or "TBD",
            "country_code": "",
            "qualifier": "home",
        }
        away = {
            "id": f"ss:{normalize_key(item.get('away'))}",
            "name": item.get("away") or "TBD",
            "country_code": "",
            "qualifier": "away",
        }
        match = {
            "id": f"ss:{normalize_key(item.get('url'))}",
            "round": "quarterfinal",
            "round_display": "Матч",
            "gender": gender,
            "category": category,
            "start_time": item.get("time") or "",
            "status": "live" if status == "live" else "not_started",
            "match_status": "",
            "best_of": 3,
            "players": [home, away],
            "_tourney": tourney,
            "_level": "masters",
        }
        try:
            match["scores"] = {
                "home": int(item.get("home_score") or 0),
                "away": int(item.get("away_score") or 0),
                "periods": [],
            }
        except (TypeError, ValueError):
            pass
        matches.append(match)
    cache_write("sportscore.json", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": matches,
    })
    return matches


# === WIKIPEDIA: РЕЙТИНГ ===

class TableParser(HTMLParser):
    """Достаёт все таблицы из HTML-страницы (в том числе вложенные)."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._stack = []
        self._row = None
        self._cell = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            # Сохраняем контекст внешней таблицы и начинаем новую
            self._stack.append({"rows": [], "saved": (self._row, self._cell)})
            self._row = None
            self._cell = None
        elif self._stack and tag == "tr":
            self._row = []
        elif self._stack and tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell).replace("\xa0", " ")).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._stack and any(self._row):
                self._stack[-1]["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            table = self._stack.pop()["rows"]
            self._row, self._cell = self._stack[-1]["saved"] if self._stack else (None, None)
            if table:
                self.tables.append(table)

    def handle_data(self, data):
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)


def fetch_tennisexplorer_rankings():
    """Рейтинг ATP/WTA (топ-100) с TennisExplorer — бесплатно, без ключа.

    У них сразу есть код страны (двухбуквенный) — из него получается
    настоящий флаг, а не набор букв.
    """
    cached = cache_read("te_rankings.json")
    if cached and cached.get("data") is not None:
        try:
            age_h = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(cached["ts"])).total_seconds() / 3600
        except ValueError:
            age_h = 999
        if age_h < 12:
            result = cached["data"]
            print(f"  TennisExplorer: рейтинг из кэша — "
                  f"ATP {len(result.get('men', []))}, WTA {len(result.get('women', []))}")
            return result

    result = {"men": [], "women": []}
    for gender, url in TENNISEXPLORER_RANKINGS.items():
        html = _fetch_html(url)
        if not html:
            print(f"  TennisExplorer: рейтинг {gender} — не удалось загрузить")
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            if len(cells) < 5:
                continue
            digits = re.sub(r"\D", "", re.sub(r"<[^>]+>", " ", cells[0]))
            if not digits:
                continue
            rank = int(digits)
            if not rank:
                continue

            raw_name = re.sub(r"<[^>]+>", "", cells[2]).replace("&nbsp;", " ").strip()
            name = _ranking_name(raw_name)
            if not name or not re.search(r"[A-Za-zА-Яа-я]", name):
                continue

            # код страны из класса флага («fl fl-kz»); у некоторых
            # стран класс длиннее («fl fl-all»), тогда берём название
            code_match = re.search(r"fl fl-([a-z]{2})\b", cells[3])
            country = code_match.group(1).upper() if code_match else ""
            country_name = re.sub(r"<[^>]+>", " ", cells[3]).replace("&nbsp;", " ").strip()
            country_name = re.sub(r"\s+", " ", country_name).strip()

            points = re.sub(r"\D", "", re.sub(r"<[^>]+>", " ", cells[4]))
            movement = re.sub(r"\D", "", re.sub(r"<[^>]+>", " ", cells[1]))

            result[gender].append({
                "rank": rank,
                "movement": int(movement) if movement else 0,
                "points": int(points) if points else 0,
                "played": 0,
                "id": f"wiki:{normalize_key(name)}",
                "name": name,
                "country_code": country,
                "country_name": country_name,
            })
        result[gender].sort(key=lambda r: r["rank"])
        print(f"  TennisExplorer: {gender} — {len(result[gender])} строк")

    if result["men"] or result["women"]:
        cache_write("te_rankings.json", {
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": result,
        })
    return result


def _ranking_name(raw):
    """«Sinner Jannik» → «Jannik Sinner», «Auger Aliassime Felix» → «Felix Auger Aliassime».

    На сайте имена в формате «Имя Фамилия». У TennisExplorer фамилия стоит
    первой и может состоять из нескольких слов («De Minaur», «Van De
    Zandschulp»), поэтому имя игрока — последнее слово, остальное — фамилия.
    """
    parts = [p for p in raw.replace(" ", " ").split() if p]
    if len(parts) < 2:
        return raw.strip()
    return " ".join([parts[-1]] + parts[:-1])


def _fetch_html(url):
    """Страница как текст (с нормальным User-Agent)."""
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=40) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        print(f"  TennisExplorer: запрос не удался — {exc}")
        return ""


def fetch_wikipedia_rankings():
    """Текущий мировой рейтинг ATP и WTA из Википедии (с кэшем на 12 часов)."""
    cached = cache_read("wiki_rankings.json")
    if cached and cached.get("data") is not None:
        try:
            age_h = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(cached["ts"])).total_seconds() / 3600
        except ValueError:
            age_h = 999
        if age_h < 12:
            result = cached["data"]
            print(f"  Wikipedia: рейтинг из кэша — "
                  f"ATP {len(result.get('men', []))}, WTA {len(result.get('women', []))}")
            return result

    result = {"men": [], "women": []}
    for gender, (page, section) in WIKI_RANKINGS.items():
        url = (f"https://en.wikipedia.org/w/api.php?action=parse&page={page}&section={section}"
               f"&prop=text&format=json&formatversion=2")
        data, error = http_get_json(url, timeout=45)
        if not data:
            print(f"  Wikipedia: рейтинг {gender} — ошибка: {error}")
            continue
        html = (data.get("parse") or {}).get("text") or ""
        parser = TableParser()
        parser.feed(html)

        rows = None
        for table in parser.tables:
            header = " ".join(table[0]) if table else ""
            low = header.lower()
            if "rankings" in low and "singles" in low and "race" not in low:
                rows = table
                break
        if not rows:
            print(f"  Wikipedia: рейтинг {gender} — таблица не найдена")
            continue

        for row in rows[1:]:
            cells = [c for c in row if c.strip()]
            if len(cells) < 3:
                continue
            digits = re.sub(r"\D", "", cells[0])
            if not digits:
                continue
            rank = int(digits)
            if not rank:
                continue

            raw_name = cells[1]
            country = ""
            m = re.search(r"\(([A-Z]{2,3})\)", raw_name)
            if m:
                country = m.group(1)
            name = re.sub(r"\s*\([A-Z]{2,3}\)\s*", "", raw_name).strip()
            if not name:
                name = raw_name

            points = 0
            movement = 0
            numbers = []
            for cell in cells[2:]:
                cleaned = cell.replace(",", "").replace("\xa0", "").replace("−", "-").strip()
                if re.fullmatch(r"-?\d+", cleaned):
                    numbers.append(int(cleaned))
            if numbers:
                points = numbers[0]
            if len(numbers) > 1:
                movement = numbers[1]

            result[gender].append({
                "rank": rank,
                "movement": movement,
                "points": points,
                "played": 0,
                "id": f"wiki:{normalize_key(name)}",
                "name": name,
                "country_code": country,
            })
        result[gender].sort(key=lambda r: r["rank"])
        print(f"  Wikipedia: рейтинг {gender} — {len(result[gender])} строк")
    cache_write("wiki_rankings.json", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": result,
    })
    return result


# === СБОРКА ===

def level_label(level, genders):
    if level == "grand_slam":
        return "Большой шлем"
    if "women" in genders and "men" in genders:
        return "Masters 1000 / WTA 1000"
    if "women" in genders:
        return "WTA 1000"
    return "Masters 1000"


def ensure_tournament(tournaments, name, level):
    """Создаёт или возвращает запись турнира."""
    entry = tournaments.get(name)
    if entry is None:
        meta = next((v for v in TML_TOURNAMENTS.values() if v[0] == name),
                    (name, name[:3].upper(), "🎾", level))
        entry = {
            "id": f"free:{slugify(name)}",
            "name": name,
            "short": meta[1],
            "icon": meta[2],
            "level": level,
            "genders": set(),
            "years": {},
        }
        tournaments[name] = entry
    return entry


def put_match(tournaments, match, year, tourney, level):
    """Кладёт матч в нужный подраздел (основные/второстепенные)."""
    entry = ensure_tournament(tournaments, tourney, level)
    gender = match["gender"]
    entry["genders"].add(gender)
    bucket = entry["years"].setdefault(str(year), {}).setdefault(
        gender, {"main": [], "secondary": []})
    bucket["main" if match["round"] in MAIN_ROUNDS else "secondary"].append(match)


def build_tournament_files(years_to_load):
    """Собирает файлы турниров из TennisMyLife + SportScore + Live Tennis API."""
    tournaments = {}

    def ensure(name, level):
        return ensure_tournament(tournaments, name, level)

    def put(entry, match, year, tourney=None, level=None):
        put_match(tournaments, match, year,
                  tourney or entry.get("name"), level or entry.get("level", "masters"))

    for year in years_to_load:
        for tour in ("atp", "wta"):
            text = fetch_tml_year(year, tour)
            matches = parse_tml(text, tour) if text else []
            if not matches:
                continue
            print(f"  TennisMyLife {year} {tour.upper()}: {len(matches)} матчей")
            for match in matches:
                tourney = match.pop("_tourney")
                level = match.pop("_level")
                put(ensure(tourney, level), match, year)

    # Текущие турниры: могут содержать матчи, которых ещё нет в годовом файле
    current_year = datetime.now(timezone.utc).year
    for tour in ("atp", "wta"):
        ongoing_text = fetch_tml_year(current_year, tour, ongoing=True)
        if not ongoing_text:
            continue
        known = set()
        for entry in tournaments.values():
            for gender_data in entry["years"].get(str(current_year), {}).values():
                for key in ("main", "secondary"):
                    known.update(m["id"] for m in gender_data.get(key, []))
        added = 0
        for match in parse_tml(ongoing_text, tour):
            if match["id"] in known:
                continue
            known.add(match["id"])
            tourney = match.pop("_tourney")
            level = match.pop("_level")
            put(ensure(tourney, level), match, current_year)
            added += 1
        if added:
            print(f"  TennisMyLife (текущие турниры) {tour.upper()}: +{added} матчей")

    live = fetch_sportscore()
    if live:
        print(f"  SportScore: {len(live)} live/предстоящих матчей")
        current_year = datetime.now(timezone.utc).year
        for match in live:
            tourney = match.pop("_tourney")
            level = match.pop("_level")
            put(ensure(tourney, level), match, current_year)

    # Live Tennis API: жеребьёвка будущих турниров и live-счёт
    load_lta_matches(tournaments)

    return tournaments


def collect_players(tournaments, rankings):
    """{id: [имя, число матчей]}"""
    players = {}
    for entry in tournaments.values():
        for year_data in entry["years"].values():
            for gender_data in year_data.values():
                for key in ("main", "secondary"):
                    for match in gender_data.get(key, []):
                        for player in match.get("players", []):
                            pid = player.get("id")
                            if not pid:
                                continue
                            item = players.setdefault(pid, [player.get("name", ""), 0])
                            item[1] += 1
    for row in rankings.get("men", []) + rankings.get("women", []):
        players.setdefault(row["id"], [row["name"], 0])
    return players


# Слова, которые не различают турниры между собой
TOURNAMENT_STOP_WORDS = {
    "open", "masters", "master", "atp", "wta", "men", "women", "m1000", "1000",
    "presented", "by", "finals", "championships", "championship", "tour", "2026", "2025",
}

# Точные соответствия названий из календаря Википедии нашим турнирам.
# Без них «French Open» и «Internazionali BNL d'Italia» ни с чем не совпадают.
CALENDAR_TOURNAMENT_ALIASES = {
    "australian open": "australian open",
    "french open": "roland garros",
    "roland garros": "roland garros",
    "wimbledon": "wimbledon",
    "us open": "us open",
    "us open tennis": "us open",
    "indian wells open": "indian wells masters",
    "indian wells masters": "indian wells masters",
    "miami open": "miami masters",
    "monte carlo masters": "monte carlo",
    "madrid open": "madrid masters",
    "italian open": "rome masters",
    "internazionali bnl d italia": "rome masters",
    "internazionali di roma": "rome masters",
    "canadian open": "canada masters",
    "national bank open": "canada masters",
    "cincinnati open": "cincinnati masters",
    "shanghai masters": "shanghai",
    "paris masters": "paris masters",
    "wta finals": "wta finals",
    "atp finals": "atp finals",
}


def core_tokens(name):
    """Значимые слова названия турнира."""
    return [t for t in normalize_key(name).split() if t not in TOURNAMENT_STOP_WORDS]


def match_tournament_key(name):
    """Ищет наш турнир по названию из любого источника.

    Сравнение идёт по значимым словам, поэтому «Shanghai Masters»,
    «Cincinnati Open» и «ATP Rome» находят свои турниры.
    """
    key = normalize_key(name)
    if not key:
        return None
    if key in TML_TOURNAMENTS:
        return key

    source = set(core_tokens(key))
    if not source:
        return None

    best = None
    best_size = 0
    for candidate in TML_TOURNAMENTS:
        tokens = set(core_tokens(candidate))
        if not tokens:
            continue
        if source == tokens or source < tokens or tokens < source:
            if len(tokens) > best_size or (len(tokens) == best_size and len(candidate) < len(best or "")):
                best = candidate
                best_size = len(tokens)
    return best


def wiki_player_name(text):
    """«Carlos Alcaraz» из ссылки Википедии → «Alcaraz, Carlos» (наш формат)."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if "," in raw:
        return raw
    parts = raw.split()
    if len(parts) < 2:
        return raw
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def wiki_name_key(text):
    """Ключ для сопоставления имён: «Alcaraz, Carlos» → «carlos alcaraz».

    Уточнения в вики-ссылках («Tommy Paul (tennis)») отбрасываем.
    """
    raw = str(text or "").strip()
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw)
    if "," in raw:
        last, first = raw.split(",", 1)
        raw = f"{first.strip()} {last.strip()}"
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def tournament_level_for(key, tour):
    """Уровень турнира: Большой шлем или Masters 1000 / WTA 1000."""
    if key in ("australian open", "roland garros", "wimbledon", "us open"):
        return "grand_slam"
    return "wta_1000" if str(tour or "").lower().startswith("wta") else "atp_1000"


def cached_rows(name, ttl_minutes, loader):
    """Ряды из кэша либо из API (с кэшем на ttl_minutes).

    loader возвращает (rows, meta) либо None.
    """
    cached = cache_read(name)
    if cached and cached.get("data") is not None:
        try:
            age_min = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(cached["ts"])).total_seconds() / 60
        except ValueError:
            age_min = 999
        if age_min < ttl_minutes:
            return cached["data"], cached.get("meta") or {}
    result = loader()
    if result is None:
        return [], {}
    if not isinstance(result, tuple):
        result = (result, {})
    rows, meta = result
    cache_write(name, {"ts": datetime.now(timezone.utc).isoformat(),
                       "data": rows, "meta": meta})
    return rows or {}, meta or {}


def load_lta_matches(tournaments):
    """Матчи из Live Tennis API: live + предстоящие (с жеребьёвкой и временем старта).

    Квота бесплатного тарифа — 100 запросов в сутки, поэтому расписание
    забираем раз в 90 минут, live-состояние — каждый запуск, а каталог
    турниров — раз в сутки.
    """
    import lta_provider

    if not lta_provider.get_key():
        print("  Live Tennis API: ключ LIVETENNIS_API_KEY не задан — пропускаем")
        return 0

    added = 0

    # Каталог турниров — раз в сутки
    catalogue = cached_rows("lta_tournaments_v3.json", 24 * 60,
                            lambda: (lta_provider.fetch_tournaments() or {}, {}))[0]

    def add_rows(rows, kind, meta=None):
        nonlocal added
        dropped = {"round": 0, "tournament": 0, "ok": 0}
        names = set()
        for row in rows:
            match = lta_provider.normalize_match(row, catalogue)
            if not match:
                dropped["round"] += 1
                continue
            key = match_tournament_key(match.get("tournament", ""))
            if not key:
                dropped["tournament"] += 1
                names.add(str(match.get("tournament", ""))[:40])
                continue
            meta_info = TML_TOURNAMENTS[key]
            level = tournament_level_for(key, match.get("category", ""))
            put_match(tournaments, match, match_year(match), meta_info[0], level)
            added += 1
            dropped["ok"] += 1
        if rows:
            print(f"    {kind}: получено {len(rows)}, добавлено {dropped['ok']}, "
                  f"без раунда {dropped['round']}, турнир не распознан {dropped['tournament']}")
        if names:
            print(f"    нераспознанные турниры: {', '.join(sorted(names)[:8])}")

    # Откат: если наш уровень в ленте отсутствует (например, бесплатный тариф
    # отдаёт только ITF/Challenger), не тратим квоту — проверяем раз в 6 часов.
    def backoff_minutes(name, base):
        state = cache_read(name) or {}
        return 6 * 60 if state.get("empty") else base

    # Live-состояние
    def load_live():
        data, error = lta_provider.api_get("/matches", {
            "status": "live", "limit": 100,
            "tier": lta_provider.LTA_TIERS, "draw": "singles"})
        if not data:
            print(f"  Live Tennis API: live-матчи недоступны — {error}")
            return None, None
        return data.get("data") or [], data.get("meta") or {}

    live_rows, live_meta = cached_rows(
        "lta_live_v3.json", backoff_minutes("lta_live_v3.json", 60), load_live)
    add_rows(live_rows, "live", live_meta)

    # Предстоящие матчи (жеребьёвка)
    def load_upcoming():
        data, error = lta_provider.api_get("/matches", {
            "status": "upcoming", "limit": 100,
            "tier": lta_provider.LTA_TIERS, "draw": "singles"})
        if not data:
            print(f"  Live Tennis API: предстоящие матчи недоступны — {error}")
            return None, None
        return data.get("data") or [], data.get("meta") or {}

    upcoming_rows, upcoming_meta = cached_rows(
        "lta_upcoming_v3.json", backoff_minutes("lta_upcoming_v3.json", 30), load_upcoming)
    add_rows(upcoming_rows, "upcoming", upcoming_meta)

    # Помечаем пустые ответы, чтобы включить откат
    for name, rows in (("lta_live_v3.json", live_rows), ("lta_upcoming_v3.json", upcoming_rows)):
        if not rows:
            state = cache_read(name) or {}
            state["empty"] = True
            cache_write(name, state)

    print(f"  Live Tennis API: матчей обработано {added}")
    return len(tournaments)


def match_year(match):
    """Год матча по времени старта."""
    stamp = (match.get("start_time") or "")[:4]
    return int(stamp) if stamp.isdigit() else datetime.now(timezone.utc).year


def fetch_lta_rankings():
    """Рейтинг из Live Tennis API (кэш на 12 часов — бережём квоту 100/сутки)."""
    import lta_provider

    if not lta_provider.get_key():
        return None

    cached = cache_read("lta_rankings.json")
    if cached and cached.get("data"):
        try:
            age_h = (datetime.now(timezone.utc) -
                     datetime.fromisoformat(cached["ts"])).total_seconds() / 3600
        except ValueError:
            age_h = 999
        if age_h < 12:
            print("  Live Tennis API: рейтинг из кэша")
            return cached["data"]

    data = lta_provider.fetch_rankings()
    if not data or not data.get("men"):
        return None
    cache_write("lta_rankings.json", {
        "ts": datetime.now(timezone.utc).isoformat(), "data": data})
    print(f"  Live Tennis API: рейтинг ATP {len(data['men'])}, WTA {len(data['women'])}")
    return data


def load_calendar():
    """Календарь турниров из Википедии: текущий и следующий сезон."""
    import wiki_provider as wp

    now = datetime.now(timezone.utc)
    items = []
    for year in (now.year, now.year + 1):
        try:
            items.extend(wp.fetch_calendar(year))
        except Exception as e:  # noqa: BLE001
            print(f"  Wikipedia: календарь {year} — ошибка: {e}")
    # оставляем только «наши» уровни
    items = [i for i in items if i["level"] in ("grand_slam", "atp_1000", "wta_1000",
                                                "atp_finals", "wta_finals")]
    # убираем дубли: у одного турнира в календаре есть и квалификация,
    # и основная сетка — оставляем последнюю (она идёт позже)
    unique = {}
    for item in items:
        unique[item["name"].lower()] = item
    items = sorted(unique.values(), key=lambda i: i["start"])

    # привязываем к нашим вкладкам, чтобы титульная страница знала,
    # какой турнир и когда в ближайшем будущем
    for item in items:
        name_key = normalize_key(item["name"])
        key = CALENDAR_TOURNAMENT_ALIASES.get(name_key)
        if not key:
            # запасной вариант — по похожему названию (без места:
            # «Paris, France» из-за этого подставлялся «Paris Masters»)
            key = match_tournament_key(item["name"])
        if key and key in TML_TOURNAMENTS:
            item["slug"] = slugify(TML_TOURNAMENTS[key][0])
    return items


def load_wiki_draws(tournaments, calendar):
    """Добавляет в календарь матчи из жеребьёвок Википедии.

    Википедия даёт участников ещё не сыгранных матчей — их нет в
    TennisMyLife, где лежат только завершённые. Идентификаторы игроков
    приводим к тем же, что и в TennisMyLife, чтобы сетка собиралась
    из одного дерева.
    """
    import wiki_provider as wp

    # карта «имя → id» по уже загруженным матчам
    name_to_id = {}
    for entry in tournaments.values():
        for year_data in entry["years"].values():
            for gender_data in year_data.values():
                for key in ("main", "secondary"):
                    for match in gender_data.get(key, []):
                        for player in match.get("players", []):
                            k = wiki_name_key(player.get("name", ""))
                            if k:
                                name_to_id.setdefault(k, player["id"])

    added = 0
    for item in calendar:
        key = match_tournament_key(item["name"]) or match_tournament_key(item.get("place", ""))
        if not key or key not in TML_TOURNAMENTS:
            continue
        if not item.get("draw_page"):
            continue
        meta = TML_TOURNAMENTS[key]
        year = int(item["start"][:4])

        # Если данные турнира уже есть (TennisMyLife отдаёт сыгранные матчи),
        # не трогаем их — иначе появятся дубли. Википедию используем только
        # для предстоящих турниров, которых ещё нет в базе.
        entry_existing = tournaments.get(meta[0])
        if entry_existing and entry_existing["years"].get(str(year)):
            continue

        for gender in ("men", "women"):
            try:
                wiki_matches = wp.fetch_draw(item["wiki_page"], gender, 128)
            except Exception as e:  # noqa: BLE001
                print(f"  Wikipedia: сетка {item['name']} — ошибка: {e}")
                continue
            # уже известные пары этого турнира — чтобы не задваивать
            known = set()
            entry = tournaments.get(meta[0])
            if entry:
                for gender_data in entry["years"].get(str(year), {}).values():
                    for key in ("main", "secondary"):
                        for m in gender_data.get(key, []):
                            if m.get("gender") != gender:
                                continue
                            names = sorted(wiki_name_key(p.get("name", "")) for p in m.get("players", []))
                            known.add((m.get("round"), tuple(names)))
            for wiki_match in wiki_matches:
                players = []
                winner_index = -1
                for raw in wiki_match["players"]:
                    name = wiki_player_name(raw.get("name", ""))
                    if not name:
                        continue
                    pid = name_to_id.get(wiki_name_key(name), f"wiki:{wiki_name_key(name)}")
                    if raw.get("winner"):
                        winner_index = len(players)
                    players.append({
                        "id": pid,
                        "name": name,
                        "country_code": "",
                        "qualifier": "home" if not players else "away",
                    })
                if len(players) < 2:
                    continue
                names = tuple(sorted(wiki_name_key(p["name"]) for p in players))
                if (wiki_match["round"], names) in known:
                    continue          # такой матч уже есть (с результатом)
                match = {
                    "id": wiki_match["id"],
                    "round": wiki_match["round"],
                    "round_display": round_display_name(wiki_match["round"]),
                    "gender": gender,
                    "category": "WTA" if gender == "women" else "ATP",
                    "start_time": "",
                    "status": "not_started",
                    "match_status": "",
                    "best_of": 3,
                    "players": players,
                    "source": "wikipedia",
                }
                if 0 <= winner_index < len(players):
                    match["winner_id"] = players[winner_index]["id"]
                    match["status"] = "closed"
                put_match(tournaments, match, year, meta[0], meta[3])
                added += 1
    if added:
        print(f"  Wikipedia: добавлено {added} матчей из жеребьёвок")
    return added


def run():
    """Собирает все данные и записывает их в data/.

    Общего троттлинга нет намеренно: у каждого источника свой кэш
    (TennisMyLife — 12 ч, живая сводка — 60 мин, жеребьёвка — 30 мин,
    рейтинг — 12 ч, фото — 60 дней), поэтому запуск тратит 1–2 запроса.
    """
    now = datetime.now(timezone.utc)
    current_year = now.year
    years = [current_year - i for i in range(HISTORY_YEARS)]

    print("TennisMyLife: результаты по годам…")
    tournaments = build_tournament_files(years)

    print("Wikipedia: календарь турниров…")
    calendar = load_calendar()
    write_json(os.path.join(DATA_DIR, "calendar.json"), {
        "last_updated": now.isoformat(),
        "tournaments": calendar,
    })
    print(f"  турниров в календаре: {len(calendar)}")

    print("Wikipedia: жеребьёвки предстоящих турниров…")
    load_wiki_draws(tournaments, calendar)

    print("Мировой рейтинг…")
    rankings = fetch_lta_rankings() or {"men": [], "women": []}
    if not rankings.get("men") and not rankings.get("women"):
        print("  TennisExplorer: мировой рейтинг…")
        rankings = fetch_tennisexplorer_rankings()
    if not rankings.get("men") and not rankings.get("women"):
        print("  Wikipedia: мировой рейтинг…")
        rankings = fetch_wikipedia_rankings()

    print("Wikipedia: фотографии игроков…")
    players = collect_players(tournaments, rankings)
    photo_cache = load_player_photos(players)
    photos = {pid: item.get("u", "") for pid, item in photo_cache.items() if item.get("u")}

    # Дублируем фото на альтернативные ключи одного игрока
    # (tml:atp:... и wiki:... могут принадлежать одному человеку —
    # иначе в карточках матчей фото не показывается)
    name_to_pids = {}
    for pid, (name, _count) in players.items():
        name_to_pids.setdefault(wiki_name_key(name), []).append(pid)
    for nk, pids in name_to_pids.items():
        if len(pids) > 1:
            photo = next((photos.get(p) for p in pids if photos.get(p)), None)
            if photo:
                for p in pids:
                    if not photos.get(p):
                        photos[p] = photo

    index = []
    for entry in sorted(tournaments.values(), key=lambda t: t["name"]):
        for year_data in entry["years"].values():
            for gender_data in year_data.values():
                for key in ("main", "secondary"):
                    gender_data[key].sort(key=lambda m: (m.get("start_time") or ""))
        slug = slugify(entry["name"])
        counts = count_matches(entry["years"])
        genders = sorted(entry["genders"])
        label = level_label(entry["level"], genders)
        description = TOURNAMENT_DESCRIPTIONS.get(slug, "")
        write_json(os.path.join(TOURNAMENTS_DIR, f"{slug}.json"), {
            "id": entry["id"],
            "slug": slug,
            "name": entry["name"],
            "short": entry["short"],
            "icon": entry["icon"],
            "level": entry["level"],
            "level_label": label,
            "description": description,
            "genders": genders,
            "years": entry["years"],
        })
        index.append({
            "slug": slug,
            "name": entry["name"],
            "short": entry["short"],
            "icon": entry["icon"],
            "level": entry["level"],
            "level_label": label,
            "description": description,
            "genders": genders,
            "years": sorted(entry["years"].keys(), reverse=True),
            "counts": counts,
        })
        print(f"  {entry['name']} ({label}): {counts['years']} г., "
              f"основных {counts['main']}, второстепенных {counts['secondary']}")

    write_json(os.path.join(DATA_DIR, "index.json"), {
        "last_updated": now.isoformat(),
        "source": "free",
        "tournaments": index,
    })
    write_json(os.path.join(DATA_DIR, "rankings.json"), {
        "last_updated": now.isoformat(),
        "week": "",
        "men": rankings.get("men", []),
        "women": rankings.get("women", []),
    })
    write_json(os.path.join(DATA_DIR, "players.json"), photos)

    # Фото турниров и подробные профили игроков (Википедия).
    # Модуль опционален: если его нет — сайт просто покажет заглушки.
    print("\nWikipedia: фото турниров и профили игроков…")
    try:
        import wiki_profiles
        wiki_profiles.main()
    except Exception as e:  # noqa: BLE001
        print(f"  пропускаем: {e}")

    print("\nГотово (бесплатный провайдер).")


if __name__ == "__main__":
    run()
