# Задача для следующего агента

## Контекст
Проект volleyball-rating — парсер и аналитика volleymsk.ru для любительского волейбола в Москве.
Развёрнут на https://volleymsk.duckdns.org (сервер 176.108.251.49).

Прочитай `CLAUDE.md` для полной документации проекта.

## ЗАДАЧА: Исправить список судей — добавить количество матчей и средний рейтинг

### Проблема
На странице "Судьи" (вкладка Referees) в таблице есть колонки "Матчей" и "Рейтинг", но они показывают "-" вместо реальных данных.

### Причина
API эндпоинт `GET /api/referees` (файл `src/web/app.py`, строка ~221) возвращает только `{id, full_name}` для каждого судьи. Не считает количество матчей и средний рейтинг.

### Что нужно сделать

#### 1. Бэкенд: обогатить `/api/referees` (src/web/app.py)
Для каждого судьи добавить:
- `match_count` — количество матчей, где `Match.referee_id == referee.id`
- `avg_rating` — средняя оценка из `Match.referee_rating_home` и `Match.referee_rating_away` (оба поля nullable, брать только не-null значения)

**Текущий код** (`src/web/app.py:221-240`):
```python
@app.route('/api/referees')
def api_referees():
    from src.database.models import Referee
    from sqlalchemy import or_

    search = request.args.get('search', '').strip()
    with db.session() as session:
        query = session.query(Referee)
        if search:
            query = query.filter(or_(
                Referee.last_name.ilike(f'%{search}%'),
                Referee.first_name.ilike(f'%{search}%'),
                Referee.patronymic.ilike(f'%{search}%')
            ))
        referees = query.order_by(Referee.last_name).all()
        result = [{'id': r.id, 'full_name': r.full_name} for r in referees]
    return jsonify({'referees': result, 'total': len(result)})
```

**Подсказка по реализации**:
Используй SQLAlchemy subquery или join с Match для подсчёта. Пример подхода:
```python
from sqlalchemy import func, case
# Subquery для подсчёта матчей и рейтинга по каждому referee
match_stats = session.query(
    Match.referee_id,
    func.count(Match.id).label('match_count'),
    func.avg(
        # Среднее из home и away рейтингов (оба nullable)
    ).label('avg_rating')
).group_by(Match.referee_id).subquery()
```

Важно: Match.referee_rating_home и Match.referee_rating_away — это Integer, nullable. Один матч может давать 0, 1 или 2 оценки. Средний рейтинг нужно считать по всем не-null оценкам.

#### 2. Фронтенд: отобразить данные (src/web/templates/index.html)

**Текущий код** (строка ~368-372):
```javascript
async function loadReferees() {
    const search = document.getElementById('referees-search')?.value || '';
    const data = await api(search ? `/api/referees?search=${encodeURIComponent(search)}` : '/api/referees');
    document.getElementById('referees-tbody').innerHTML = data.referees.map((r, i) => {
        ...
        return `<tr>...<td>-</td><td>-</td></tr>`;
    }).join('');
}
```

Заменить `-` на `r.match_count` и `r.avg_rating` (округлённый до 1 знака).

#### 3. Dashboard: обновить таблицу топ-судей
На дашборде тоже есть таблица судей (строка ~318-319) — добавить туда match_count и avg_rating, и отсортировать по кол-ву матчей или рейтингу.

### Модели данных (справка)

```python
# src/database/models.py
class Match:
    referee_id: Optional[int]  # FK на referees.id
    referee_rating_home: Optional[int]  # Оценка от хозяев (1-5)
    referee_rating_away: Optional[int]  # Оценка от гостей (1-5)

class Referee:
    id, last_name, first_name, patronymic
    matches: List[Match]  # relationship
```

### Деплой
После внесения изменений:
```bash
# С Windows
scp -i ~/.ssh/russia_vps_key src/web/app.py artemfcsm@176.108.251.49:/opt/volleyball-rating/src/web/app.py
scp -i ~/.ssh/russia_vps_key src/web/templates/index.html artemfcsm@176.108.251.49:/opt/volleyball-rating/src/web/templates/index.html
ssh -i ~/.ssh/russia_vps_key artemfcsm@176.108.251.49 "sudo systemctl restart volleyball-rating"
```

### Проверка
1. Открой https://volleymsk.duckdns.org -> вкладка "Судьи"
2. Убедись что колонки "Матчей" и "Рейтинг" показывают числа, а не "-"
3. Поиск должен продолжать работать
4. На дашборде топ-судьи тоже должны показывать статистику
