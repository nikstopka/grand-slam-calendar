#!/usr/bin/env python3
"""Титульные фотографии турниров и подробные профили игроков из Википедии.

Что делает модуль:
  • tournament_photos(pages) — для каждого турнира находит титульную фотографию
    (корт, стадион, арена) в статье Википедии и отдаёт прямой URL файла
    с upload.wikimedia.org (ширина 1600 px);
  • player_profiles(players) — разбирает инфобокс «Infobox tennis biography»
    и лид статьи: фото, страна, возраст, рост, вес, награды, интересные факты.

Особенности работы с API Википедии (проверено на практике):
  • между любыми запросами выдерживается пауза не меньше 1.5 с, иначе IP
    получает HTTP 429; при 429 делаются повторы с backoff 5/10/20 с;
  • метаданные файлов (`imageinfo`) запрашиваются пачками по 50 файлов;
  • всё найденное кэшируется на диске на 60 дней
    (.cache/profiles_players.json, .cache/profiles_tournaments.json).

Использование:
    python scripts/wiki_profiles.py
"""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timezone

# Чтобы sibling-модули (common, wiki_provider) находились при любом способе запуска
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import wiki_provider  # noqa: E402
from common import DATA_DIR, cache_read, cache_write, http_get_json, write_json  # noqa: E402

WIKI_API = wiki_provider.WIKI_API

# === ПАРАМЕТРЫ РАБОТЫ С API ===

MIN_DELAY = 1.5           # секунд между любыми запросами к Википедии
BACKOFF = (5, 10, 20)     # повторы при HTTP 429
CACHE_TTL_DAYS = 60       # сколько живёт кэш фото и описаний
CACHE_PLAYERS = "profiles_players.json"
CACHE_TOURNAMENTS = "profiles_tournaments.json"

LEAD_LIMIT = 15000        # окно «лида» статьи — там ищем картинки в первую очередь
EXTENDED_LIMIT = 45000    # расширенное окно, если в лиде подходящих фото нет
# Размеры фото под конкретные места на сайте:
# карточка турнира в карусели — 250px (с ретиной хватит 700),
# аватар в рейтинге — 38px, фото в профиле — 170px.
PHOTO_WIDTH_PLAYER = 520
PHOTO_WIDTH_TOURNAMENT = 760
IMAGE_BATCH = 50          # максимум файлов в одном запросе imageinfo

# Wikimedia теперь отдаёт превью только «бакетных» размеров — если API вернул
# вариант меньше запрошенного, расширяем ссылку до ближайшего разрешённого.
ALLOWED_BUCKETS = (960, 1280, 1920, 3840)

# Слова, по которым узнаём фотографию площадки (корт, стадион, арена…)
VENUE_WORDS = (
    ("court", 100), ("stadium", 100), ("arena", 100), ("stadion", 100),
    ("centre", 90), ("center", 90), ("park", 80), ("gardens", 80),
    ("club", 70), ("field", 70), ("ground", 60), ("open", 40),
)

# Ранги кандидатов-фотографий турнира (меньше — лучше):
#   1 — картинка из инфобокса; 2 — «площадка» в лиде; 3 — «площадка» ниже лида;
#   4 — первый JPEG лида; 5 — первый JPEG ниже лида; 6 — фото со страницы арены;
#   7 — pageimages страницы турнира; 8 — логотип из инфобокса.
RANK_INFOBOX = 1
RANK_LEAD_VENUE = 2
RANK_EXT_VENUE = 3
RANK_LEAD_JPEG = 4
RANK_EXT_JPEG = 5
RANK_VENUE_PAGE = 6
RANK_PAGEIMAGES = 7
RANK_LOGO = 8

# Страница Википедии для каждого турнира. Основная страница + запасные
# варианты (часть названий — redirect-страницы или «мёртвые» заголовки)
# и страница арены, где почти всегда есть фотография корта.
TOURNAMENT_PAGES = {
    "australian-open": {
        "pages": ["Australian Open"],
        "venues": ["Melbourne Park"],
    },
    "roland-garros": {
        "pages": ["French Open", "Roland Garros"],
        "venues": ["Stade Roland Garros"],
    },
    "wimbledon": {
        "pages": ["Wimbledon", "Wimbledon Championships"],
        "venues": ["All England Lawn Tennis and Croquet Club"],
    },
    "us-open": {
        "pages": ["US Open (tennis)"],
        "venues": ["USTA Billie Jean King National Tennis Center"],
    },
    "indian-wells": {
        "pages": ["Indian Wells Open", "Indian Wells Masters"],
        "venues": ["Indian Wells Tennis Garden"],
    },
    "miami-open": {
        "pages": ["Miami Open", "Miami Open (tennis)"],
        "venues": ["Hard Rock Stadium"],
    },
    "monte-carlo": {
        "pages": ["Monte-Carlo Masters", "Monte Carlo Masters"],
        "venues": ["Monte Carlo Country Club"],
    },
    "madrid-open": {
        "pages": ["Madrid Open", "Madrid Open (tennis)"],
        "venues": ["Caja Mágica"],
    },
    "internazionali-di-roma": {
        "pages": ["Internazionali BNL d'Italia", "Internazionali di Roma"],
        "venues": ["Foro Italico"],
    },
    "toronto-montreal": {
        "pages": ["Canadian Open", "Canadian Open (tennis)", "National Bank Open"],
        "venues": ["Sobeys Stadium"],
    },
    "cincinnati": {
        "pages": ["Cincinnati Open", "Western & Southern Open"],
        "venues": ["Lindner Family Tennis Center"],
    },
    "shanghai": {
        "pages": ["Shanghai Masters", "Shanghai Masters (tennis)"],
        "venues": ["Qizhong Forest Sports City Arena"],
    },
    "paris-masters": {
        "pages": ["Paris Masters", "Rolex Paris Masters"],
        "venues": ["Paris La Défense Arena"],
    },
}

