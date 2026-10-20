# 🎾 Большой шлем и не только

Живой календарь турниров: **Большой шлем**, **Masters 1000 (ATP)** и **WTA 1000** — расписание, результаты, live-счёт и текущий рейтинг игроков. Данные обновляются автоматически через GitHub Actions.

🌐 **Сайт:** https://nikstopka.github.io/grand-slam-calendar/
📦 **Репозиторий:** https://github.com/nikstopka/grand-slam-calendar

## Возможности

- **Вкладка на каждый турнир** — Australian Open, Roland Garros, Wimbledon, US Open, Indian Wells, Miami, Мадрид, Рим, Торонто, Цинциннати, Шанхай, Париж, Доха, Дубай, Пекин и другие
- **Вкладка «Рейтинг»** — актуальный мировой рейтинг ATP и WTA с очками и изменением позиции
- **Разделение по годам** — прошлые сезоны с результатами и предстоящие матчи
- **Мужчины / женщины / все** — фильтр по категории внутри любого турнира
- **Основные и второстепенные матчи** — четвертьфиналы, полуфиналы и финалы отдельно от ранних раундов
- **До матча** — соперники, время, корт и обратный отсчёт
- **Во время матча** — индикатор LIVE и текущий счёт по сетам
- **После матча** — итоговый счёт и победитель
- **Фотографии игроков** — из Images API, с автоматической заменой на инициалы, если фото недоступно
- **Адаптивный дизайн** — работает на телефоне и компьютере

## Что вам понадобится

