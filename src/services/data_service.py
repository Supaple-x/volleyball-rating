"""Service for saving parsed data to database."""

import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from src.database.models import (
    Team, Player, Referee, Match, MatchPlayer, BestPlayer, TeamRoster,
    Season, Tournament, League, Round
)

logger = logging.getLogger(__name__)


class DataService:
    """Service for saving and retrieving volleyball data."""

    def __init__(self, session: Session):
        self.session = session

    def get_or_create_team(self, site_id: int, name: str = None) -> Team:
        """Get existing team or create new one."""
        team = self.session.query(Team).filter_by(site_id=site_id).first()
        if not team:
            team = Team(site_id=site_id, name=name or f"Team {site_id}")
            self.session.add(team)
            self.session.flush()
        elif name and team.name != name:
            team.name = name
        return team

    def get_or_create_player(self, site_id: int, last_name: str = None,
                              first_name: str = None, patronymic: str = None,
                              **kwargs) -> Player:
        """Get existing player or create new one."""
        player = self.session.query(Player).filter_by(site_id=site_id).first()
        if not player:
            player = Player(
                site_id=site_id,
                last_name=last_name or "",
                first_name=first_name or "",
                patronymic=patronymic,
                birth_year=kwargs.get("birth_year"),
                height=kwargs.get("height"),
                position=kwargs.get("position"),
                photo_url=kwargs.get("photo_url"),
            )
            self.session.add(player)
            self.session.flush()
        else:
            # Update with new data if available
            if last_name and not player.last_name:
                player.last_name = last_name
            if first_name and not player.first_name:
                player.first_name = first_name
            if patronymic and not player.patronymic:
                player.patronymic = patronymic
            if kwargs.get("birth_year") and not player.birth_year:
                player.birth_year = kwargs["birth_year"]
            if kwargs.get("height") and not player.height:
                player.height = kwargs["height"]
            if kwargs.get("position") and not player.position:
                player.position = kwargs["position"]
            if kwargs.get("photo_url") and not player.photo_url:
                player.photo_url = kwargs["photo_url"]
        return player

    def get_or_create_referee(self, last_name: str, first_name: str = None,
                               patronymic: str = None) -> Referee:
        """Get existing referee or create new one."""
        query = self.session.query(Referee).filter_by(last_name=last_name)
        if first_name:
            query = query.filter_by(first_name=first_name)
        if patronymic:
            query = query.filter_by(patronymic=patronymic)

        referee = query.first()
        if not referee:
            referee = Referee(
                last_name=last_name,
                first_name=first_name or "",
                patronymic=patronymic,
            )
            self.session.add(referee)
            self.session.flush()
        return referee

    def save_match(self, match_data: Dict[str, Any]) -> Optional[Match]:
        """Save match data to database."""
        site_id = match_data.get("site_id")
        if not site_id:
            logger.error("Match data missing site_id")
            return None

        # Check if match already exists
        match = self.session.query(Match).filter_by(site_id=site_id).first()
        if match:
            logger.debug(f"Match {site_id} already exists, updating...")
        else:
            match = Match(site_id=site_id)
            self.session.add(match)

        # Basic info
        match.date_time = match_data.get("date_time")
        match.status = match_data.get("status", "unknown")
        match.tournament_path = match_data.get("tournament_path")

        # Score
        match.home_score = match_data.get("home_score")
        match.away_score = match_data.get("away_score")
        match.set_scores = match_data.get("set_scores")

        # Teams
        if match_data.get("home_team"):
            home_team_data = match_data["home_team"]
            if home_team_data.get("site_id"):
                home_team = self.get_or_create_team(
                    home_team_data["site_id"],
                    home_team_data.get("name")
                )
                match.home_team_id = home_team.id

        if match_data.get("away_team"):
            away_team_data = match_data["away_team"]
            if away_team_data.get("site_id"):
                away_team = self.get_or_create_team(
                    away_team_data["site_id"],
                    away_team_data.get("name")
                )
                match.away_team_id = away_team.id

        # Referee
        if match_data.get("referee"):
            ref_data = match_data["referee"]
            if ref_data.get("last_name"):
                referee = self.get_or_create_referee(
                    ref_data["last_name"],
                    ref_data.get("first_name"),
                    ref_data.get("patronymic")
                )
                match.referee_id = referee.id

        match.referee_rating_home = match_data.get("referee_rating_home")
        match.referee_rating_away = match_data.get("referee_rating_away")
        match.referee_rating_home_text = match_data.get("referee_rating_home_text")
        match.referee_rating_away_text = match_data.get("referee_rating_away_text")

        self.session.flush()

        # Save players in rosters
        self._save_match_players(match, match_data)

        # Save best players
        self._save_best_players(match, match_data)

        return match

    def _save_match_players(self, match: Match, match_data: Dict[str, Any]):
        """Save match roster (players who played)."""
        # Clear existing roster
        self.session.query(MatchPlayer).filter_by(match_id=match.id).delete()

        # Track added players to avoid duplicates
        added_player_ids = set()

        # Home team players
        if match.home_team_id and match_data.get("home_roster"):
            for player_data in match_data["home_roster"]:
                if player_data.get("site_id"):
                    player = self.get_or_create_player(**player_data)
                    if player.id not in added_player_ids:
                        mp = MatchPlayer(
                            match_id=match.id,
                            player_id=player.id,
                            team_id=match.home_team_id
                        )
                        self.session.add(mp)
                        added_player_ids.add(player.id)

        # Away team players
        if match.away_team_id and match_data.get("away_roster"):
            for player_data in match_data["away_roster"]:
                if player_data.get("site_id"):
                    player = self.get_or_create_player(**player_data)
                    if player.id not in added_player_ids:
                        mp = MatchPlayer(
                            match_id=match.id,
                            player_id=player.id,
                            team_id=match.away_team_id
                        )
                        self.session.add(mp)
                        added_player_ids.add(player.id)

    def _save_best_players(self, match: Match, match_data: Dict[str, Any]):
        """Save best players of the match."""
        # Clear existing
        self.session.query(BestPlayer).filter_by(match_id=match.id).delete()

        for bp_data in match_data.get("best_players", []):
            if bp_data.get("player") and bp_data.get("team"):
                player_info = bp_data["player"]
                team_info = bp_data["team"]

                if not team_info.get("site_id"):
                    continue

                team = self.get_or_create_team(team_info["site_id"], team_info.get("name"))
                player_id = None
                player_name = None

                # If we have site_id, use it directly
                if player_info.get("site_id"):
                    player = self.get_or_create_player(**player_info)
                    player_id = player.id
                else:
                    # Try to find player by name in the match roster
                    first_name = player_info.get("first_name", "")
                    last_name = player_info.get("last_name", "")

                    if first_name and last_name:
                        # Search in match_players for this match and team
                        found_player = self.session.query(Player).join(
                            MatchPlayer, MatchPlayer.player_id == Player.id
                        ).filter(
                            MatchPlayer.match_id == match.id,
                            MatchPlayer.team_id == team.id,
                            Player.first_name == first_name,
                            Player.last_name == last_name
                        ).first()

                        if found_player:
                            player_id = found_player.id
                        else:
                            # Fallback: save as text
                            parts = [last_name, first_name]
                            if player_info.get("middle_name"):
                                parts.append(player_info["middle_name"])
                            player_name = " ".join(parts)

                bp = BestPlayer(
                    match_id=match.id,
                    player_id=player_id,
                    team_id=team.id,
                    player_name=player_name
                )
                self.session.add(bp)

    def save_roster(self, roster_data: Dict[str, Any]) -> bool:
        """Save roster data from members.php."""
        if not roster_data.get("team") or not roster_data.get("players"):
            return False

        team_info = roster_data["team"]
        if not team_info.get("site_id"):
            return False

        team = self.get_or_create_team(team_info["site_id"], team_info.get("name"))

        for player_data in roster_data["players"]:
            if player_data.get("site_id"):
                player = self.get_or_create_player(**player_data)

                # Check if roster entry exists
                existing = self.session.query(TeamRoster).filter_by(
                    roster_site_id=roster_data["roster_id"],
                    player_id=player.id
                ).first()

                if not existing:
                    roster = TeamRoster(
                        team_id=team.id,
                        player_id=player.id,
                        roster_site_id=roster_data["roster_id"],
                        jersey_number=player_data.get("jersey_number")
                    )
                    self.session.add(roster)

        return True

    def get_match_by_site_id(self, site_id: int) -> Optional[Match]:
        """Get match by site ID."""
        return self.session.query(Match).filter_by(site_id=site_id).first()

    def match_exists(self, site_id: int) -> bool:
        """Check if match already exists in database."""
        return self.session.query(Match).filter_by(site_id=site_id).count() > 0

    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        return {
            "matches": self.session.query(Match).count(),
            "teams": self.session.query(Team).count(),
            "players": self.session.query(Player).count(),
            "referees": self.session.query(Referee).count(),
        }