# Явные предпочтения: титульные фотографии площадок. В статьях некоторых
# турниров первым идёт снимок отдельного матча — он не подходит.
PREFERRED_PHOTOS = {
    "madrid-open": ["Caja Mágica exterior.jpg"],
    "toronto-montreal": [
        "Rexall Centre at York Toronto Canada.JPG",
        "Rexall Centre York University Toronto.JPG",
    ],
    "paris-masters": [
        "Defense arena.jpg",
        "Entrée 4 Paris Défense Arena - Nanterre (FR92) - 2022-07-24 - 1.jpg",
    ],
}

# Коды стран (ISO 3166-1 alpha-3) → названия. Инфобоксы теннисистов часто
# пишут страну как «{{POL}}» или «{{flagu|Italy}}».
COUNTRY_NAMES = {
    "ALG": "Algeria", "ARG": "Argentina", "ARM": "Armenia", "AUS": "Australia",
    "AUT": "Austria", "AZE": "Azerbaijan", "BEL": "Belgium", "BIH": "Bosnia and Herzegovina",
    "BLR": "Belarus", "BOL": "Bolivia", "BRA": "Brazil", "BUL": "Bulgaria",
    "CAN": "Canada", "CHI": "Chile", "CHN": "China", "COL": "Colombia",
    "CRO": "Croatia", "CYP": "Cyprus", "CZE": "Czech Republic", "DEN": "Denmark",
    "ECU": "Ecuador", "EGY": "Egypt", "ESP": "Spain", "EST": "Estonia",
    "FIN": "Finland", "FRA": "France", "GBR": "United Kingdom", "GEO": "Georgia",
    "GER": "Germany", "GRE": "Greece", "HKG": "Hong Kong", "HUN": "Hungary",
    "INA": "Indonesia", "IND": "India", "IRI": "Iran", "IRL": "Ireland",
    "ISL": "Iceland", "ISR": "Israel", "ITA": "Italy", "JPN": "Japan",
    "KAZ": "Kazakhstan", "KOR": "South Korea", "KOS": "Kosovo", "LAT": "Latvia",
    "LTU": "Lithuania", "LUX": "Luxembourg", "MAR": "Morocco", "MDA": "Moldova",
    "MEX": "Mexico", "MKD": "North Macedonia", "MLT": "Malta", "MON": "Monaco",
    "NED": "Netherlands", "NOR": "Norway", "NZL": "New Zealand", "PAK": "Pakistan",
    "PAR": "Paraguay", "PER": "Peru", "PHI": "Philippines", "POL": "Poland",
    "POR": "Portugal", "ROU": "Romania", "RSA": "South Africa", "RUS": "Russia",
    "SCG": "Serbia and Montenegro", "SRB": "Serbia", "SUI": "Switzerland",
    "SVK": "Slovakia", "SLO": "Slovenia", "SWE": "Sweden", "TPE": "Chinese Taipei",
    "THA": "Thailand", "TUN": "Tunisia", "TUR": "Turkey", "UKR": "Ukraine",
    "URU": "Uruguay", "USA": "United States", "UZB": "Uzbekistan",
    "VEN": "Venezuela", "ZIM": "Zimbabwe",
}

# Сокращения, после которых точка не заканчивает предложение
ABBREVIATIONS = {
    "no", "nos", "u.s", "u.k", "mr", "mrs", "ms", "dr", "jr", "sr", "st",
    "vs", "etc", "inc", "ltd", "co", "approx", "est", "gen", "capt", "sgt",
}

# Фразы, по которым в лиде ищем предложение про титулы
TITLES_PATTERNS = (
    r"has won[^.]*?\btitles?\b",
    r"has won[^.]*?\bGrand Slam\b",
    r"\bGrand Slam\b[^.]*?\btitles?\b",
    r"has won[^.]*?\bmajors?\b",
    r"is the (?:first|only|youngest|oldest)[^.]*?\bmajor\b",
)


