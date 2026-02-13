# Инструкции для Claude Code

## Быстрый старт

Агрегатор статистики любительского волейбола из двух источников:
1. **VolleyMSK** — volleymsk.ru (любительские турниры Москвы)
2. **ЛЧБ** — volleyball.businesschampions.ru (Лига Чемпионов Бизнеса, корпоративный волейбол)

Проект развёрнут на сервере: https://volleymsk.duckdns.org

### Архитектура проекта:
```
src/
├── database/
│   ├── db.py              # Database class (SQLite + SQLAlchemy)
│   └── models.py          # Все модели: VM (Match, Player, Team, Referee, BestPlayer)
│                          #              BC (BCSeason, BCMatch, BCTeam, BCPlayer,
│                          #                  BCReferee, BCBestPlayer, BCMatchPlayerStats, ...)
├── parser/                # Парсеры VolleyMSK (windows-1251, HTML scraping)
│   ├── base_parser.py     # RATE_LIMIT 50ms
│   ├── match_parser.py    # match.php → составы, счёт, судьи, лучшие игроки
│   └── roster_parser.py   # members.php → детали игроков (рост, год, фото)
├── parser_bc/             # Парсеры ЛЧБ (utf-8, структурированный HTML)
│   ├── base_parser.py     # BASE_URL = volleyball.businesschampions.ru
│   ├── season_parser.py   # Имя сезона из навигационного дропдауна (НЕ из <title>!)
│   ├── schedule_parser.py # Расписание: championship + cup
│   ├── match_parser.py    # Детали матча + составы + статистика игроков
│   ├── team_parser.py     # Список команд сезона
│   ├── player_parser.py   # Детали игрока (фото, рост, вес, позиция)
│   └── referee_parser.py  # Список судей сезона
├── services/
│   ├── data_service.py        # CRUD для VM данных
│   ├── bc_data_service.py     # CRUD для BC данных (с дедупликацией игроков по ФИО+дата рождения)
│   ├── parsing_service.py     # Фоновый парсинг VM с threading (pause/resume/stop)
│   ├── bc_parsing_service.py  # Фоновый парсинг BC (5 шагов: schedule→teams→matches→players→referees)
│   └── scheduler.py           # AutoUpdater — демон автообновления (раз в час)
└── web/
    ├── app.py                 # Flask API (register_routes + register_bc_routes)
    └── templates/
        └── index.html         # SPA фронтенд (единый файл, Tailwind CSS)
```

### Запуск:
```bash
python run.py web              # http://127.0.0.1:5000
python run.py web --port 8080  # Production
python test_parser.py 42131    # Тест парсинга одного матча
```

## Текущее состояние (13.02.2026)

### Что работает:
- **Два источника** с переключателем (VolleyMSK / Champions) в сайдбаре
- SPA на одной HTML-странице (12 страниц: по 6 для каждого источника)
- Дашборд с графиком динамики, топ-игроками (MVP), топ-судьями, KPI-карточками
- Детальные модалки для матчей/команд/игроков/судей с кликабельными фото (полноэкранный оверлей)
- Поиск, сортировка (MVP, очки, атаки, подачи, блоки), пагинация
- Парсинг из веб-интерфейса с прогрессбарами, паузой, остановкой
- **Автообновление** — демон проверяет оба источника раз в час
- Ссылки на источники (volleymsk.ru / businesschampions.ru) в деталях матчей и команд
- Дедупликация игроков ЛЧБ при парсинге (по ФИО + дата рождения)

### База данных:
- SQLite: `data/volleyball.db`
- **VolleyMSK**: ~36600 матчей (site_id 1..43977), ~7000 игроков, ~500 команд, ~1700 судей
- **ЛЧБ**: ~7000 матчей (30 сезонов: Весна 2011 — Осень 2025), ~6100 игроков, ~600 команд

### Автообновление (scheduler.py → AutoUpdater):
- Запускается автоматически при старте Flask-приложения
- **VolleyMSK**: ищет новые match_id после текущего max, останавливается после 50 пустых
- **ЛЧБ**: проверяет расписание текущего сезона + детектит новый сезон по имени
- Статус: `GET /api/autoupdate/status`
- Интервал: 3600 секунд (константа CHECK_INTERVAL в scheduler.py)

