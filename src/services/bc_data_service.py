"""Service for saving BC parsed data to database."""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from src.database.models import (
    BCSeason, BCDivision, BCTeam, BCDivisionTeam, BCPlayer, BCReferee,
    BCMatch, BCMatchPlayerStats, BCBestPlayer, BCMatchReferee
)

logger = logging.getLogger(__name__)


class BCDataService:
    """Service for saving and retrieving BC volleyball data."""

    def __init__(self, session: Session):
        self.session = session

    def get_or_create_season(self, number: int, name: str = "") -> BCSeason:
        season = self.session.query(BCSeason).filter_by(number=number).first()
        if not season:
            season = BCSeason(number=number, name=name or f"Season {number}")
            self.session.add(season)
            self.session.flush()
        elif name and season.name != name:
            season.name = name
        return season

    def get_or_create_division(self, name: str, season_id: int) -> BCDivision:
        division = self.session.query(BCDivision).filter_by(
            name=name, season_id=season_id
        ).first()
        if not division:
            division = BCDivision(name=name, season_id=season_id)
            self.session.add(division)
            self.session.flush()
        return division

    def get_or_create_team(self, site_id: int, name: str = None, **kwargs) -> BCTeam:
        team = self.session.query(BCTeam).filter_by(site_id=site_id).first()
        if not team:
            team = BCTeam(
                site_id=site_id,
                name=name or f"Team {site_id}",
                logo_url=kwargs.get("logo_url"),
                is_women=kwargs.get("is_women", False),
            )
            self.session.add(team)
            self.session.flush()
        else:
            if name and team.name != name:
                team.name = name
            if kwargs.get("logo_url") and not team.logo_url:
                team.logo_url = kwargs["logo_url"]
            if kwargs.get("is_women") is not None:
                team.is_women = kwargs["is_women"]
        return team

    def get_or_create_player(self, site_id: int, **kwargs) -> BCPlayer:
        player = self.session.query(BCPlayer).filter_by(site_id=site_id).first()
        if not player:
            # Dedup: check if same person exists under different site_id
            # Match by last_name + first_name + birth_date
            last_name = kwargs.get("last_name", "")
            first_name = kwargs.get("first_name", "")
            birth_date = kwargs.get("birth_date")
            if last_name and first_name and birth_date:
                player = self.session.query(BCPlayer).filter_by(
                    last_name=last_name, first_name=first_name, birth_date=birth_date
                ).first()
                if player:
                    logger.debug(f"Dedup: site_id={site_id} matched existing player "
                                 f"{last_name} {first_name} (id={player.id})")
        if not player:
            player = BCPlayer(
                site_id=site_id,
                last_name=kwargs.get("last_name", ""),
                first_name=kwargs.get("first_name", ""),
                birth_date=kwargs.get("birth_date"),
                height=kwargs.get("height"),
                weight=kwargs.get("weight"),
                position=kwargs.get("position"),
                photo_url=kwargs.get("photo_url"),
            )
            self.session.add(player)
            self.session.flush()
        else:
            # Update with new data if available
            if kwargs.get("last_name") and not player.last_name:
                player.last_name = kwargs["last_name"]
            if kwargs.get("first_name") and not player.first_name:
                player.first_name = kwargs["first_name"]
            if kwargs.get("birth_date") and not player.birth_date:
                player.birth_date = kwargs["birth_date"]
            if kwargs.get("height") and not player.height:
                player.height = kwargs["height"]
            if kwargs.get("weight") and not player.weight:
                player.weight = kwargs["weight"]
            if kwargs.get("position") and not player.position:
                player.position = kwargs["position"]
            if kwargs.get("photo_url") and not player.photo_url:
                player.photo_url = kwargs["photo_url"]
        return player

    def get_or_create_referee(self, site_id: int, **kwargs) -> BCReferee:
        referee = self.session.query(BCReferee).filter_by(site_id=site_id).first()
        if not referee:
            referee = BCReferee(
                site_id=site_id,
                last_name=kwargs.get("last_name", ""),
                first_name=kwargs.get("first_name", ""),
                photo_url=kwargs.get("photo_url"),
            )
            self.session.add(referee)
            self.session.flush()
        else:
            if kwargs.get("photo_url") and not referee.photo_url:
                referee.photo_url = kwargs["photo_url"]
        return referee

    def save_division_team(self, division_id: int, team_id: int,
                           games: int = None, wins: int = None,
                           losses: int = None, points: int = None):
        """Save or update division-team standings."""
        dt = self.session.query(BCDivisionTeam).filter_by(
            division_id=division_id, team_id=team_id
        ).first()
        if not dt:
            dt = BCDivisionTeam(
                division_id=division_id,
                team_id=team_id,
                games_played=games,
                wins=wins,
                losses=losses,
                points=points,
            )
            self.session.add(dt)
        else:
            if games is not None:
                dt.games_played = games
            if wins is not None:
                dt.wins = wins
            if losses is not None:
                dt.losses = losses
            if points is not None:
                dt.points = points

    def match_exists(self, site_id: int) -> bool:
        return self.session.query(BCMatch).filter_by(site_id=site_id).count() > 0

    def save_match(self, match_data: Dict[str, Any], season_id: int) -> Optional[BCMatch]:
        """Save full match data."""
        site_id = match_data.get("site_id")
        if not site_id:
            return None

        match = self.session.query(BCMatch).filter_by(site_id=site_id).first()
        if not match:
            match = BCMatch(site_id=site_id, season_id=season_id)
            self.session.add(match)
        else:
            match.season_id = season_id

        match.date_time = match_data.get("date_time")
        match.venue = match_data.get("venue")
        match.division_name = match_data.get("division_name")
        match.round_name = match_data.get("round_name")
        match.tournament_type = match_data.get("tournament_type")
        match.home_score = match_data.get("home_score")
        match.away_score = match_data.get("away_score")
        match.set_scores = match_data.get("set_scores")
        match.home_total_points = match_data.get("home_total_points")
        match.away_total_points = match_data.get("away_total_points")
        match.status = match_data.get("status", "unknown")
        match.parsed_at = datetime.utcnow()

        # Teams
        if match_data.get("home_team") and match_data["home_team"].get("site_id"):
            home_team = self.get_or_create_team(
                match_data["home_team"]["site_id"],
                match_data["home_team"].get("name")
            )
            match.home_team_id = home_team.id

        if match_data.get("away_team") and match_data["away_team"].get("site_id"):
            away_team = self.get_or_create_team(
                match_data["away_team"]["site_id"],
                match_data["away_team"].get("name")
            )
            match.away_team_id = away_team.id

        self.session.flush()

        # Player stats
        self._save_player_stats(match, match_data)

        # Best players
        self._save_best_players(match, match_data)

        # Referees
        self._save_referees(match, match_data)

        return match

    def _save_player_stats(self, match: BCMatch, match_data: Dict):
        """Save per-player match statistics."""
        # Clear existing
        self.session.query(BCMatchPlayerStats).filter_by(match_id=match.id).delete()

        added = set()
        for side, team_id_field in [("home_stats", "home_team_id"), ("away_stats", "away_team_id")]:
            stats_list = match_data.get(side, [])
            team_id = getattr(match, team_id_field)
            if not team_id or not stats_list:
                continue

            for ps in stats_list:
                player_site_id = ps.get("player_site_id")
                if not player_site_id:
                    continue

                # Parse name for player creation
                name = ps.get("player_name", "")
                parsed = {"last_name": "", "first_name": ""}
                if name:
                    parts = name.strip().split()
                    parsed["last_name"] = parts[0] if parts else ""
                    parsed["first_name"] = parts[1] if len(parts) > 1 else ""

                player = self.get_or_create_player(
                    site_id=player_site_id,
                    last_name=parsed["last_name"],
                    first_name=parsed["first_name"],
                )

                if player.id in added:
                    continue
                added.add(player.id)

                mps = BCMatchPlayerStats(
                    match_id=match.id,
                    player_id=player.id,
                    team_id=team_id,
                    jersey_number=ps.get("jersey_number"),
                    points=ps.get("points"),
                    attacks=ps.get("attacks"),
                    serves=ps.get("serves"),
                    blocks=ps.get("blocks"),
                )
                self.session.add(mps)

    def _save_best_players(self, match: BCMatch, match_data: Dict):
        """Save best players."""
        self.session.query(BCBestPlayer).filter_by(match_id=match.id).delete()

        for bp_data in match_data.get("best_players", []):
            player_id = None
            team_id = None
            player_name = bp_data.get("player_name", "")

            if bp_data.get("player_site_id"):
                parsed = {"last_name": "", "first_name": ""}
                if player_name:
                    parts = player_name.strip().split()
                    parsed["last_name"] = parts[0] if parts else ""
                    parsed["first_name"] = parts[1] if len(parts) > 1 else ""
                player = self.get_or_create_player(
                    site_id=bp_data["player_site_id"],
                    last_name=parsed["last_name"],
                    first_name=parsed["first_name"],
                )
                player_id = player.id

            bp = BCBestPlayer(
                match_id=match.id,
                player_id=player_id,
                team_id=team_id,
                player_name=player_name,
                points=bp_data.get("points"),
                attacks=bp_data.get("attacks"),
                serves=bp_data.get("serves"),
                blocks=bp_data.get("blocks"),
            )
            self.session.add(bp)

    def _save_referees(self, match: BCMatch, match_data: Dict):
        """Save match referees (many-to-many)."""
        self.session.query(BCMatchReferee).filter_by(match_id=match.id).delete()

        for ref_data in match_data.get("referees", []):
            if not ref_data.get("site_id"):
                continue
            referee = self.get_or_create_referee(
                site_id=ref_data["site_id"],
                last_name=ref_data.get("last_name", ""),
                first_name=ref_data.get("first_name", ""),
            )
            mr = BCMatchReferee(match_id=match.id, referee_id=referee.id)
            self.session.add(mr)

    def save_schedule_match(self, match_data: Dict, season_id: int) -> Optional[BCMatch]:
        """Save basic match data from schedule (before detail parsing)."""
        site_id = match_data.get("site_id")
        if not site_id:
            return None

        match = self.session.query(BCMatch).filter_by(site_id=site_id).first()
        if match:
            return match  # Already exists, don't overwrite with basic data

        match = BCMatch(site_id=site_id, season_id=season_id)
        match.date_time = match_data.get("date_time")
        match.venue = match_data.get("venue")
        match.division_name = match_data.get("division_name")
        match.round_name = match_data.get("round_name")
        match.tournament_type = match_data.get("tournament_type")
        match.home_score = match_data.get("home_score")
        match.away_score = match_data.get("away_score")
        match.status = match_data.get("status", "unknown")

        # Teams
        if match_data.get("home_team") and match_data["home_team"].get("site_id"):
            home_team = self.get_or_create_team(
                match_data["home_team"]["site_id"],
                match_data["home_team"].get("name")
            )
            match.home_team_id = home_team.id

        if match_data.get("away_team") and match_data["away_team"].get("site_id"):
            away_team = self.get_or_create_team(
                match_data["away_team"]["site_id"],
                match_data["away_team"].get("name")
            )
            match.away_team_id = away_team.id

        self.session.add(match)
        self.session.flush()
        return match

    def get_stats(self) -> Dict[str, int]:
        """Get BC database statistics."""
        return {
            "seasons": self.session.query(BCSeason).count(),
            "matches": self.session.query(BCMatch).count(),
            "teams": self.session.query(BCTeam).count(),
            "players": self.session.query(BCPlayer).count(),
            "referees": self.session.query(BCReferee).count(),
        }

    def get_season_match_ids(self, season_id: int) -> List[int]:
        """Get all match site_ids for a season."""
        matches = self.session.query(BCMatch.site_id).filter_by(season_id=season_id).all()
        return [m[0] for m in matches]

    def get_season_player_ids(self, season_id: int) -> List[int]:
        """Get unique player site_ids from match stats for a season."""
        from sqlalchemy import distinct
        results = self.session.query(distinct(BCPlayer.site_id)).join(
            BCMatchPlayerStats, BCMatchPlayerStats.player_id == BCPlayer.id
        ).join(
            BCMatch, BCMatch.id == BCMatchPlayerStats.match_id
        ).filter(BCMatch.season_id == season_id).all()
        return [r[0] for r in results]