# === HTTP: ПАУЗЫ, ПОВТОРЫ, 429 ===

_last_request = 0.0


def _pause():
    """Пауза между запросами к Википедии (не меньше MIN_DELAY секунд)."""
    global _last_request
    wait = MIN_DELAY - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def _probe_error(params):
    """Код ошибки запроса (api_get прячет исключения) — нужен для отлова 429."""
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    _pause()
    _data, error = http_get_json(url, headers={"Accept": "application/json"}, timeout=45)
    return error or ""


def _request(fetch, params, label=""):
    """Запрос к Википедии: пауза 1.5 с, повторы и backoff при 429."""
    for attempt in range(len(BACKOFF) + 1):
        _pause()
        data = fetch(params)
        if data:
            return data
        error = _probe_error(params)
        print(f"  Wikipedia: {label or 'запрос'} не удался ({error or 'без ответа'})")
        if attempt >= len(BACKOFF):
            break
        if "429" in error:
            wait = BACKOFF[attempt]
            print(f"  Wikipedia: 429 — повтор через {wait} с")
            time.sleep(wait)
        else:
            time.sleep(2)
    return None


def _api_get(params, label=""):
    """Запрос к API Википедии через wiki_provider.api_get."""
    return _request(lambda p: wiki_provider.api_get(p), params, label)


def _wikitext(title):
    """Викитекст страницы через wiki_provider.wikitext."""
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "redirects": "1", "titles": title,
    }
    return _request(lambda p: wiki_provider.wikitext(p["titles"]), params,
                    f"страница «{title}»")


def _page_images(title):
    """Оригинал картинки-«лида» страницы (pageimages) или ''."""
    if not title:
        return ""
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "pageimages", "piprop": "original", "redirects": "1",
        "titles": title,
    }
    data = _api_get(params, f"pageimages «{title}»")
    for page in _pages(data):
        original = page.get("original") or {}
        return _clean_url(original.get("source") or "")
    return ""


def _pages(data):
    """Список страниц из ответа API (formatversion=2)."""
    if not isinstance(data, dict):
        return []
    pages = ((data.get("query") or {}).get("pages") or [])
    if isinstance(pages, dict):
        pages = list(pages.values())
    return [p for p in pages if isinstance(p, dict)]


def _clean_url(url):
    """Убираем трекинговые параметры (utm_*) из ссылки на файл."""
    if not url:
        return ""
    return url.split("?")[0].strip()


def _is_photo_url(url):
    """Похоже ли на картинку (а не svg-логотип и не пустая строка)."""
    if not url:
        return False
    low = url.lower()
    basename = low.rsplit("/", 1)[-1]
    if ".svg" in basename:  # svg-логотип (даже если отрендерен в .png)
        return False
    return low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))


def _image_urls(titles, width):
    """{имя файла: URL} для пачки файлов — запросы imageinfo пачками по 50."""
    result = {}
    names = [t for t in dict.fromkeys(titles) if t]
    for start in range(0, len(names), IMAGE_BATCH):
        chunk = names[start:start + IMAGE_BATCH]
        params = {
            "action": "query", "format": "json", "formatversion": "2",
            "prop": "imageinfo", "iiprop": "url|size", "iiurlwidth": str(width),
            "titles": "|".join("File:" + t for t in chunk),
        }
        data = _api_get(params, "imageinfo")
        for page in _pages(data):
            info = (page.get("imageinfo") or [{}])[0]
            url = _clean_url(info.get("thumburl") or info.get("url") or "")
            if not url:
                continue
            url = _ensure_width(url, width, info.get("width") or 0)
            title = page.get("title") or ""
            name = title[5:] if title.lower().startswith("file:") else title
            result[_norm(name)] = url
    return result


def _ensure_width(url, width, original_width=0):
    """Расширяет превью до ближайшего разрешённого размера, если API дал мелкий."""
    match = re.search(r"/(\d+)px-", url)
    if not match or int(match.group(1)) >= width:
        return url
    for bucket in ALLOWED_BUCKETS:
        if bucket < width:
            continue
        if original_width and original_width < bucket:
            break  # оригинал меньше — увеличивать нечего
        return url[:match.start()] + f"/{bucket}px-" + url[match.end():]
    return url


def _norm(name):
    """Ключ для сравнения имён файлов: пробелы вместо подчёркиваний, регистр."""
    return re.sub(r"\s+", " ", str(name or "").replace("_", " ")).strip().lower()


# === РАЗБОР ВИКИТЕКСТА ===

def _delta(text, open_mark, close_mark):
    """Сколько раз открывающих/закрывающих маркеров в строке."""
    return text.count(open_mark) - text.count(close_mark)


