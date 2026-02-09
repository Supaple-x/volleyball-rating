# Инструкции для Claude Code

## Быстрый старт

Это парсер сайта volleymsk.ru для сбора статистики любительского волейбола в Москве.
Проект развёрнут на сервере и доступен по адресу https://volleymsk.duckdns.org

### Ключевые файлы:
1. `src/parser/match_parser.py` - парсинг матчей (составы, счёт, судьи)
2. `src/parser/roster_parser.py` - парсинг страниц составов (members.php)
3. `src/parser/base_parser.py` - базовый парсер с RATE_LIMIT (50ms)
4. `src/database/models.py` - структура БД (SQLAlchemy)
5. `src/services/data_service.py` - сохранение данных
6. `src/services/parsing_service.py` - фоновый парсинг с threading
7. `src/web/app.py` - Flask API + веб-интерфейс
8. `src/web/templates/index.html` - SPA фронтенд (Tailwind CSS, тёмная тема)

### Запуск:
```bash
# Веб-сервер (локально)
python run.py web
# http://127.0.0.1:5000

# Тест парсера
python test_parser.py 42131
```

## Текущее состояние (10.02.2026)

### Что работает:
- Парсинг матчей с составами и фото игроков
- Полностью переработанный тёмный SPA-интерфейс (Tailwind CSS + Inter + Material Icons)
- 6 страниц: Dashboard, Матчи, Команды, Игроки, Судьи, Парсинг
- Детальные модальные окна для матчей/команд/игроков/судей
- Поиск по командам, игрокам, судьям, матчам (debounce 300ms)
- Пагинация на матчах и игроках
- Парсинг из веб-интерфейса с прогрессбаром, паузой и остановкой
- Деплой на сервере с SSL (Let's Encrypt)
- Лучшие игроки матча (поиск по имени, fallback на текст)
- Судьи: кол-во матчей и средний рейтинг в таблице + профиль при клике + тултип при наведении
- Интерактивный график динамики матчей (фильтр по годам, тултипы)
- Топ игроков по MVP на дашборде, кол-во матчей и MVP в карточках
- Поиск по матчам (по названию команды)
- Ссылка на источник (volleymsk.ru) в деталях матча

### База данных:
- SQLite: `data/volleyball.db`
- ~15000 матчей, ~7000 игроков, ~500 команд, ~1700 судей
- Задержка парсинга: 50ms (RATE_LIMIT в base_parser.py)

### Известные проблемы:
- Исторические названия команд не отслеживаются (отображается текущее название)
- Нет страницы сравнения игроков/команд

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
# Перезапуск сервиса
sudo systemctl restart volleyball-rating

# Логи
sudo journalctl -u volleyball-rating -f

# Обновить код (после scp)
sudo systemctl restart volleyball-rating

# Деплой с локальной машины (Windows)
scp -i ~/.ssh/russia_vps_key src/web/templates/index.html artemfcsm@176.108.251.49:/opt/volleyball-rating/src/web/templates/index.html
scp -i ~/.ssh/russia_vps_key src/web/app.py artemfcsm@176.108.251.49:/opt/volleyball-rating/src/web/app.py
# и перезапуск:
ssh -i ~/.ssh/russia_vps_key artemfcsm@176.108.251.49 "sudo systemctl restart volleyball-rating"
```

### Локальная разработка
- Windows: c:\Dev\volleyball-rating
- Веб: http://127.0.0.1:5000

## API эндпоинты

### Списки (с поиском)
- `GET /api/matches?page=1&per_page=20&search=` - список матчей (поиск по команде)
- `GET /api/teams?search=` - команды с поиском
- `GET /api/players?page=1&per_page=50&search=&sort=mvp` - игроки с поиском (sort: mvp/name)
- `GET /api/referees?search=` - судьи с поиском (match_count, avg_rating)

### Детальная информация
- `GET /api/matches/<id>` - матч с составами и лучшими игроками
- `GET /api/teams/<id>` - команда со статистикой, игроками, матчами
- `GET /api/players/<id>` - игрок с полной статистикой, историей матчей, судейством
- `GET /api/referees/<id>` - судья с историей матчей и распределением рейтингов

### Статистика
- `GET /api/stats/monthly` - количество матчей по месяцам (для графика)

### Парсинг
- `POST /api/parse/matches` - запустить парсинг матчей
- `POST /api/parse/rosters` - запустить парсинг составов
- `POST /api/parse/pause` - пауза
- `POST /api/parse/resume` - продолжить
- `POST /api/parse/stop` - остановить

## Особенности HTML volleymsk.ru

### Важно
- Кодировка сайта: **windows-1251**
- Ссылок player.php на страницах матча и состава НЕТ
- ID игроков извлекаются из URL картинок: `/uploads/player/t/{ID}.PNG`
- Фото URL: `https://volleymsk.ru/uploads/player/t/{ID}.{ext}`

### Страница матча (match.php)
- Таблица с bgcolor="#CCCCCC" содержит основную информацию
- Турнирный путь, дата, результат, судья, оценки, лучшие игроки
- Вторая таблица - составы команд с фото игроков

### Страница состава (members.php)
- ID игрока в URL фото
- Имя в `<strong>` тегах (Фамилия<br>Имя<br>Отчество)
- Рост: "Рост: 185", Год: "Год рожд: 1986"

## Модели данных

### Player
- site_id, first_name, last_name, patronymic
- height, position, birth_year, photo_url

### Match
- site_id, date_time, home_team_id, away_team_id
- home_score, away_score, set_scores
- referee_id, referee_rating_home/away, referee_rating_home/away_text
- tournament_path, status

### BestPlayer
- match_id, player_id (nullable!), team_id
- player_name (fallback если игрок не найден)

## Фронтенд (SPA)

Весь фронтенд — один файл `src/web/templates/index.html`:
- **Tailwind CSS** через CDN + кастомные цвета:
  - primary: #6366f1 (indigo), bg-dark: #0f1117, surface: #1a1d28, input-bg: #252836
- **Material Symbols Outlined** — иконки
- **Inter** — шрифт
- Hash-based navigation (`#dashboard`, `#matches`, `#teams`, `#players`, `#referees`, `#parsing`)
- `pageLoaders` — маппинг страниц на функции загрузки данных
- `api(url)` — обёртка fetch для API вызовов
- `setupSearch(inputId, loaderFn)` — debounce поиск 300ms
- Модальные окна для детальной информации (матчи, игроки, команды, судьи)
- Интерактивный SVG график динамики матчей с фильтром по годам
- Тултипы при наведении на судей (последние 5 матчей) с кешированием

## Дизайн-макеты (Stitch)

Макеты сгенерированы через Google Stitch MCP и лежат в `stitch_designs/`:
- `stitch_dashboard.html` — Dashboard
- `matches.html` — Список матчей
- `players.html` — Каталог игроков
- `teams.html` — Каталог команд
- `referees.html` — Рейтинг судей
- `parsing.html` — Управление парсингом

Stitch проект ID: `7337845422571308408`

## Зависимости
```
Python 3.10+
Flask
SQLAlchemy
BeautifulSoup4
lxml
requests
```

## Типичные задачи

### Отладка парсинга:
```bash
python debug_html.py 42131  # Сохранит HTML
```

### Перепарсить матчи:
В веб-интерфейсе снять галочку "Пропускать существующие" и запустить.

### Деплой изменений на сервер:
```bash
# С Windows на сервер
scp -i ~/.ssh/russia_vps_key <файл> artemfcsm@176.108.251.49:/opt/volleyball-rating/<файл>
ssh -i ~/.ssh/russia_vps_key artemfcsm@176.108.251.49 "sudo systemctl restart volleyball-rating"
```