### Известные нюансы:
- Тег `<title>` на BC сайте содержит "настольный теннис" — это баг сайта, имя сезона берётся из навигационного дропдауна (`season_parser.py`)
- На BC сайте один игрок может иметь несколько site_id (при смене команды) — дедупликация по ФИО+дата рождения в `bc_data_service.py`, скрипт `merge_bc_duplicates.py` для разовой очистки
- Для несуществующих сезонов BC сайт отдаёт страницу текущего сезона — проверяем по имени сезона
- VolleyMSK: 13000+ site_id не имеют матчей (пустые страницы на сайте)

## Сервер (Production)

### Подключение:
```bash
ssh -i ~/.ssh/russia_vps_key artemfcsm@176.108.251.49
```

### Расположение:
- Проект: `/opt/volleyball-rating/`
- Venv: `/opt/volleyball-rating/venv/`
- БД: `/opt/volleyball-rating/data/volleyball.db`

### Сервисы:
- **systemd**: `volleyball-rating` (ExecStart: venv/bin/python run.py web --host 127.0.0.1 --port 8080)
- **nginx**: reverse proxy volleymsk.duckdns.org → 127.0.0.1:8080
- **SSL**: Let's Encrypt (certbot), expires 2026-05-06

### Типичные команды на сервере:
```bash
sudo systemctl restart volleyball-rating
sudo journalctl -u volleyball-rating -f
sudo journalctl -u volleyball-rating --since '1 hour ago' | grep 'update:'  # Проверить автообновление
```

### Деплой с локальной машины (Windows):
```bash
scp -i ~/.ssh/russia_vps_key <файл> artemfcsm@176.108.251.49:/opt/volleyball-rating/<файл>
ssh -i ~/.ssh/russia_vps_key artemfcsm@176.108.251.49 "sudo systemctl restart volleyball-rating"
```

### Локальная разработка:
- Windows: `c:\Dev\volleyball-rating`
- Веб: http://127.0.0.1:5000

## API эндпоинты

### VolleyMSK
| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/matches?page=1&per_page=20&search=` | Матчи (поиск по команде) |
| GET | `/api/teams?search=` | Команды |
| GET | `/api/players?page=1&per_page=50&search=&sort=mvp` | Игроки (sort: mvp/name) |
| GET | `/api/referees?search=` | Судьи (match_count, avg_rating) |
| GET | `/api/matches/<id>` | Детали матча |
| GET | `/api/teams/<id>` | Детали команды |
| GET | `/api/players/<id>` | Детали игрока |
| GET | `/api/referees/<id>` | Детали судьи |
| GET | `/api/stats/monthly` | Данные для графика |
| POST | `/api/parse/matches` | Запуск парсинга |
| POST | `/api/parse/rosters` | Парсинг составов |
| POST | `/api/parse/pause\|resume\|stop` | Управление |

### ЛЧБ (Business Champions)
| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/bc/matches?page=1&per_page=20&search=` | Матчи |
| GET | `/api/bc/teams?search=` | Команды |
| GET | `/api/bc/players?page=1&per_page=50&search=&sort=mvp` | Игроки (sort: mvp/matches/points/attacks/serves/blocks/name) |
| GET | `/api/bc/referees?search=` | Судьи |
| GET | `/api/bc/matches/<id>` | Детали матча (с season_num для ссылки на источник) |
| GET | `/api/bc/teams/<id>` | Детали команды (seasons[], roster[]) |
| GET | `/api/bc/players/<id>` | Детали игрока (teams[], matches[] со score) |
| GET | `/api/bc/referees/<id>` | Детали судьи |
| GET | `/api/bc/stats` | Общая статистика |
| GET | `/api/bc/stats/monthly` | Данные для графика |
| POST | `/api/bc/parse/season` | Парсинг сезона (body: season_num, mode, skip_existing) |
| POST | `/api/bc/parse/pause\|resume\|stop` | Управление |