def _find_template(text, name="Infobox"):
    """Текст шаблона (вместе с вложенными) или ''."""
    if not text:
        return ""
    match = re.search(r"\{\{\s*" + re.escape(name), text, re.I)
    if not match:
        return ""
    depth = 0
    i = match.start()
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return text[match.start():i]
            continue
        i += 1
    return ""


def _split_template_fields(template):
    """Свойства шаблона → {ключ: значение}. Учитывает вложенные шаблоны и ссылки."""
    if not template:
        return {}
    body = template
    depth = 1
    links = 0
    i = body.find("{{") + 2
    while i < len(body):
        if body.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if body.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
            continue
        if body.startswith("[[", i):
            links += 1
            i += 2
            continue
        if body.startswith("]]", i):
            links -= 1
            i += 2
            continue
        if depth == 1 and links == 0 and body[i] == "|":
            body = body[i:]
            break
        i += 1

    fields = {}
    key = None
    buf = []
    depth = 0
    links = 0
    for line in body.split("\n"):
        stripped = line.strip()
        if depth == 0 and links == 0 and stripped.startswith("|"):
            if key is not None:
                fields[key] = "\n".join(buf).strip()
            head, sep, rest = stripped[1:].partition("=")
            if not sep:
                key = None
                buf = []
            else:
                key = head.strip().lower()
                buf = [rest]
        elif key is not None:
            buf.append(line)
        depth = max(depth + _delta(line, "{{", "}}"), 0)
        links = max(links + _delta(line, "[[", "]]"), 0)
    if key is not None:
        fields[key] = "\n".join(buf).strip()
    return fields


def _infobox_fields(text, name="Infobox tennis biography"):
    """Свойства инфобокса «Infobox tennis biography» → {ключ: значение}."""
    return _split_template_fields(_find_template(text, name))


def _clean_text(text):
    """Чистый текст без разметки Википедии (шаблоны, ссылки, сноски)."""
    if not text:
        return ""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    # важно: сначала убираем одиночные <ref .../>, иначе следующая регулярка
    # «съест» кусок текста до первой парной </ref>
    text = re.sub(r"<ref[^>]*/>", " ", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    # шаблоны в скобках (например «({{Langx|ru|…}}; born …)») убираем целиком
    text = re.sub(r"\(\s*\{\{[^{}]*\}\}\s*\)\s*;?", " ", text)
    for _ in range(6):  # шаблоны (в т.ч. вложенные) вырезаем целиком
        new = re.sub(r"\{\{[^{}]*\}\}", " ", text)
        if new == text:
            break
        text = new
    text = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"\(\s*[;,]\s*", "(", text)   # «( ;» — остаток шаблона
    text = re.sub(r"\(\s*\)", "", text)             # пустые скобки
    text = _balance_parens(text)
    return re.sub(r"\s+", " ", text).strip()


def _balance_parens(text):
    """Убирает «лишние» закрывающие скобки, оставшиеся после шаблонов."""
    out = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                continue
            depth -= 1
        out.append(char)
    return "".join(out)


def _clean_cell(text):
    """Разбор ячейки/значения инфобокса (обёртка над clean_cell из wiki_provider)."""
    return wiki_provider.clean_cell(text or "")


# === ТУРНИРЫ: ВЫБОР ФОТОГРАФИИ ===

