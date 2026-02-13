"""Background scheduler for auto-updating matches from both sources."""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from src.database.db import Database
from src.database.models import (
    Match, BCMatch, BCSeason, BCMatchPlayerStats
)
from src.parser import MatchParser
from src.services.data_service import DataService
from src.parser_bc import (
    BCSeasonParser, BCScheduleParser, BCMatchParser as BCMatchDetailParser,
    BCTeamParser, BCPlayerParser, BCRefereeParser
)
from src.services.bc_data_service import BCDataService
from sqlalchemy import func

logger = logging.getLogger(__name__)

# Stop after this many consecutive empty pages
VOLLEYMSK_EMPTY_THRESHOLD = 50
# How often to check (seconds)
CHECK_INTERVAL = 3600  # 1 hour
# BC: how many consecutive non-existent seasons to check before giving up
BC_SEASON_LOOKAHEAD = 2


class AutoUpdater:
    """Background auto-updater for both data sources."""

    def __init__(self, db: Database):
        self.db = db
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_run: Optional[datetime] = None
        self._status = "idle"
        self._last_vm_result = ""
        self._last_bc_result = ""

    def start(self):
        """Start the auto-updater daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("AutoUpdater already running")
            return

        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("AutoUpdater started (interval: %ds)", CHECK_INTERVAL)

    def stop(self):
        """Stop the auto-updater."""
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("AutoUpdater stopped")

    def get_status(self):
        return {
            "status": self._status,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_vm_result": self._last_vm_result,
            "last_bc_result": self._last_bc_result,
        }

    def _run_loop(self):
        """Main loop: run immediately, then every CHECK_INTERVAL."""
        # Initial delay to let app fully start
        self._stop_flag.wait(10)

        while not self._stop_flag.is_set():
            try:
                self._status = "running"
                self._last_run = datetime.now()

                # Update VolleyMSK
                vm_result = self._update_volleymsk()
                self._last_vm_result = vm_result
                logger.info("VolleyMSK update: %s", vm_result)

                if self._stop_flag.is_set():
                    break

                # Update BC
                bc_result = self._update_bc()
                self._last_bc_result = bc_result
                logger.info("BC update: %s", bc_result)

                self._status = "idle"

            except Exception as e:
                self._status = "error"
                logger.error("AutoUpdater error: %s", e, exc_info=True)

            # Wait for next interval
            self._stop_flag.wait(CHECK_INTERVAL)

    def _update_volleymsk(self) -> str:
        """Check for new VolleyMSK matches beyond current max."""
        parser = MatchParser()

        with self.db.session() as session:
            max_id = session.query(func.max(Match.site_id)).filter(
                Match.home_team_id.isnot(None)
            ).scalar() or 0

        logger.info("VolleyMSK: checking new matches after site_id=%d", max_id)

        new_count = 0
        empty_streak = 0
        current_id = max_id + 1

        while empty_streak < VOLLEYMSK_EMPTY_THRESHOLD:
            if self._stop_flag.is_set():
                break

            try:
                with self.db.session() as session:
                    ds = DataService(session)
                    if ds.match_exists(current_id):
                        current_id += 1
                        empty_streak = 0
                        continue

                    match_data = parser.parse_match(current_id)
                    if match_data and match_data.get("home_team"):
                        ds.save_match(match_data)
                        new_count += 1
                        empty_streak = 0
                        logger.info("VolleyMSK: new match %d", current_id)
                    else:
                        empty_streak += 1

            except Exception as e:
                logger.error("VolleyMSK: error parsing %d: %s", current_id, e)
                empty_streak += 1

            current_id += 1

        return f"+{new_count} matches (checked up to {current_id - 1})"

    def _update_bc(self) -> str:
        """Check for new BC matches in latest season and detect new seasons."""
        season_parser = BCSeasonParser()
        schedule_parser = BCScheduleParser()
        match_parser = BCMatchDetailParser()
        team_parser = BCTeamParser()
        player_parser = BCPlayerParser()
        referee_parser = BCRefereeParser()

        # Find latest season in DB
        with self.db.session() as session:
            max_season = session.query(func.max(BCSeason.number)).scalar() or 0

        total_new = 0

        # Only check the current max season (for new matches within it)
        # and one season ahead (to detect a brand-new season)
        seasons_to_check = [max_season] if max_season > 0 else []

        # Check if next season exists by comparing season name
        next_season = max_season + 1
        try:
            next_data = season_parser.parse_season(next_season)
            if next_data and next_data.get("name"):
                # Get current season name for comparison
                with self.db.session() as session:
                    current = session.query(BCSeason).filter_by(number=max_season).first()
                    current_name = current.name if current else ""

                # If names differ, it's a real new season
                if next_data["name"] != current_name:
                    seasons_to_check.append(next_season)
                    logger.info("BC: detected new season %d: '%s'", next_season, next_data["name"])
                else:
                    logger.debug("BC: season %d has same name as %d, skipping", next_season, max_season)
        except Exception as e:
            logger.debug("BC: season %d check failed: %s", next_season, e)

        for season_num in seasons_to_check:
            if self._stop_flag.is_set():
                break

            new_in_season = self._update_bc_season(
                season_num, season_parser, schedule_parser,
                match_parser, team_parser, player_parser, referee_parser
            )
            total_new += new_in_season

        return f"+{total_new} matches (checked seasons {max_season}-{max_season + BC_SEASON_LOOKAHEAD})"

    def _update_bc_season(self, season_num, season_parser, schedule_parser,
                          match_parser, team_parser, player_parser,
                          referee_parser) -> int:
        """Update a single BC season. Returns count of new matches."""
        logger.info("BC: checking season %d", season_num)

        try:
            # Parse schedule
            championship = schedule_parser.parse_schedule(season_num, "championship")
            cup = schedule_parser.parse_schedule(season_num, "cup")
            all_schedule = championship + cup

            if not all_schedule:
                logger.info("BC: season %d has no matches in schedule", season_num)
                return 0

            # Save season and schedule
            with self.db.session() as session:
                svc = BCDataService(session)
                season = svc.get_or_create_season(season_num)

                # Update season name
                season_data = season_parser.parse_season(season_num)
                if season_data and season_data.get("name"):
                    season.name = season_data["name"]

                # Save schedule entries and find new matches
                new_stubs = []
                for m in all_schedule:
                    m_site_id = m.get("site_id")
                    if not m_site_id:
                        continue

                    m["tournament_type"] = m.get("tournament_type", "championship")
                    svc.save_schedule_match(m, season.id)

                    # Check if match is already fully parsed
                    existing_match = session.query(BCMatch).filter_by(
                        site_id=m_site_id
                    ).first()
                    if existing_match and existing_match.home_score is not None:
                        continue  # Already parsed with score
                    if not existing_match:
                        new_stubs.append(m)

            if not new_stubs:
                logger.info("BC: season %d - no new matches to parse", season_num)
                return 0

            logger.info("BC: season %d - %d new matches to parse", season_num, len(new_stubs))

            # Parse teams
            try:
                teams = team_parser.parse_teams_listing(season_num)
                with self.db.session() as session:
                    svc = BCDataService(session)
                    for td in teams:
                        svc.get_or_create_team(
                            site_id=td["site_id"],
                            name=td.get("name"),
                            is_women=td.get("is_women", False),
                        )
            except Exception as e:
                logger.error("BC: teams parse error for season %d: %s", season_num, e)

            # Parse new matches
            new_count = 0
            for stub in new_stubs:
                if self._stop_flag.is_set():
                    break

                m_site_id = stub.get("site_id")
                try:
                    match_data = match_parser.parse_match(season_num, m_site_id)
                    if match_data:
                        match_data.setdefault("tournament_type", stub.get("tournament_type"))
                        match_data.setdefault("division_name", stub.get("division_name"))
                        match_data.setdefault("round_name", stub.get("round_name"))
                        match_data.setdefault("venue", stub.get("venue"))

                        with self.db.session() as session:
                            svc = BCDataService(session)
                            season = svc.get_or_create_season(season_num)
                            svc.save_match(match_data, season.id)
                            new_count += 1

                except Exception as e:
                    logger.error("BC: match %d parse error: %s", m_site_id, e)

            # Parse players for new matches
            if new_count > 0:
                # Players
                try:
                    with self.db.session() as session:
                        svc = BCDataService(session)
                        season = svc.get_or_create_season(season_num)
                        player_site_ids = svc.get_season_player_ids(season.id)

                    for pid in player_site_ids:
                        if self._stop_flag.is_set():
                            break
                        try:
                            pdata = player_parser.parse_player(season_num, pid)
                            if pdata:
                                with self.db.session() as session:
                                    svc = BCDataService(session)
                                    svc.get_or_create_player(
                                        site_id=pid,
                                        last_name=pdata.get("last_name", ""),
                                        first_name=pdata.get("first_name", ""),
                                        birth_date=pdata.get("birth_date"),
                                        height=pdata.get("height"),
                                        weight=pdata.get("weight"),
                                        position=pdata.get("position"),
                                        photo_url=pdata.get("photo_url"),
                                    )
                        except Exception as e:
                            logger.error("BC: player %d error: %s", pid, e)
                except Exception as e:
                    logger.error("BC: players step error: %s", e)

                # Referees
                try:
                    refs = referee_parser.parse_referees_listing(season_num)
                    with self.db.session() as session:
                        svc = BCDataService(session)
                        for rd in refs:
                            svc.get_or_create_referee(
                                site_id=rd["site_id"],
                                last_name=rd.get("last_name", ""),
                                first_name=rd.get("first_name", ""),
                                photo_url=rd.get("photo_url"),
                            )
                except Exception as e:
                    logger.error("BC: referees parse error: %s", e)

            return new_count

        except Exception as e:
            logger.error("BC: season %d update error: %s", season_num, e, exc_info=True)
            return 0
