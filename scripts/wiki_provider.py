#!/usr/bin/env python3
"""Источник данных из Википедии: календарь турниров и сетки (жеребьёвки).

Откуда берём:
  • «{год} ATP Tour» / «{год} WTA Tour» — календарь сезона: турниры, даты, уровень,
    город и ссылка на страницу сетки. Страница появляется заранее (обычно в ноябре
    предыдущего года), поэтому в календаре есть и будущие турниры;
  • «{год} {Турнир} – Men's/Women's singles» — сама сетка: участники каждого матча
    и счёт по сетам. Страница появляется, когда жеребьёвка опубликована.

Особенности формата:
  • сетка оформлена шаблоном `{{16TeamBracket-Compact-Tennis5}}` с плоскими
    параметрами `RD<n>-team<NN>`, `RD<n>-seed<NN>`, `RD<n>-score<NN>-<k>`;
  • в секции «Finals» этот шаблон содержит последние три раунда (1/4, 1/2, финал),
    а в секциях «Section N» — первые (1/64 … 1/8);
  • жирный шрифт `'''…'''` отмечает победителя.
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

WIKI_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "grand-slam-calendar/1.0 (https://github.com/nikstopka/grand-slam-calendar)"

# Сколько матчей в раунде → внутреннее название
ROUND_BY_SIZE = {
    64: "round_of_128",
    32: "round_of_64",
    16: "round_of_32",
    8: "round_of_16",
    4: "quarterfinal",
    2: "semifinal",
    1: "final",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# В календаре месяцы записаны сокращённо: «2 Mar», «9 Mar»
MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Уровни турниров из календаря → наши вкладки
LEVEL_MAP = [
    ("grand slam", "grand_slam"),
    ("atp 1000", "atp_1000"),
    ("wta 1000", "wta_1000"),
    ("atp finals", "atp_finals"),
    ("wta finals", "wta_finals"),
]


# === HTTP ===

# Уровень турнира определяем по названию (нужно для WTA-календаря,
# где уровень задан заголовком колонки, а не ячейкой)
LEVEL_BY_NAME = {
    "australian open": "grand_slam",
    "roland garros": "grand_slam",
    "wimbledon": "grand_slam",
    "us open": "grand_slam",
    "doha": "wta_1000",
    "dubai": "wta_1000",
    "indian wells": "wta_1000",
    "miami": "wta_1000",
    "madrid": "wta_1000",
    "rome": "wta_1000",
    "montreal": "wta_1000",
    "toronto": "wta_1000",
    "cincinnati": "wta_1000",
    "beijing": "wta_1000",
    "wuhan": "wta_1000",
    "guangzhou": "wta_1000",
}


def api_get(params):
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def wikitext(title):
    data = api_get({
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "redirects": "1", "titles": title,
    })
    if not data:
        return None
    page = (data.get("query") or {}).get("pages") or [{}]
    page = page[0]
    if page.get("missing"):
        return None
    revisions = page.get("revisions") or []
    if not revisions:
        return None
    return (revisions[0].get("slots") or {}).get("main", {}).get("content")


def page_exists(title):
    data = api_get({
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "info", "redirects": "1", "titles": title,
    })
    if not data:
        return False
    page = ((data.get("query") or {}).get("pages") or [{}])[0]
    return not page.get("missing")


# === РАЗБОР ТАБЛИЦ ===

def split_rows(table):
    """Делит wikitable на строки (учитывая |- внутри ячеек)."""
    rows = []
    current = []
    for line in table.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|-"):
            if current:
                rows.append(current)
            current = []
            continue
        if stripped.startswith("|") or stripped.startswith("!"):
            current.append(stripped)
    if current:
        rows.append(current)
    return rows


def split_cells(row):
    """Делит строку на ячейки, разбирая rowspan.

    В викитексте атрибут rowspan идёт отдельным сегментом:
    ``|rowspan=3|2 Mar`` или ``| rowspan=3 style="..." |text``.
    """
    if isinstance(row, list):
        row = "\n".join(row)

    segments = []
    i = 0
    while i < len(row):
        ch = row[i]
        if ch not in "|!":
            i += 1
            continue
        j = i + 1
        depth = 0
        links = 0
        while j < len(row):
            c = row[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif row.startswith("[[", j):
                links += 1
                j += 1
                continue
            elif row.startswith("]]", j):
                links -= 1
                j += 1
                continue
            elif depth == 0 and links == 0 and c == "|":
                break
            j += 1
        segments.append(row[i + 1:j])
        i = j + 1

    cells = []
    k = 0
    while k < len(segments):
        seg = segments[k]
        m = re.match(r"\s*rowspan=(\d+)", seg)
        if m and k + 1 < len(segments):
            rowspan = int(m.group(1))
            content = segments[k + 1]
            k += 2
        else:
            rowspan = 1
            content = seg
            k += 1
        cells.append((content.strip(), rowspan))
    return cells


def clean_cell(text):
    """Убирает разметку Википедии, оставляя читаемый текст."""
    text = re.sub(r"\{\{[^}]*\}\}", " ", text)
    text = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", text)   # [[цель|текст]]
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)                # [[цель]]
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"\s+", " ", text).strip(" |")
    return text.strip()


def cell_link(text):
    """Первая ссылка [[Цель|Отображаемое]] → (цель, отображаемое)."""
    m = re.search(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]", text)
    if not m:
        return None, None
    return m.group(1).strip(), (m.group(2) or m.group(1)).strip()


# === КАЛЕНДАРЬ ===

DATE_RE = re.compile(
    r"(?:(?P<d1>\d{1,2})\s*(?P<m1>[A-Za-z]{3,})|(?P<m2>[A-Za-z]{3,})\s*(?P<d2>\d{1,2}))\.?")


def parse_date(text, month, year):
    """«2 Mar» или «Dec 29» → дата. Пустая строка не должна ломать разбор."""
    if not text:
        return None
    m = DATE_RE.search(text.strip())
    if not m:
        return None
    if m.group("d1"):
        day = int(m.group("d1"))
        word = m.group("m1").lower()
    else:
        day = int(m.group("d2"))
        word = m.group("m2").lower()
    mon = MONTHS.get(word) or MONTH_ABBR.get(word[:3])
    if not mon:
        return None
    # декабрь может переходить в январь следующего года
    if month == 12 and mon == 1:
        year += 1
    if month == 1 and mon == 12:
        year -= 1
    try:
        return date(year, mon, day)
    except ValueError:
        return None


def classify_level(text, name=""):
    """Определяет уровень турнира по строке календаря или по названию.

    В ATP-календаре уровень написан прямо в ячейке («ATP 1000»),
    а в WTA — вынесен в заголовок колонки, поэтому там приходится
    определять уровень по названию турнира.
    """
    low = (text or "").strip().lower()
    for key, value in LEVEL_MAP:
        if low.startswith(key):
            return value
    for key, value in LEVEL_MAP:
        if key in low:
            return value

    norm = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    for key, value in LEVEL_BY_NAME.items():
        if norm.startswith(key) or key in norm:
            return value
    return ""


def parse_calendar(text, year, tour):
    """Викитекст сезона → список турниров.

    Строка календаря устроена так:
    ``|rowspan=3|2 Mar<br />9 Mar|| rowspan=3 style="..." |[[Страница|Название]]<br />
    [[Город]], Страна<br />Уровень<br />…``
    Разбираем регуляркой — это надёжнее, чем разбор wiki-таблиц.
    """
    tournaments = []
    heads = [(m.start(), m.group(1).strip().lower())
              for m in re.finditer(r"^=+\s*([^=\n]+?)\s*=+\s*$", text, re.M)]

    row_re = re.compile(
        # неделя: «rowspan=3|2 Mar<br />9 Mar» (ATP) или «rowspan="2" |Sep 28<br/>Oct 5» (WTA)
        r'rowspan="?\d+"?\s*\|(?P<start>(?:\d{1,2}\s*[A-Za-z]{3,}|[A-Za-z]{3,}\s*\d{1,2}))'
        r"(?:\s*<br\s*/?>\s*(?P<end>(?:\d{1,2}\s*[A-Za-z]{3,}|[A-Za-z]{3,}\s*\d{1,2})))?"
        # турнир (у WTA перед ссылкой бывает пробел)
        r".*?\|\s*\[\[(?P<page>[^\]|]+)\|(?P<name>[^\]]+)\]\](?P<cell>[^\n]*)",
        re.S)

    for idx, (pos, name) in enumerate(heads):
        if name not in MONTHS:
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(text)
        body = text[pos:end]
        month = MONTHS[name]

        for m in row_re.finditer(body):
            cell = m.group("cell")
            level = classify_level(cell, m.group("name"))
            if not level:
                continue

            start = parse_date(m.group("start"), month, year)
            if not start:
                continue
            finish = parse_date(m.group("end"), month, year) if m.group("end") else None

            # место: первая ссылка после названия турнира
            place = ""
            pm = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", cell)
            if pm:
                city = (pm.group(2) or pm.group(1)).strip()
                country = ""
                cm = re.search(r"\]\],\s*([^\n<|]+)", cell)
                if cm:
                    country = cm.group(1).strip(" ,")
                place = ", ".join(x for x in (city, country) if x)

            # ссылка на страницу сетки — идёт последней в строке турнира
            draw_link = ""
            dm = re.search(r"\[\[([^\]]*[Ss]ingles[^\]]*)\]\]", cell)
            if dm:
                draw_link = dm.group(1).split("|")[0].strip()

            tournaments.append({
                "name": m.group("name").strip(),
                "wiki_page": m.group("page").strip(),
                "draw_page": draw_link,
                "level": level,
                "place": place,
                "start": start.isoformat(),
                "end": (finish or start).isoformat(),
                "tour": tour,
            })
    return tournaments


def fetch_calendar(year):
    """Календарь ATP и WTA на год: [{name, level, start, end, ...}]."""
    result = []
    for tour, page in (("atp", f"{year} ATP Tour"), ("wta", f"{year} WTA Tour")):
        text = wikitext(page)
        if not text:
            continue
        result.extend(parse_calendar(text, year, tour))
    # убираем дубли по названию и датам
    unique = {}
    for item in result:
        key = (item["name"].lower(), item["start"])
        unique.setdefault(key, item)
    return sorted(unique.values(), key=lambda t: t["start"])


# === СЕТКА ===

def parse_bracket_section(body, kind, gender, tournament, late_rounds=3, tag=""):
    """Разбирает шаблон сетки в список матчей с участниками.

    В шаблонах Википедии номера слотов идут подряд: два слота — одна пара
    (RD1-team01 и RD1-team02 — участники первого матча).

    Раунд определяем по подписям шаблона, а не по числу участников: у Masters
    сетка на 96 игроков, и «число матчей в раунде» не степень двойки.
    Число поздних раундов (1/4, 1/2, финал) берём из секции Finals — оно
    тоже разное: в сетке на 128 участников Finals содержит три раунда,
    а в сетке на 64 — два (1/4 остаётся в секциях).
    """
    teams = {}
    seeds = {}
    # Важно: после "=" только пробелы и табы — иначе пустое значение
    # захватит следующую строку (в \s входит перевод строки).
    for key, value in re.findall(
            r"\|\s*(RD\d+-(?:team|seed)\d+)\s*=[ \t]*([^\n]*)", body):
        m = re.match(r"RD(\d+)-(team|seed)(\d+)$", key)
        if not m:
            continue
        rd, kind_name, number = int(m.group(1)), m.group(2), int(m.group(3))
        if kind_name == "seed":
            seeds[(rd, number)] = clean_cell(value)
            continue
        name = clean_cell(value)
        if not name:
            continue
        target, _disp = cell_link(value)
        # берём полное имя из ссылки, а не сокращённое («C Alcaraz» → «Carlos Alcaraz»),
        # уточнения в скобках («Tommy Paul (tennis)») убираем
        if target:
            name = re.sub(r"\s*\([^)]*\)\s*$", "", target).strip()
        teams[(rd, number)] = {
            "name": name,
            "wiki": target or "",
            "winner": "'''" in value,
        }
    if not teams:
        return []

    rd_count = len({rd for rd, _ in teams})
    by_round = {}
    for (rd, number), player in teams.items():
        by_round.setdefault(rd, {})[number] = player

    result = []
    for rd, slots in by_round.items():
        if kind == "finals":
            size = 2 ** (late_rounds - rd)      # 4, 2, 1 матча: 1/4, 1/2, финал
        else:
            size = 2 ** (late_rounds + rd_count - rd)
        round_name = ROUND_BY_SIZE.get(size)
        if not round_name:
            continue
        maxnum = max(slots)
        # слоты идут подряд: два слота — одна пара
        for k in range(1, maxnum // 2 + 1):
            first = slots.get(2 * k - 1)
            second = slots.get(2 * k)
            if not first or not second:
                continue
            result.append({
                "id": f"wiki:{tournament}:{gender}:{kind[:1]}{tag}{rd}-{k}",
                "round": round_name,
                "players": [first, second],
                "seed": seeds.get((rd, 2 * k - 1), ""),
                "seed2": seeds.get((rd, 2 * k), ""),
            })
    return result


def parse_draw_page(text, tournament, gender, draw_size):
    """Страница сетки → список матчей с участниками."""
    heads = [(m.start(), m.group(1).strip()) for m in
             re.finditer(r"^=+\s*([^=\n]+?)\s*=+\s*$", text, re.M)]

    matches = []
    # секция Finals: 1/4, 1/2, финал (число раундов разное — смотрим подписи)
    late_rounds = 3
    for idx, (pos, title) in enumerate(heads):
        if not title.lower().startswith("finals"):
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(text)
        body = text[pos:end]
        labels = {int(m[2:]) for m in re.findall(r"\|\s*(RD\d+)\s*=[ \t]*", body)}
        if labels:
            late_rounds = len(labels)
        matches.extend(parse_bracket_section(
            body, "finals", gender, tournament, late_rounds, "F"))
    # секции Section N: первые раунды
    for idx, (pos, title) in enumerate(heads):
        if not title.lower().startswith("section"):
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(text)
        matches.extend(parse_bracket_section(
            text[pos:end], "section", gender, tournament, late_rounds, f"S{idx}"))

    # Самопроверка: в сетке на N участников ровно N-1 матчей. Если не совпало —
    # структура страницы другая, и лучше не добавить кривые данные.
    expected = draw_size - 1 if draw_size else 0
    if expected and len(matches) != expected:
        print(f"    Wikipedia: сетка {tournament} ({gender}) — разобрано {len(matches)} "
              f"матчей вместо {expected}, пропускаем")
        return []
    return matches


def fetch_draw(tournament_page, gender, draw_size=128):
    """Матчи сетки из страницы турнира. Пусто, если страницы нет."""
    if not tournament_page:
        return []
    title = tournament_page
    suffix = "Men's singles" if gender == "men" else "Women's singles"
    if re.search(r"[–—-]\s*Singles\s*$", title):
        title = re.sub(r"[–—-]\s*Singles\s*$", f"– {suffix}", title)
    elif "singles" not in title.lower():
        title = f"{tournament_page} – {suffix}"
    text = wikitext(title)
    if not text:
        return []
    m = re.search(r"\|\s*draw\s*=\s*(\d+)", text)
    size = int(m.group(1)) if m else draw_size
    return parse_draw_page(text, title, gender, size)
    text = wikitext(title)
    if not text:
        return []
    m = re.search(r"\|\s*draw\s*=\s*(\d+)", text)
    size = int(m.group(1)) if m else draw_size
    if size not in (32, 64, 128):
        return []
    return parse_draw_page(text, title, gender, size)
