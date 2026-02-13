"""One-time migration: populate teams.gender from match tournament_path."""
import sqlite3
import sys


def migrate(db_path='data/volleyball.db'):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Add column if not exists
    columns = [row[1] for row in cur.execute("PRAGMA table_info(teams)")]
    if 'gender' not in columns:
        cur.execute("ALTER TABLE teams ADD COLUMN gender VARCHAR(10)")
        conn.commit()
        print("Added 'gender' column to teams table")
    else:
        print("Column 'gender' already exists")

    # For each team, determine gender from tournament_path
    teams = cur.execute("SELECT id, name FROM teams").fetchall()
    updated = 0
    male = 0
    female = 0

    for team_id, team_name in teams:
        paths = cur.execute("""
            SELECT DISTINCT tournament_path FROM matches
            WHERE (home_team_id = ? OR away_team_id = ?)
            AND tournament_path IS NOT NULL
        """, (team_id, team_id)).fetchall()

        has_male = any("мужской" in (p[0] or "").lower() for p in paths)
        has_female = any("женский" in (p[0] or "").lower() for p in paths)

        gender = None
        if has_male and not has_female:
            gender = "М"
            male += 1
        elif has_female and not has_male:
            gender = "Ж"
            female += 1

        cur.execute("UPDATE teams SET gender = ? WHERE id = ?", (gender, team_id))
        if gender:
            updated += 1

    conn.commit()
    conn.close()
    print(f"Updated {updated}/{len(teams)} teams (M: {male}, F: {female})")


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'data/volleyball.db'
    migrate(db_path)