### Общие
| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/autoupdate/status` | Статус автообновления (last_run, last_vm_result, last_bc_result) |

## Модели данных (models.py)

### VolleyMSK модели:
- **Player**: site_id, first_name, last_name, patronymic, height, position, birth_year, photo_url
- **Team**: site_id, name
- **Match**: site_id, date_time, home/away_team_id, home/away_score, set_scores, referee_id, referee_rating_*, tournament_path, status
- **BestPlayer**: match_id, player_id (nullable!), team_id, player_name (fallback)
- **Referee**: site_id, full_name

### ЛЧБ модели (префикс BC):
- **BCSeason**: number, name (e.g. "Осень 2025")
- **BCTeam**: site_id, name, logo_url, is_women
- **BCPlayer**: site_id, first_name, last_name, birth_date, height, weight, position, photo_url
- **BCReferee**: site_id, first_name, last_name, photo_url
- **BCMatch**: site_id, season_id, date_time, home/away_team_id, home/away_score, set_scores, referee_id, division_name, round_name, venue, tournament_type
- **BCBestPlayer**: match_id, player_id (nullable), team_id, player_name
- **BCMatchPlayerStats**: match_id, player_id, team_id, points, attacks, serves, blocks

## Фронтенд (SPA)

Весь фронтенд — один файл `src/web/templates/index.html`:
- **Tailwind CSS** через CDN + кастомные цвета:
  - primary: #6366f1 (indigo), bg-dark: #0f1117, surface: #1a1d28, input-bg: #252836
- **Material Symbols Outlined** — иконки
- **Inter** — шрифт
- Переключатель источника: `switchSource('volleymsk'|'bc')` — показывает/скрывает соответствующие пункты меню
- Hash-based navigation: `#dashboard`, `#matches`, `#teams`, `#players`, `#referees`, `#parsing`, `#bc-dashboard`, `#bc-matches`, `#bc-teams`, `#bc-players`, `#bc-referees`, `#bc-parsing`
- `pageLoaders` — маппинг всех 12 страниц на функции загрузки данных
- `api(url)` — обёртка fetch для API вызовов
- `setupSearch(inputId, loaderFn)` — debounce поиск 300ms
- Модальные окна: `showMatchDetail`, `showPlayerDetail`, `showTeamDetail`, `showRefereeDetail` + BC-версии (`showBcMatchDetail`, ...)
- `showPhoto(url)` — полноэкранный оверлей фото (`#photo-overlay`)
- SVG-графики: `renderChart()` / `renderBcChart()` — интерактивные с тултипами и фильтром по годам
- Тултипы судей (VM): кеширование через `refTooltipCache`
- BC-сортировка игроков: `setBcPlayersSort(field)` — mvp/matches/points/attacks/serves/blocks

## Утилитарные скрипты:
- `backfill_volleymsk.py` — разовое заполнение пробелов VM (пропущенные site_id)
- `merge_bc_duplicates.py` — объединение дублей BC игроков (по ФИО + дата рождения)
- `migrate_team_gender.py` — миграция поля is_women для BC команд
- `debug_html.py` — сохранение HTML страницы матча для отладки

## Особенности HTML источников

### volleymsk.ru:
- Кодировка: **windows-1251**
- Ссылок player.php на страницах НЕТ
- ID игроков из URL картинок: `/uploads/player/t/{ID}.PNG`
- Фото URL: `https://volleymsk.ru/uploads/player/t/{ID}.{ext}`
- Максимальный match_id: ~43977 (февраль 2026)

### volleyball.businesschampions.ru:
- Мультиспортивный сайт (волейбол, футбол, теннис и т.д.)
- **ВАЖНО**: `<title>` страницы содержит "настольный теннис" — это баг сайта, НЕ использовать
- Имена сезонов — из навигационного дропдауна: `<a href="/season-N">Осень 2025</a>`
- Для несуществующих сезонов отдаёт страницу текущего → проверяем по имени
- Один игрок может иметь несколько профилей (site_id) при смене команды
- Ссылка на матч: `https://volleyball.businesschampions.ru/season-{N}/matches/{ID}`
- Ссылка на команду: `https://volleyball.businesschampions.ru/season-{N}/teams/{ID}`

## Зависимости
```
Python 3.10+
Flask
SQLAlchemy
BeautifulSoup4
lxml
requests
```