def _file_links(text, limit):
    """Ссылки на файлы в начале статьи: [(имя файла, подпись, позиция)]."""
    if not text:
        return []
    region = text[:limit]
    found = []
    seen = set()
    pos = 0
    while True:
        match = re.search(r"\[\[\s*[Ff]ile\s*:\s*([^\]|]+)", region[pos:])
        if not match:
            break
        name = match.group(1).strip()
        start = pos + match.start()
        # ищем конец ссылки, считая вложенные [[ ]]
        j = pos + match.end()
        depth = 1
        while j < len(region):
            if region.startswith("[[", j):
                depth += 1
                j += 2
                continue
            if region.startswith("]]", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
                continue
            j += 1
        raw = region[pos + match.end():max(j - 2, pos + match.end())]
        caption = raw.split("|")[-1] if "|" in raw else ""
        key = _norm(name)
        if key and key not in seen:
            seen.add(key)
            found.append((name, _clean_text(caption), start))
        pos = j
    return found


def _file_name(value):
    """Имя файла из значения поля инфобокса («File:X.jpg», «[[File:X.jpg]]»…)."""
    if not value:
        return ""
    value = value.strip()
    match = re.search(r"\[\[\s*[Ff]ile\s*:\s*([^\]|]+)", value)
    name = match.group(1).strip() if match else ""
    if not name:
        name = re.sub(r"^\s*[Ff]ile\s*:\s*", "", value).split("|")[0].strip()
    if not name or name.lower().endswith(".svg"):
        return ""
    if re.search(r"\.(jpe?g|png|webp|gif)$", name, re.I):
        return name
    return ""


def _photo_score(name, position=0):
    """Оценка файла: чем больше, тем лучше фото турнира."""
    low = str(name or "").lower()
    score = 0
    for word, weight in VENUE_WORDS:
        if word in low:
            score = max(score, weight)
    if re.search(r"\.(jpe?g)$", low):
        score += 60
    elif re.search(r"\.png$", low):
        score += 20
    elif low.endswith(".svg"):
        score -= 1000
    if position:
        score -= position / 10000.0
    return score


def _is_venue_photo(name):
    """Похоже ли имя файла на фотографию площадки."""
    return _photo_score(name) >= 90


def _tournament_candidates(title):
    """Кандидаты-фото со страницы турнира: [(ранг, имя, подпись)]."""
    text = _wikitext(title)
    if not text:
        return []
    candidates = []

    # 1. картинка из инфобокса (не логотип)
    box = _split_template_fields(_find_template(text, "Infobox"))
    image = _file_name(box.get("image", "") or box.get("picture", "") or box.get("photo", ""))
    if image:
        candidates.append((RANK_INFOBOX, image, ""))
    logo = _file_name(box.get("logo", ""))
    if logo:
        candidates.append((RANK_LOGO, logo, ""))

    # 2. «площадка» в лиде
    for name, caption, position in _file_links(text, LEAD_LIMIT):
        if _is_venue_photo(name):
            candidates.append((RANK_LEAD_VENUE, name, caption))

    # 3. «площадка» ниже лида
    for name, caption, position in _file_links(text, EXTENDED_LIMIT):
        if _is_venue_photo(name):
            candidates.append((RANK_EXT_VENUE, name, caption))

    # 4. первый JPEG в лиде
    for name, caption, _position in _file_links(text, LEAD_LIMIT):
        if _photo_score(name) > 0:
            candidates.append((RANK_LEAD_JPEG, name, caption))
            break

    # 5. первый JPEG ниже лида
    for name, caption, _position in _file_links(text, EXTENDED_LIMIT):
        if _photo_score(name) > 0:
            candidates.append((RANK_EXT_JPEG, name, caption))
            break

    return _rank_candidates(candidates)


def _rank_candidates(candidates):
    """Убираем дубли и сортируем по рангу, затем по оценке файла."""
    unique = {}
    for rank, name, caption in candidates:
        key = _norm(name)
        if key not in unique:
            unique[key] = (rank, name, caption)
    ranked = sorted(unique.values(), key=lambda item: (item[0], -_photo_score(item[1])))
    return [(rank, name, caption) for rank, name, caption in ranked]


def tournament_photos(pages):
    """pages: список кортежей (slug, wiki_page_title).

    Возвращает {slug: {"photo": url, "caption": str}}.
    """
    cache = _load_cache(CACHE_TOURNAMENTS)
    result = {}
    pending = []

    for slug, title in pages:
        entry = cache.get(slug)
        if entry and entry.get("photo"):
            result[slug] = {"photo": entry["photo"], "caption": entry.get("caption", "")}
        else:
            pending.append((slug, title))

    if not pending:
        return result

    print(f"  Wikipedia: ищем фото для {len(pending)} турниров")

    # 1) кандидаты со страниц турниров
    candidates = {}
    for slug, title in pending:
        items = []
        try:
            items = _tournament_candidates(title)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {slug}: {exc}")
        if not items:
            # запасные названия страницы
            for alt in _alt_pages(slug, title):
                try:
                    items = _tournament_candidates(alt)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {slug}: {exc}")
                if items:
                    break
        candidates[slug] = items

    # 2) если в статье нет подходящих фото — страница арены
    for slug, _title in pending:
        if any(rank <= RANK_EXT_JPEG for rank, _n, _c in candidates.get(slug, [])):
            continue
        info = TOURNAMENT_PAGES.get(slug) or {}
        for venue in info.get("venues", []):
            try:
                text = _wikitext(venue)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {slug} (арена {venue}): {exc}")
                continue
            if not text:
                continue
            for name, caption, _position in _file_links(text, EXTENDED_LIMIT):
                if _photo_score(name) > 0:
                    candidates[slug].append((RANK_VENUE_PAGE, name, caption))
            url = _page_images(venue)
            if url and _is_photo_url(url):
                candidates[slug].append((RANK_VENUE_PAGE, "", "", url))
            break

    # 3) метаданные файлов — пачками
    names = []
    for items in candidates.values():
        for _rank, name, _caption, *_rest in items:
            if name:
                names.append(name)
    for slug in pending:
        for preferred in PREFERRED_PHOTOS.get(slug[0], []):
            names.append(preferred)
    urls = _image_urls(names, PHOTO_WIDTH_TOURNAMENT)

    # 4) выбираем фото
    for slug, title in pending:
        photo = ""
        caption = ""
        # сначала заранее выбранные фотографии площадок
        for preferred in PREFERRED_PHOTOS.get(slug, []):
            url = urls.get(_norm(preferred))
            if url and _is_photo_url(url):
                photo = _clean_url(url)
                break
        if not photo:
            for item in sorted(candidates.get(slug, []), key=lambda i: i[0]):
                rank, name, cap = item[0], item[1], item[2]
                direct_url = item[3] if len(item) > 3 else ""
                url = direct_url or urls.get(_norm(name))
                if url and _is_photo_url(url):
                    photo, caption = _clean_url(url), _clean_text(cap)
                    break
        if not photo:
            # последний шанс — оригинал картинки-«лида» страницы турнира
            photo = _page_images(title)
            if photo and not _is_photo_url(photo):
                photo = ""
        result[slug] = {"photo": photo, "caption": caption}
        cache[slug] = {"photo": photo, "caption": caption,
                       "t": datetime.now(timezone.utc).isoformat(), "n": title}
        print(f"    {slug}: {'ок' if photo else 'не найдено'}")

    cache_write(CACHE_TOURNAMENTS, cache)
    return result


def _alt_pages(slug, title):
    """Запасные названия страницы турнира (кроме уже использованного)."""
    info = TOURNAMENT_PAGES.get(slug) or {}
    return [t for t in info.get("pages", []) if t.lower() != str(title or "").lower()]


# === ИГРОКИ: ПРОФИЛИ ===

def _player_page(name):
    """Ищем страницу теннисиста и возвращаем (title, text)."""
    for title in (name, f"{name} (tennis)"):
        if not title:
            continue
        text = _wikitext(title)
        if text and _find_template(text, "Infobox tennis biography"):
            return title, text
    # запасной вариант — поиск по имени
    query = re.sub(r"[<>\"*]", " ", str(name or "")).strip()
    if query:
        data = _api_get({
            "action": "query", "format": "json", "formatversion": "2",
            "list": "search", "srsearch": f"{query} tennis player",
            "srlimit": "5", "srnamespace": "0",
        }, f"поиск «{query}»")
        for item in ((data or {}).get("query") or {}).get("search") or []:
            title = item.get("title") or ""
            if not title:
                continue
            text = _wikitext(title)
            if text and _find_template(text, "Infobox tennis biography"):
                return title, text
    return "", ""


def _country_name(value):
    """Страна из значения поля country: «{{flagu|Italy}}» → «Italy»."""
    if not value:
        return ""
    # все варианты записи страны вместе с «периодом» после шаблона
    found = []
    pattern = re.compile(r"\{\{\s*(?:flagu|flag|flagicon|country)\s*\|\s*([^|}]+)"
                         r"(?:\|[^}]*)?\}\}|"
                         r"\{\{\s*([A-Z]{3})\s*(?:\|[^}]*)?\}\}", re.I)
    for match in pattern.finditer(value):
        code = (match.group(1) or match.group(2) or "").strip()
        if not code:
            continue
        tail = value[match.end():match.end() + 24]
        period = re.match(r"\s*\(([^)]*)\)", tail)
        found.append((code, period.group(1) if period else ""))

    # текущая страна — та, у которой период открыт («2018–», «2006–present»)
    for code, period in found:
        if "–" in period and not re.search(r"–\s*\d{4}", period):
            return _country_label(code)
        if "present" in period.lower():
            return _country_label(code)
    if found:
        return _country_label(found[-1][0])
    return _clean_text(value)


def _country_label(code):
    """Код страны → название (или сам код, если это уже название)."""
    code = code.strip()
    if code.upper() in COUNTRY_NAMES:
        return COUNTRY_NAMES[code.upper()]
    if re.fullmatch(r"[A-Z]{2,3}", code):
        return code
    return code


def _parse_height(value):
    """Рост: «{{convert|1.91|m|abbr=on}}» → «1,91 м», «5 ft 9 in» → «1,75 м»."""
    if not value:
        return ""
    match = re.search(r"\{\{\s*convert\s*\|(.*?)\}\}", value, re.S | re.I)
    if match:
        args = [a.strip() for a in match.group(1).split("|")]
        args = [a for a in args if a and "=" not in a]  # убираем abbr=on и т.п.
        numbers = []
        for i, arg in enumerate(args):
            if not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", arg):
                continue
            unit = ""
            for nxt in args[i + 1:i + 2]:
                if re.fullmatch(r"[a-zA-Z'\"]+", nxt):
                    unit = nxt.lower()
            numbers.append((float(arg.replace(",", ".")), unit))
        for amount, unit in numbers:
            if unit in ("m", "meter", "metre"):
                return _format_meters(amount * 1.0)
        feet = next((v for v, u in numbers if u in ("ft", "'", "feet")), None)
        if feet is not None:
            inches = next((v for v, u in numbers if u in ("in", '"', "inch")), 0.0)
            return _format_meters((feet * 12 + inches) * 0.0254)
    plain = _clean_text(value)
    match = re.search(r"([0-9]+[.,][0-9]+)\s*(?:m\b|м\b|metre|meter)", plain, re.I)
    if match:
        return _format_meters(float(match.group(1).replace(",", ".")))
    match = re.search(r"([0-9]+)\s*(?:'|’|ft\b|feet)\s*([0-9.,]+)?\s*(?:''|”|\"|in\b|inches)?", plain, re.I)
    if match:
        feet = float(match.group(1))
        inches = float((match.group(2) or "0").replace(",", "."))
        return _format_meters((feet * 12 + inches) * 0.0254)
    return plain


def _format_meters(value):
    """Метры → «1,91 м»."""
    return f"{value:.2f}".replace(".", ",") + " м"


def _parse_weight(value):
    """Вес: «{{convert|83|kg|abbr=on}}» → «83 кг»."""
    if not value:
        return ""
    match = re.search(r"\{\{\s*convert\s*\|\s*([0-9]+(?:[.,][0-9]+)?)\s*\|\s*kg", value, re.I)
    if not match:
        match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:kg\b|кг\b)", value, re.I)
    if match:
        number = match.group(1).replace(",", ".").split(".")[0]
        return f"{number} кг"
    return _clean_text(value)


