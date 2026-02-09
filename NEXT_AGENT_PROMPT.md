# Задача для следующего агента

## Контекст
Проект volleyball-rating — парсер и аналитика volleymsk.ru для любительского волейбола в Москве.
Развёрнут на https://volleymsk.duckdns.org (сервер 176.108.251.49).
GitHub: https://github.com/Supaple-x/volleyball-rating

Прочитай `CLAUDE.md` для полной документации проекта.

## Текущее состояние

Всё работает и задеплоено:
- Парсинг ~15000 матчей с volleymsk.ru
- SPA фронтенд с тёмной темой (Dashboard, Матчи, Команды, Игроки, Судьи, Парсинг)
- Детальные профили: матчи, игроки, команды, судьи
- Поиск по всем сущностям
- Интерактивный график динамики матчей с фильтром по годам
- Топ игроков по MVP, судей по кол-ву матчей

## ЗАДАЧА: Парсинг из нового источника

Пользователь укажет новый источник данных для парсинга. Детали задачи будут предоставлены в начале сессии.

### Архитектура парсера (для справки)

Текущая архитектура парсинга:
```
src/parser/
├── base_parser.py      # BaseParser: fetch_page(), RATE_LIMIT, clean_text(), parse_name()
├── match_parser.py     # MatchParser(BaseParser): parse_match(id) → dict
├── roster_parser.py    # RosterParser(BaseParser): parse_roster(id) → dict
└── tournament_parser.py # TournamentParser(BaseParser)
```

- `BaseParser` — общая логика: HTTP-запросы (requests + BeautifulSoup), RATE_LIMIT 50ms, кодировка windows-1251
- Каждый парсер наследует BaseParser и реализует специфичную логику
- `DataService` (`src/services/data_service.py`) — сохраняет данные в SQLite через SQLAlchemy
- `ParsingService` (`src/services/parsing_service.py`) — фоновый парсинг с threading, прогрессбар

### При добавлении нового источника:
1. Изучи структуру нового сайта (кодировка, HTML-структура, API)
2. Создай новый парсер в `src/parser/` наследуя от BaseParser (или создай новый базовый)
3. Обнови модели в `src/database/models.py` если нужны новые поля
4. Обнови `DataService` для сохранения новых данных
5. Добавь API эндпоинты в `src/web/app.py`
6. Обнови фронтенд в `src/web/templates/index.html`
7. Протестируй локально (python run.py web → http://127.0.0.1:5000)
8. Задеплой на сервер (scp + systemctl restart)

### Деплой
```bash
# С Windows на сервер
scp -i ~/.ssh/russia_vps_key <файл> artemfcsm@176.108.251.49:/opt/volleyball-rating/<файл>
ssh -i ~/.ssh/russia_vps_key artemfcsm@176.108.251.49 "sudo systemctl restart volleyball-rating"
```

### Нерешённые проблемы (низкий приоритет)
1. Исторические названия команд не отслеживаются (показывается текущее название)
2. Нет страницы сравнения игроков/команд
