#!/usr/bin/env python3
"""
Grand Slam Calendar - Data Fetcher
Автоматически получает расписание матчей Большого шлема через Sportradar Tennis API v3
и сохраняет их в data/matches.json для отображения на GitHub Pages.

Использование:
    python scripts/fetch_tennis.py

Требуется переменная окружения SPORTRADAR_API_KEY (содержится в GitHub Secrets).
Получить бесплатный ключ: https://developer.sportradar.com/
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error

# === КОНФИГУРАЦИЯ ===

# Sportradar Tennis API v3 base URL
API_BASE = "https://api.sportradar.com/tennis/trial/v3/en"

# ID турниров Большого шлема (singles only - одиночные разряды)
GRAND_SLAM_COMPETITIONS = {
    "sr:competition:2567": "Australian Open Men Singles",
    "sr:competition:2571": "Australian Open Women Singles",
    "sr:competition:2579": "French Open Men Singles",
    "sr:competition:2583": "French Open Women Singles",
    "sr:competition:2555": "Wimbledon Men Singles",
    "sr:competition:2559": "Wimbledon Women Singles",
    "sr:competition:2591": "US Open Men Singles",
    "sr:competition:2595": "US Open Women Singles",
}

# Раунды, которые считаются "основными" (четвертьфиналы и дальше)
MAIN_ROUNDS = {"quarterfinal", "semifinal", "final"}

# Количество дней вперёд/назад для проверки расписания
DAYS_BACK = 3
DAYS_FORWARD = 14

# Задержка между запросами (секунды) - чтобы не превысить лимиты API
REQUEST_DELAY = 1.0

# === ФУНКЦИИ ===

def get_api_key():
    """Получает API ключ из переменной окружения."""
    key = os.environ.get("SPORTRADAR_API_KEY")
    if not key:
        print("ОШИБКА: Не найдена переменная окружения SPORTRADAR_API_KEY")
        print("Получите бесплатный ключ на https://developer.sportradar.com/")
        print("И добавьте его в GitHub Secrets (см. README.md)")
        sys.exit(1)
    return key


def api_get(path, params=None):
    """Выполняет GET запрос к Sportradar API."""
    api_key = get_api_key()
    url = f"{API_BASE}{path}.json?api_key={api_key}"

    if params:
        query_parts = [f"{k}={v}" for k, v in params.items()]
        url += "&" + "&".join(query_parts)

    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP ошибка {e.code}: {e.reason} для {path}")
        if e.code == 429:
            print("  Превышен лимит запросов. Увеличиваю задержку...")
            time.sleep(5)
        return None
    except Exception as e:
        print(f"  Ошибка при запросе {path}: {e}")
        return None


def round_display_name(round_name):
    """Преобразует название раунда API в читаемый вид на русском."""
    round_names = {
        "qualification_round_1": "Квалификация. Раунд 1",
        "qualification_round_2": "Квалификация. Раунд 2",
        "qualification_round_3": "Квалификация. Раунд 3",
        "round_of_128": "1/64 финала",
        "round_of_64": "1/32 финала",
        "round_of_32": "1/16 финала",
        "round_of_16": "1/8 финала",
        "quarterfinal": "Четвертьфинал",
        "semifinal": "Полуфинал",
        "final": "Финал",
    }
    return round_names.get(round_name, round_name or "Раунд")


def normalize_match(summary, competition_name):
    """Преобразует данные матча из API в наш формат."""
    sport_event = summary.get("sport_event", {})
    sport_event_status = summary.get("sport_event_status", {})
    context = sport_event.get("sport_event_context", {})
    competitors = sport_event.get("competitors", [])

    # Информация о раунде
    round_info = context.get("round", {})
    round_name = round_info.get("name", "")

    # Стадия (квалификация или основная сетка)
    stage = context.get("stage", {})
    is_qualification = stage.get("phase") == "qualification"

    # Статус матча
    status = sport_event_status.get("status", "not_started")

    # Игроки
    players = []
    for comp in competitors:
        player = {
            "id": comp.get("id", ""),
            "name": comp.get("name", "TBD"),
            "country": comp.get("country", ""),
            "country_code": comp.get("country_code", ""),
            "abbreviation": comp.get("abbreviation", ""),
            "qualifier": comp.get("qualifier", ""),
        }
        if comp.get("seed"):
            player["seed"] = comp["seed"]
        players.append(player)

    # Счёт
    scores = {}
    if status in ("closed", "live") and sport_event_status.get("period_scores"):
        periods = []
        for ps in sport_event_status["period_scores"]:
            period = {
                "home": ps.get("home_score", 0),
                "away": ps.get("away_score", 0),
                "number": ps.get("number", 0),
            }
            if ps.get("home_tiebreak_score") is not None:
                period["home_tb"] = ps["home_tiebreak_score"]
                period["away_tb"] = ps.get("away_tiebreak_score", 0)
            periods.append(period)
        scores = {
            "home": sport_event_status.get("home_score", 0),
            "away": sport_event_status.get("away_score", 0),
            "periods": periods,
        }

    # Короткое название турнира
    tournament_short = competition_name.replace(" Men Singles", "").replace(" Women Singles", "")

    # Категория (ATP/WTA) и пол — берём из объекта competition
    category = context.get("category", {}).get("name", "")
    competition_obj = context.get("competition", {})
    gender = competition_obj.get("gender", "men")

    # Venue
    venue = sport_event.get("venue", {})

    # Mode (best_of)
    mode = context.get("mode", {})
    best_of = mode.get("best_of", 3)

    match = {
        "id": sport_event.get("id", ""),
        "tournament": competition_name,
        "tournament_short": tournament_short,
        "round": round_name,
        "round_display": round_display_name(round_name),
        "is_qualification": is_qualification,
        "gender": gender,
        "category": category,
        "start_time": sport_event.get("start_time", ""),
        "start_time_confirmed": sport_event.get("start_time_confirmed", False),
        "status": status,
        "match_status": sport_event_status.get("match_status", ""),
        "best_of": best_of,
        "players": players,
    }

    if venue:
        match["venue"] = venue.get("name", "")
        match["city"] = venue.get("city_name", "")
        match["country"] = venue.get("country_name", "")
        match["timezone"] = venue.get("timezone", "")

    if scores:
        match["scores"] = scores

    if sport_event_status.get("winner_id"):
        match["winner_id"] = sport_event_status["winner_id"]

    return match


def fetch_grand_slam_matches():
    """Получает все матчи Большого шлема за указанный период."""
    all_matches = []
    today = datetime.now(timezone.utc)

    # Проверяем каждый день в диапазоне
    for day_offset in range(-DAYS_BACK, DAYS_FORWARD + 1):
        check_date = today + timedelta(days=day_offset)
        date_str = check_date.strftime("%Y-%m-%d")

        print(f"  Проверка расписания на {date_str}...")

        data = api_get(f"/schedules/{date_str}/summaries")
        if not data or "summaries" not in data:
            time.sleep(REQUEST_DELAY)
            continue

        summaries = data["summaries"]
        print(f"    Найдено матчей: {len(summaries)}")

        for summary in summaries:
            context = summary.get("sport_event", {}).get("sport_event_context", {})
            competition = context.get("competition", {})
            comp_id = competition.get("id", "")

            # Проверяем, турнир Большого шлема ли это
            if comp_id in GRAND_SLAM_COMPETITIONS:
                match = normalize_match(summary, GRAND_SLAM_COMPETITIONS[comp_id])
                # Дедупликация
                if match["id"] and match["id"] not in [m["id"] for m in all_matches]:
                    all_matches.append(match)

        time.sleep(REQUEST_DELAY)

    return all_matches


def separate_matches(matches):
    """Разделяет матчи на основные (QF/SF/F) и второстепенные."""
    main_matches = []
    secondary_matches = []

    for match in matches:
        # Пропускаем квалификацию
        if match.get("is_qualification"):
            continue

        if match["round"] in MAIN_ROUNDS:
            main_matches.append(match)
        else:
            secondary_matches.append(match)

    return main_matches, secondary_matches


def main():
    print("=" * 50)
    print("  Grand Slam Calendar - Обновление данных")
    print("=" * 50)
    print()

    # Загружаем существующие данные (если есть)
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "matches.json")
    output_path = os.path.abspath(output_path)

    existing_data = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except:
            pass

    # Получаем свежие данные
    print("Получение данных о матчах Большого шлема...")
    matches = fetch_grand_slam_matches()
    print(f"\nВсего найдено матчей Большого шлема: {len(matches)}")

    # Разделяем на основные и второстепенные
    main_matches, secondary_matches = separate_matches(matches)
    print(f"  Основные матчи (1/4+): {len(main_matches)}")
    print(f"  Второстепенные матчи: {len(secondary_matches)}")

    # Объединяем с существующими данными (чтобы не потерять завершённые матчи)
    # Если новых матчей не найдено, сохраняем старые
    if not matches and existing_data:
        print("\nНовых матчей не найдено. Сохраняю существующие данные.")
        output_data = existing_data
    else:
        output_data = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "main_matches": main_matches,
            "secondary_matches": secondary_matches,
        }

    # Сохраняем
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\nДанные сохранены в {output_path}")
    print(f"Последнее обновление: {output_data['last_updated']}")
    print("\nГотово!")


if __name__ == "__main__":
    main()