def _parse_birthdate(value):
    """Дата рождения из «{{birth date and age|2001|8|16|df=yes}}» → date."""
    if not value:
        return None
    numbers = [n for n in re.findall(r"\d+", value) if len(n) <= 4]
    if len(numbers) >= 3:
        try:
            return date(int(numbers[0]), int(numbers[1]), int(numbers[2]))
        except ValueError:
            pass
    plain = _clean_text(value)
    match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", plain)
    if match:
        months = ["january", "february", "march", "april", "may", "june", "july",
                  "august", "september", "october", "november", "december"]
        name = match.group(2).lower()
        if name in months:
            try:
                return date(int(match.group(3)), months.index(name) + 1, int(match.group(1)))
            except ValueError:
                return None
    return None


def _age(born, today=None):
    """Полных лет от даты рождения."""
    if not born:
        return None
    today = today or date.today()
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years if years >= 0 else None


def _split_sentences(text):
    """Делит текст на предложения (с учётом сокращений)."""
    parts = []
    start = 0
    for match in re.finditer(r"[.!?]+(?=\s+[A-Z0-9\"'“‘(])", text):
        end = match.end()
        head = text[:end].rstrip(".!?").split()
        word = head[-1].lower() if head else ""
        if word in ABBREVIATIONS:
            continue
        if len(word) == 1 and word.isalpha():
            continue
        chunk = text[start:end].strip()
        if chunk:
            parts.append(chunk)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _lead_text(text):
    """Лид статьи: текст после инфобокса и служебных шаблонов."""
    if not text:
        return ""
    body = text
    infobox = _find_template(body, "Infobox tennis biography")
    if infobox:
        body = body.replace(infobox, " ")
    # убираем служебные шаблоны в начале статьи
    for _ in range(12):
        new = re.sub(r"^\s*(?:\{\{[^{}]*\}\}|<!--.*?-->)\s*", " ", body, flags=re.S)
        if new == body:
            break
        body = new
    # лид заканчивается первой секцией
    body = re.split(r"\n==+[^=]", body)[0]
    return body.strip()


