#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сбор новостей с ATP, WTA, Tennis.com и перевод на русский через Google Translate."""

import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_PATH = os.path.join(DATA_DIR, "news.json")


def translate_text(text: str) -> str:
    if not text or not text.strip():
        return text
    text = text.strip()
    # Ограничим длину, чтобы не словить лимиты
    if len(text) > 4500:
        text = text[:4500]
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "ru",
            "dt": "t",
            "q": text,
        }
        resp = requests.get(url, params=params, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data or not data[0]:
            return text
        parts = []
        for item in data[0]:
            if item and item[0]:
                parts.append(item[0])
        return "".join(parts) or text
    except Exception as e:
        print(f"translate error: {e}")
        return text


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_atp() -> list:
    items = []
    try:
        url = "https://www.atptour.com/en/news"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Ищем карточки новостей
        for card in soup.select("a[href*='/en/news/']"):
            href = card.get("href") or ""
            if not href or href.count("/en/news/") < 1:
                continue
            full_url = urljoin(url, href)
            # Пропустим некарточки
            title_el = card.select_one("h2, h3, .news-title, .title")
            if not title_el:
                # попробуем текст ссылки
                title_el = card
            title = clean_text(title_el.get_text(" ", strip=True))
            if not title or len(title) < 10:
                continue
            img_el = card.select_one("img")
            image = None
            if img_el:
                image = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src")
                if image:
                    image = urljoin(url, image)
            # избегаем дублей
            if any(it["url"] == full_url for it in items):
                continue
            items.append({
                "source": "ATP",
                "title_orig": title,
                "url": full_url,
                "image": image,
                "published_at": datetime.now(timezone.utc).isoformat(),
            })
            if len(items) >= 15:
                break
    except Exception as e:
        print(f"ATP fetch error: {e}")
    return items


def fetch_wta() -> list:
    items = []
    try:
        url = "https://www.wtatennis.com/news"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for card in soup.select("a[href*='/news/']"):
            href = card.get("href") or ""
            if "/news/" not in href:
                continue
            full_url = urljoin(url, href)
            title_el = card.select_one("h2, h3, .title, .news-card-title")
            if not title_el:
                title_el = card
            title = clean_text(title_el.get_text(" ", strip=True))
            if not title or len(title) < 10:
                continue
            img_el = card.select_one("img")
            image = None
            if img_el:
                image = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src")
                if image:
                    image = urljoin(url, image)
            if any(it["url"] == full_url for it in items):
                continue
            items.append({
                "source": "WTA",
                "title_orig": title,
                "url": full_url,
                "image": image,
                "published_at": datetime.now(timezone.utc).isoformat(),
            })
            if len(items) >= 15:
                break
    except Exception as e:
        print(f"WTA fetch error: {e}")
    return items


def fetch_tennis_com() -> list:
    items = []
    try:
        url = "https://www.tennis.com/news"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for card in soup.select("a[href*='/news/']"):
            href = card.get("href") or ""
            if "/news/" not in href:
                continue
            full_url = urljoin(url, href)
            title_el = card.select_one("h2, h3, .title, .headline")
            if not title_el:
                title_el = card
            title = clean_text(title_el.get_text(" ", strip=True))
            if not title or len(title) < 10:
                continue
            img_el = card.select_one("img")
            image = None
            if img_el:
                image = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src")
                if image:
                    image = urljoin(url, image)
            if any(it["url"] == full_url for it in items):
                continue
            items.append({
                "source": "Tennis.com",
                "title_orig": title,
                "url": full_url,
                "image": image,
                "published_at": datetime.now(timezone.utc).isoformat(),
            })
            if len(items) >= 15:
                break
    except Exception as e:
        print(f"Tennis.com fetch error: {e}")
    return items


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_items = []
    all_items.extend(fetch_atp())
    time.sleep(1)
    all_items.extend(fetch_wta())
    time.sleep(1)
    all_items.extend(fetch_tennis_com())

    # Удалим явные дубли по URL
    seen = set()
    unique = []
    for it in all_items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        unique.append(it)

    # Переведем заголовки на русский
    result = []
    for idx, it in enumerate(unique):
        title_ru = translate_text(it["title_orig"])
        result.append({
            "id": f"news_{int(time.time())}_{idx}",
            "source": it["source"],
            "title_orig": it["title_orig"],
            "title_ru": title_ru,
            "image": it.get("image"),
            "url": it["url"],
            "published_at": it.get("published_at") or datetime.now(timezone.utc).isoformat(),
        })
        time.sleep(0.4)  # небольшая пауза между переводами

    # Сортируем по свежести (как есть)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": result[:30],
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(payload['items'])} news items to {OUT_PATH}")


if __name__ == "__main__":
    main()
