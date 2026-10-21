#!/usr/bin/env python3
"""Провайдер Live Tennis API (https://livetennisapi.com).

Бесплатный тариф: 30 запросов/мин, 100 запросов/сутки, ключ выдаётся сразу по почте.
Доступно на Free:
    GET /matches?status=live      — идущие матчи со счётом
    GET /matches?status=upcoming  — ближайшие матчи
    GET /fixtures                 — расписание (жеребьёвка) с временем старта
    GET /players                  — игроки (список отсортирован по рейтингу)
    GET /players/{id}             — профиль игрока: рейтинг, очки, страна
    GET /tournaments              — каталог турниров (уровень, город, страна)
    GET /usage                    — расход квоты (не тратит лимит)

Даёт то, чего не хватает бесплатным открытым источникам: жеребьёвку будущих
турниров с точным временем старта, live-счёт и уровень турнира.
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from common import http_get_json  # noqa: E402

LTA_BASE = "https://api.livetennisapi.com/api/public/v1"

# Коды раундов Live Tennis API → внутренние названия
ROUND_CODES = {
    "R128": "round_of_128",
    "R64": "round_of_64",
    "R32": "round_of_32",
    "R16": "round_of_16",
    "Q": "quarterfinal",
    "SF": "semifinal",
    "F": "final",
    "Q1": "qualification_round_1",
    "Q2": "qualification_round_2",
    "Q3": "qualification_round_3",
    "R16Q": "qualification_round_1",
    "R32Q": "qualification_round_2",
    "R64Q": "qualification_round_3",
}


def get_key():
    key = os.environ.get("LIVETENNIS_API_KEY", "").strip()
    return key or None


def api_get(path, params=None):
    """GET к Live Tennis API. Возвращает (data, error)."""
    key = get_key()
    if not key:
        return None, "нет ключа LIVETENNIS_API_KEY"
    query = dict(params or {})
    query["limit"] = query.get("limit", 100)
    url = f"{LTA_BASE}{path}"
    data, error = http_get_json(
        url + "?" + "&".join(f"{k}={v}" for k, v in query.items()),
        headers={"Accept": "application/json", "X-API-Key": key},
        timeout=45,
    )
    return data, error


def _rows(data):
    return (data or {}).get("data") or []


def normalize_round(match):
    """Раунд из round_code, иначе из текстового round."""
    code = str(match.get("round_code") or "").strip().upper()
    if code in ROUND_CODES:
        return ROUND_CODES[code]
    text = str(match.get("round") or "").strip().lower()
    mapping = {
        "quarterfinal": "quarterfinal", "quarter finals": "quarterfinal", "q": "quarterfinal",
        "semifinal": "semifinal", "semi finals": "semifinal", "sf": "semifinal",
        "final": "final", "f": "final",
        "round of 128": "round_of_128", "round of 64": "round_of_64",
        "round of 32": "round_of_32", "round of 16": "round_of_16",
        "r128": "round_of_128", "r64": "round_of_64", "r32": "round_of_32", "r16": "round_of_16",
    }
    return mapping.get(text, "")


def normalize_player(player, side):
    """Игрок из match.players.p1/p2 в наш формат."""
    if not isinstance(player, dict):
        return {"id": "", "name": "", "country_code": "", "qualifier": side}
    out = {
        "id": f"lta:{player.get('id', '')}",
        "name": player.get("name") or "TBD",
        "country_code": (player.get("country") or "").strip().upper(),
        "qualifier": side,
    }
    seed = player.get("seed")
    if seed:
        out["seed"] = seed
    return out


def normalize_score(match):
    """Счёт по сетам → {home, away, periods}."""
    score = match.get("score") or {}
    sets = score.get("sets")
    if not isinstance(sets, list) or not sets:
        return None
    periods = []
    for index, pair in enumerate(sets, 1):
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            periods.append({"home": int(pair[0]), "away": int(pair[1]), "number": index})
        except (TypeError, ValueError):
            continue
    if not periods:
        return None
    return {
        "home": sum(1 for p in periods if p["home"] > p["away"]),
        "away": sum(1 for p in periods if p["away"] > p["home"]),
        "periods": periods,
    }


def normalize_match(match, tournaments=None):
    """Матч Live Tennis API → наш формат."""
    if not isinstance(match, dict):
        return None
    match_id = match.get("id")
    if match_id is None:
        return None

    status = str(match.get("status") or "").lower()
    if status == "live":
        our_status = "live"
    elif status == "upcoming":
        our_status = "not_started"
    elif status in ("completed", "cancelled"):
        our_status = "closed"
    else:
        our_status = "not_started"

    players = match.get("players") or {}
    home = normalize_player(players.get("p1"), "home")
    away = normalize_player(players.get("p2"), "away")

    tour = str(match.get("tour") or "").lower()
    gender = str(match.get("gender") or "").lower()
    if gender not in ("men", "women"):
        gender = "women" if tour.startswith("wta") else "men"
    category = "WTA" if tour.startswith("wta") else "ATP"

    round_name = normalize_round(match)
    if not round_name:
        return None

    result = {
        "id": f"lta:{match_id}",
        "round": round_name,
        "gender": gender,
        "category": category,
        "start_time": match.get("scheduled_time") or match.get("start_time") or "",
        "status": our_status,
        "match_status": str(match.get("event_status") or ""),
        "best_of": 3,
        "players": [home, away],
        "tournament": match.get("tournament") or "",
        "tier": match.get("tier") or "",
        "source": "livetennis",
    }
    if match.get("format"):
        result["best_of"] = 3
    if match.get("is_qualifying"):
        result["is_qualification"] = True
    if match.get("surface"):
        result["surface"] = match["surface"]

    scores = normalize_score(match)
    if scores:
        result["scores"] = scores

    winner = match.get("winner")
    if winner in (1, 2) and our_status == "closed":
        result["winner_id"] = home["id"] if winner == 1 else away["id"]

    if tournaments and match.get("tournament_id") in tournaments:
        info = tournaments[match["tournament_id"]]
        if info.get("city"):
            result["city"] = info["city"]
        if info.get("country"):
            result["country"] = info["country"]
        if info.get("name"):
            result["tournament"] = info["name"]
        if info.get("tier"):
            result["tier"] = info["tier"]
    return result


def fetch_tournaments():
    """Каталог турниров: {tournament_id: {...}}."""
    data, error = api_get("/tournaments", {"limit": 200})
    if not data:
        print(f"  Live Tennis API: каталог турниров недоступен — {error}")
        return {}
    result = {}
    for row in _rows(data):
        if not isinstance(row, dict):
            continue
        tid = row.get("id")
        if not tid:
            continue
        result[str(tid)] = {
            "name": row.get("name"),
            "city": row.get("city"),
            "country": row.get("country"),
            "tier": row.get("tier"),
            "category": row.get("category"),
            "tour": row.get("tour"),
        }
    return result


def fetch_matches():
    """Все доступные матчи: предстоящие + идущие."""
    tournaments = fetch_tournaments()
    matches = []
    for status in ("upcoming", "live"):
        data, error = api_get("/matches", {"status": status, "limit": 100})
        if not data:
            print(f"  Live Tennis API: status={status} — {error}")
            continue
        for row in _rows(data):
            normalized = normalize_match(row, tournaments)
            if normalized:
                matches.append(normalized)
    return matches


def fetch_fixtures():
    """Расписание (жеребьёвка) — источник участников будущих матчей."""
    data, error = api_get("/fixtures", {"limit": 100})
    if not data:
        print(f"  Live Tennis API: расписание недоступно — {error}")
        return []
    result = []
    for row in _rows(data):
        normalized = normalize_match(row)
        if normalized:
            result.append(normalized)
    return result


def fetch_rankings(limit=120):
    """Рейтинг ATP/WTA: список игроков отсортирован по рейтингу."""
    data, error = api_get("/players", {"limit": limit})
    if not data:
        print(f"  Live Tennis API: рейтинг недоступен — {error}")
        return {"men": [], "women": []}
    result = {"men": [], "women": []}
    for row in _rows(data):
        if not isinstance(row, dict):
            continue
        rank = row.get("ranking")
        if not rank:
            continue
        tour = str(row.get("tour") or "").lower()
        gender = "women" if tour.startswith("wta") else "men"
        result[gender].append({
            "rank": rank,
            "movement": 0,
            "points": row.get("ranking_points") or 0,
            "played": 0,
            "id": f"lta:{row.get('id', '')}",
            "name": row.get("name") or "",
            "country_code": (row.get("country") or "").strip().upper(),
        })
    for bucket in result.values():
        bucket.sort(key=lambda r: r["rank"])
    return result


def is_available():
    """Есть ли ключ и отвечает ли API."""
    if not get_key():
        return False
    data, error = api_get("/usage", {"limit": 1})
    return bool(data)