def _extract_titles(summary, lead):
    """Предложение про титулы из лида (для поля titles)."""
    for source in (summary, lead):
        if not source:
            continue
        for sentence in _split_sentences(source):
            for pattern in TITLES_PATTERNS:
                if re.search(pattern, sentence, re.I):
                    return _clean_text(sentence)
    return ""


def player_profiles(players):
    """players: список словарей {"name":..., "id":..., "country_code":...}.

    Возвращает {player["id"]: {"photo":..., "country":..., "residence":...,
                                "turned_pro":..., "height":..., "plays":..., "weight":...,
                                "born":..., "age":..., "summary":..., "titles":...,
                                "wiki_url":...}}.
    """
    cache = _load_cache(CACHE_PLAYERS)
    result = {}
    pending = []

    for player in players:
        pid = player.get("id") or ""
        entry = cache.get(pid)
        if entry and entry.get("photo"):
            result[pid] = _profile_fields(entry)
        else:
            pending.append(player)

    if not pending:
        return result

    print(f"  Wikipedia: собираем профили для {len(pending)} игроков")

    # 1) страницы и инфобоксы
    parsed = {}
    for player in pending:
        pid = player.get("id") or ""
        name = player.get("name") or ""
        try:
            title, text = _player_page(name)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name}: {exc}")
            title, text = "", ""
        fields = _infobox_fields(text) if text else {}
        parsed[pid] = {
            "title": title,
            "fields": fields,
            "lead": _lead_text(text) if text else "",
        }

    # 2) фото — пачками по 50 файлов
    names = []
    for info in parsed.values():
        image = _file_name((info["fields"] or {}).get("image", ""))
        if image:
            names.append(image)
    urls = _image_urls(names, PHOTO_WIDTH_PLAYER)

    # 3) собираем профили
    for player in pending:
        pid = player.get("id") or ""
        name = player.get("name") or ""
        info = parsed.get(pid) or {}
        fields = info.get("fields") or {}
        lead = info.get("lead") or ""

        photo = ""
        image = _file_name(fields.get("image", ""))
        if image:
            photo = urls.get(_norm(image)) or ""
        if not photo and info.get("title"):
            photo = _page_images(info["title"])
            if not _is_photo_url(photo):
                photo = ""

        born = _parse_birthdate(fields.get("birth_date", "") or fields.get("birthdate", ""))
        turned = _clean_text(fields.get("turnedpro", "") or fields.get("turned_pro", ""))
        digits = re.search(r"\d{4}", turned)
        turned_pro = digits.group(0) if digits else turned
        country_raw = (fields.get("country") or fields.get("country_represented")
                       or fields.get("citizenship") or "")

        clean_lead = _clean_text(lead)
        sentences = _split_sentences(clean_lead)
        summary = " ".join(sentences[:3]).strip()
        titles = _extract_titles(summary, clean_lead)

        profile = {
            "photo": _clean_url(photo),
            "country": _country_name(country_raw),
            "residence": _clean_cell(fields.get("residence", "")),
            "turned_pro": turned_pro,
            "height": _parse_height(fields.get("height", "")),
            "plays": _clean_cell(fields.get("plays", "")),
            "weight": _parse_weight(fields.get("weight", "")),
            "born": born.isoformat() if born else "",
            "age": _age(born),
            "summary": summary,
            "titles": titles,
            "wiki_url": _wiki_url(info.get("title") or name),
        }
        result[pid] = profile
        cache[pid] = dict(profile)
        cache[pid]["t"] = datetime.now(timezone.utc).isoformat()
        cache[pid]["n"] = name
        print(f"    {name}: {'ок' if profile['photo'] else 'без фото'}")

    cache_write(CACHE_PLAYERS, cache)
    return result


