"""SQLAlchemy models for volleyball database."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, Text, Boolean,
    create_engine, UniqueConstraint
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship
)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Season(Base):
    """Сезон (например, 2025-2026)."""
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)  # "2025-2026"
    start_year: Mapped[int] = mapped_column(Integer)
    end_year: Mapped[int] = mapped_column(Integer)

    # Relationships
    tournaments: Mapped[List["Tournament"]] = relationship(back_populates="season")

    def __repr__(self):
        return f"<Season {self.name}>"


class Tournament(Base):
    """Турнир (Регулярный турнир, Кубок и т.д.)."""
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    gender: Mapped[Optional[str]] = mapped_column(String(10))  # "М" / "Ж" / "mixed"
    season_id: Mapped[Optional[int]] = mapped_column(ForeignKey("seasons.id"))

    # Relationships
    season: Mapped[Optional["Season"]] = relationship(back_populates="tournaments")
    leagues: Mapped[List["League"]] = relationship(back_populates="tournament")

    def __repr__(self):
        return f"<Tournament {self.name}>"


class League(Base):
    """Лига (Суперлига, Высшая лига, Первая лига и т.д.)."""
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    level: Mapped[Optional[int]] = mapped_column(Integer)  # 1 = Суперлига, 2 = Высшая и т.д.
    tournament_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tournaments.id"))

    # Relationships
    tournament: Mapped[Optional["Tournament"]] = relationship(back_populates="leagues")
    rounds: Mapped[List["Round"]] = relationship(back_populates="league")

    def __repr__(self):
        return f"<League {self.name}>"


class Round(Base):
    """Круг/этап турнира (Круг 1, Круг 2, Плей-офф и т.д.)."""
    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    league_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leagues.id"))

    # Relationships
    league: Mapped[Optional["League"]] = relationship(back_populates="rounds")
    matches: Mapped[List["Match"]] = relationship(back_populates="round")

    def __repr__(self):
        return f"<Round {self.name}>"


class Team(Base):
    """Команда."""
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(Integer, unique=True)  # ID с сайта
    name: Mapped[str] = mapped_column(String(200))
    organization: Mapped[Optional[str]] = mapped_column(String(200))

    # Relationships
    home_matches: Mapped[List["Match"]] = relationship(
        back_populates="home_team", foreign_keys="Match.home_team_id"
    )
    away_matches: Mapped[List["Match"]] = relationship(
        back_populates="away_team", foreign_keys="Match.away_team_id"
    )
    rosters: Mapped[List["TeamRoster"]] = relationship(back_populates="team")

    def __repr__(self):
        return f"<Team {self.name}>"


class Player(Base):
    """Игрок."""
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(Integer, unique=True)  # ID с сайта
    last_name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100))
    patronymic: Mapped[Optional[str]] = mapped_column(String(100))
    birth_year: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    position: Mapped[Optional[str]] = mapped_column(String(50))
    photo_url: Mapped[Optional[str]] = mapped_column(String(500))

    # Relationships
    match_appearances: Mapped[List["MatchPlayer"]] = relationship(back_populates="player")
    best_player_awards: Mapped[List["BestPlayer"]] = relationship(back_populates="player")
    roster_entries: Mapped[List["TeamRoster"]] = relationship(back_populates="player")

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name]
        if self.patronymic:
            parts.append(self.patronymic)
        return " ".join(parts)

    def __repr__(self):
        return f"<Player {self.full_name}>"


class Referee(Base):
    """Судья."""
    __tablename__ = "referees"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True, nullable=True)
    last_name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100))
    patronymic: Mapped[Optional[str]] = mapped_column(String(100))

    # Relationships
    matches: Mapped[List["Match"]] = relationship(back_populates="referee")

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name]
        if self.patronymic:
            parts.append(self.patronymic)
        return " ".join(parts)

    def __repr__(self):
        return f"<Referee {self.full_name}>"


class Match(Base):
    """Матч."""
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(Integer, unique=True)  # match_id с сайта

    # Время и место
    date_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    venue: Mapped[Optional[str]] = mapped_column(String(200))

    # Команды
    home_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"))

    # Результат
    home_score: Mapped[Optional[int]] = mapped_column(Integer)  # Счёт по сетам (напр. 3)
    away_score: Mapped[Optional[int]] = mapped_column(Integer)  # Счёт по сетам (напр. 1)
    set_scores: Mapped[Optional[str]] = mapped_column(String(100))  # "25:20, 25:22, 20:25, 25:18"

    # Статус
    status: Mapped[str] = mapped_column(String(50), default="unknown")  # played, cancelled, postponed

    # Турнирная информация
    round_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rounds.id"))
    tournament_path: Mapped[Optional[str]] = mapped_column(String(500))  # Полный путь турнира

    # Судейство
    referee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("referees.id"))
    referee_rating_home: Mapped[Optional[int]] = mapped_column(Integer)  # Оценка от хозяев
    referee_rating_away: Mapped[Optional[int]] = mapped_column(Integer)  # Оценка от гостей
    referee_rating_home_text: Mapped[Optional[str]] = mapped_column(String(100))
    referee_rating_away_text: Mapped[Optional[str]] = mapped_column(String(100))

    # Метаданные
    parsed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_html: Mapped[Optional[str]] = mapped_column(Text)  # Для отладки

    # Relationships
    home_team: Mapped[Optional["Team"]] = relationship(
        back_populates="home_matches", foreign_keys=[home_team_id]
    )
    away_team: Mapped[Optional["Team"]] = relationship(
        back_populates="away_matches", foreign_keys=[away_team_id]
    )
    round: Mapped[Optional["Round"]] = relationship(back_populates="matches")
    referee: Mapped[Optional["Referee"]] = relationship(back_populates="matches")
    players: Mapped[List["MatchPlayer"]] = relationship(back_populates="match")
    best_players: Mapped[List["BestPlayer"]] = relationship(back_populates="match")

    def __repr__(self):
        home = self.home_team.name if self.home_team else "?"
        away = self.away_team.name if self.away_team else "?"
        return f"<Match {home} vs {away} ({self.site_id})>"


class MatchPlayer(Base):
    """Связь игрок-матч (состав на матч)."""
    __tablename__ = "match_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    # Relationships
    match: Mapped["Match"] = relationship(back_populates="players")
    player: Mapped["Player"] = relationship(back_populates="match_appearances")
    team: Mapped["Team"] = relationship()

    __table_args__ = (
        UniqueConstraint('match_id', 'player_id', name='unique_match_player'),
    )

    def __repr__(self):
        return f"<MatchPlayer match={self.match_id} player={self.player_id}>"


class BestPlayer(Base):
    """Лучший игрок матча."""
    __tablename__ = "best_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"), nullable=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    # Fallback if player not found by name
    player_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Relationships
    match: Mapped["Match"] = relationship(back_populates="best_players")
    player: Mapped[Optional["Player"]] = relationship(back_populates="best_player_awards")
    team: Mapped["Team"] = relationship()

    __table_args__ = (
        UniqueConstraint('match_id', 'team_id', name='unique_best_player_per_team'),
    )

    def __repr__(self):
        return f"<BestPlayer match={self.match_id} player={self.player_id}>"


class TeamRoster(Base):
    """Исторический состав команды на турнир (из members.php)."""
    __tablename__ = "team_rosters"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    tournament_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tournaments.id"))
    roster_site_id: Mapped[Optional[int]] = mapped_column(Integer)  # ID из members.php?id=

    # Дополнительные данные на момент турнира
    jersey_number: Mapped[Optional[int]] = mapped_column(Integer)

    # Relationships
    team: Mapped["Team"] = relationship(back_populates="rosters")
    player: Mapped["Player"] = relationship(back_populates="roster_entries")
    tournament: Mapped[Optional["Tournament"]] = relationship()

    __table_args__ = (
        UniqueConstraint('roster_site_id', 'player_id', name='unique_roster_player'),
    )

    def __repr__(self):
        return f"<TeamRoster team={self.team_id} player={self.player_id}>"


class ParsingJob(Base):
    """Журнал задач парсинга."""
    __tablename__ = "parsing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50))  # "matches", "teams", "rosters"
    start_id: Mapped[int] = mapped_column(Integer)
    end_id: Mapped[int] = mapped_column(Integer)
    current_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # "running", "paused", "completed", "failed"
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    total_parsed: Mapped[int] = mapped_column(Integer, default=0)
    total_errors: Mapped[int] = mapped_column(Integer, default=0)
    error_log: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self):
        return f"<ParsingJob {self.job_type} {self.start_id}-{self.end_id} ({self.status})>"