1. **Аккаунт GitHub** (бесплатный) — [github.com](https://github.com)
2. **API ключ Sportradar** (бесплатный) — [developer.sportradar.com](https://developer.sportradar.com/)

---

## Как всё устроено

```
┌──────────────────────────────────────────────────────────┐
│                    GitHub Actions                         │
│              (запускается каждые 6 часов)                  │
│                                                          │
│  fetch_tennis.py → Sportradar Tennis API v3 → data/      │
│         ↕ кэш (каталог, сезоны, фотографии)              │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│                    GitHub Pages                           │
│                                                          │
│  index.html + app.js → data/index.json (список турниров)  │
│                      → data/tournaments/*.json (сетки)    │
│                      → data/rankings.json (рейтинг)       │
│                      → data/players.json (фото)           │
└──────────────────────────────────────────────────────────┘
```

Каждый турнир лежит в **отдельном файле** и подгружается только при переключении на его вкладку — поэтому страница открывается мгновенно и не весит десятки мегабайт.

### Файлы проекта

```
grand-slam-calendar/
├── index.html
├── styles.css
├── app.js
├── .gitignore
├── data/
│   ├── index.json              ← список турниров и счётчики
│   ├── rankings.json           ← мировой рейтинг ATP и WTA
│   ├── players.json            ← фотографии игроков
│   ├── tournaments/            ← сетки матчей по турнирам
│   │   ├── australian-open.json
│   │   ├── shanghai.json
│   │   └── …
│   └── sample/                 ← демо-данные (см. ниже)
├── scripts/
│   └── fetch_tennis.py
└── .github/
    └── workflows/
        └── update-schedule.yml
```

---

## Установка

### Шаг 1. Создание репозитория

1. На GitHub нажмите **New repository**
2. Имя: `grand-slam-calendar`, видимость: **Public**
3. Нажмите **Create repository**

### Шаг 2. Загрузка файлов

Склонируйте репозиторий и скопируйте в него содержимое проекта (включая скрытые папки `.github` и `.gitignore`):

```bash
git clone https://github.com/ВАШ_НИК/grand-slam-calendar.git
cd grand-slam-calendar
# копируем содержимое проекта (Windows: robocopy путь\к\проекту . /E)
# Linux/macOS: cp -r путь/к/проекту/. .

git add .
git commit -m "Загрузка файлов проекта"
git push
```

Или загрузите файлы через веб-интерфейс (**Add file → Upload files**), перетащив **содержимое** папки проекта, а не саму папку.

### Шаг 3. API ключ Sportradar

1. Откройте [developer.sportradar.com](https://developer.sportradar.com/) и зарегистрируйтесь
2. Создайте приложение с продуктом **Tennis v3 (Trial)**
3. Скопируйте ключ

### Шаг 4. Секрет в GitHub

**Settings → Secrets and variables → Actions → New repository secret**:

- Name: `SPORTRADAR_API_KEY`
- Secret: ваш ключ

### Шаг 5. GitHub Pages

**Settings → Pages → Build and deployment**:

- Source: **Deploy from a branch**
- Branch: `main`, папка `/ (root)`

### Шаг 6. Запуск

**Actions → «Обновление расписания турниров» → Run workflow → Run workflow**.

Через 1–2 минуты данные появятся на сайте, ещё через 1–2 минуты обновится сам сайт.

---

## Источники данных

Всё берётся из одного тарифа Sportradar Tennis API v3:

| Данные | Запрос | Частота |
|---|---|---|
| Каталог турниров (уровень, пол, группа) | `/competitions.json` | раз в неделю (кэш) |
| Сезоны турниров | `/seasons.json` | раз в неделю (кэш) |
| Сетка матчей сезона + результаты | `/seasons/{id}/summaries.json` | идущие сезоны — каждый запуск, завершённые — навсегда |
| Мировой рейтинг | `/rankings.json` | раз в сутки |
| Фотографии игроков | `/tennis-images-t3/…/manifest.json` | раз в месяц (кэш) |

Каталог турниров **не зашит в код**: скрипт берёт из API поле `level` (`grand_slam`, `atp_1000`, `wta_1000`) и группирует мужские и женские розыгрыши по `parent_id`. Новый турнир в календаре появится сам.

### Расход лимита

Бесплатный тариф — **1000 запросов в месяц**. Скрипт кэширует всё, что меняется редко, поэтому укладывается в лимит:

| Что | Запросов в сутки |
|---|---|
| Идущие сезоны (2–4 турнира) | ~8–16 |
| Будущие сезоны (перепроверка раз в 2 дня) | ~5 |
| Рейтинг | 1 |
| **Итого** | **~20 в сутки, ~600 в месяц** |

Кэш лежит в каталоге `.cache/` и восстанавливается через `actions/cache`. Он не попадает в репозиторий.

### Фотографии игроков

Фото берутся из **Images API** Sportradar (`tennis-images-t3`). Если этот продукт не входит в ваш тариф, скрипт не сломается — вместо фотографии автоматически показывается круглая заглушка с инициалами и флагом страны.

---

## Демо-данные

В каталоге `data/sample/` лежит демонстрационный набор (турниры, годы, рейтинг). Чтобы посмотреть сайт без API-ключа, скопируйте его содержимое на место боевых данных:

```bash
# Linux/macOS
cp data/sample/index.json data/index.json
cp data/sample/rankings.json data/rankings.json
cp data/sample/players.json data/players.json
cp -r data/sample/tournaments/. data/tournaments/

# Windows PowerShell
Copy-Item data\sample\index.json data\index.json
Copy-Item data\sample\rankings.json data\rankings.json
Copy-Item data\sample\players.json data\players.json
Copy-Item data\sample\tournaments\* data\tournaments\ -Recurse
```

В боевом режиме эти файлы перезаписываются скриптом автоматически.

---

## Решение проблем

### Сайт не обновляется

1. Проверьте вкладку **Actions** — есть ли ошибки в последних запусках
2. Убедитесь, что секрет `SPORTRADAR_API_KEY` добавлен
3. Запустите workflow вручную

### Ошибка 403 или 429

- **401/403** — неверный ключ или исчерпан месячный лимит
- **429** — превышен лимит запросов. Уменьшите частоту в `.github/workflows/update-schedule.yml`:
  ```yaml
  - cron: '0 0,12 * * *'   # раз в 12 часов
  ```
  и поправьте `SCHEDULE_EVERY_HOURS` в `scripts/fetch_tennis.py` (значение `12`).
- Сбросить кэш: удалите каталог `.cache/` в репозитории Actions.

### Страница GitHub Pages не открывается

1. Settings → Pages — включена ли публикация
2. `index.html` должен лежать в корне репозитория
3. Подождите 5–10 минут

### Нет матчей на сайте

Это нормально вне турнирных периодов: расписание появляется за несколько дней до старта. Проверить API локально:

```bash
export SPORTRADAR_API_KEY=ваш_ключ      # Windows: $env:SPORTRADAR_API_KEY="ваш_ключ"
python scripts/fetch_tennis.py
```

### Нет фотографий игроков

Проверьте, что в вашем тарифе доступен **Images API** для тенниса. Без него календарь работает полностью — вместо фото показываются инициалы.

---

## Лицензия

MIT — свободное использование, изменение и распространение.

## Источник данных

[Sportradar Tennis API v3](https://developer.sportradar.com/) и [Images API](https://developer.sportradar.com/images-and-editorials/reference/images-overview).