def _profile_fields(entry):
    """Профиль из кэша (без служебных полей); возраст пересчитываем."""
    profile = {key: entry.get(key, "") for key in
               ("photo", "country", "residence", "turned_pro", "height", "plays",
                "weight", "born", "age", "summary", "titles", "wiki_url")}
    if profile.get("born"):
        try:
            profile["age"] = _age(date.fromisoformat(profile["born"]))
        except ValueError:
            pass
    return profile


def _wiki_url(title):
    """Ссылка на страницу Википедии."""
    if not title:
        return ""
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


# === КЭШ ===

def _load_cache(name):
    """Кэш с TTL: возвращает только свежие записи."""
    raw = cache_read(name) or {}
    now = datetime.now(timezone.utc)
    fresh = {}
    for key, item in raw.items():
        if not isinstance(item, dict):
            continue
        try:
            age_days = (now - datetime.fromisoformat(item.get("t", ""))).days
        except (TypeError, ValueError):
            age_days = 9999
        if age_days < CACHE_TTL_DAYS:
            fresh[key] = item
    return fresh


# === ЗАПУСК ===

def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _tournament_pages():
    """Список (slug, wiki_page_title) из data/index.json."""
    index = _read_json(os.path.join(DATA_DIR, "index.json"))
    pages = []
    for item in index.get("tournaments") or []:
        slug = item.get("slug") or ""
        if not slug:
            continue
        info = TOURNAMENT_PAGES.get(slug) or {}
        title = (info.get("pages") or [item.get("name") or slug])[0]
        pages.append((slug, title))
    return pages


def _ranking_players():
    """Список игроков из data/rankings.json."""
    rankings = _read_json(os.path.join(DATA_DIR, "rankings.json"))
    players = []
    for group in ("men", "women"):
        for item in rankings.get(group) or []:
            pid = item.get("id") or ""
            name = item.get("name") or ""
            if not pid or not name:
                continue
            players.append({
                "name": name,
                "id": pid,
                "country_code": item.get("country_code") or "",
            })
    return players


def main():
    """Пишет data/tournament_photos.json и data/player_profiles.json."""
    pages = _tournament_pages()
    players = _ranking_players()
    print(f"Турниров: {len(pages)}, игроков: {len(players)}")

    photos = tournament_photos(pages)
    profiles = player_profiles(players)

    write_json(os.path.join(DATA_DIR, "tournament_photos.json"), photos)
    write_json(os.path.join(DATA_DIR, "player_profiles.json"), profiles)

    with_photo = sum(1 for item in photos.values() if item.get("photo"))
    with_profile_photo = sum(1 for item in profiles.values() if item.get("photo"))
    print(f"Фото турниров: {with_photo}/{len(photos)}")
    print(f"Фото игроков: {with_profile_photo}/{len(profiles)}")
    print("Записано: data/tournament_photos.json, data/player_profiles.json")


if __name__ == "__main__":
    main()
