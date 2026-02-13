"""Service for coordinating BC parsing operations with multi-step progress."""

import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

from src.database.db import Database
from src.parser_bc import (
    BCSeasonParser, BCScheduleParser, BCMatchParser,
    BCTeamParser, BCPlayerParser, BCRefereeParser
)
from src.database.models import BCMatch, BCMatchPlayerStats
from src.services.bc_data_service import BCDataService

logger = logging.getLogger(__name__)


class StepProgress:
    """Progress for a single parsing step."""

    def __init__(self, name: str):
        self.name = name
        self.status = "pending"  # pending, running, completed, failed, skipped
        self.total = 0
        self.done = 0
        self.errors = 0

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "errors": self.errors,
        }


class BCParsingService:
    """Service for managing BC parsing jobs with per-step progress bars."""

    STEPS = ["schedule", "teams", "matches", "players", "referees"]

    def __init__(self, db: Database):
        self.db = db
        self.season_parser = BCSeasonParser()
        self.schedule_parser = BCScheduleParser()
        self.match_parser = BCMatchParser()
        self.team_parser = BCTeamParser()
        self.player_parser = BCPlayerParser()
        self.referee_parser = BCRefereeParser()

        self._status = "idle"  # idle, running, paused, stopped, completed
        self._season_num = 0
        self._current_step = ""
        self._mode = ""  # full, schedule, matches, players, referees, all-seasons
        self._steps: Dict[str, StepProgress] = {}
        self._last_error = ""

        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._current_thread: Optional[threading.Thread] = None

        # For all-seasons mode
        self._all_seasons_current = 0
        self._all_seasons_total = 0

        self._reset_steps()

    def _reset_steps(self):
        self._steps = {name: StepProgress(name) for name in self.STEPS}

    @property
    def is_running(self) -> bool:
        return self._status in ("running", "paused")

    def get_progress(self) -> Dict[str, Any]:
        """Get current progress for all steps."""
        return {
            "status": self._status,
            "season_num": self._season_num,
            "current_step": self._current_step,
            "mode": self._mode,
            "steps": {name: step.to_dict() for name, step in self._steps.items()},
            "last_error": self._last_error,
            "all_seasons_current": self._all_seasons_current,
            "all_seasons_total": self._all_seasons_total,
        }

    def _check_stop(self) -> bool:
        """Check if stop was requested."""
        return self._stop_flag.is_set()

    def _check_pause(self):
        """Wait if paused."""
        while self._pause_flag.is_set() and not self._stop_flag.is_set():
            self._status = "paused"
            self._pause_flag.wait(1)
        if not self._stop_flag.is_set():
            self._status = "running"

    # ---- Public control methods ----

    def start_full_season(self, season_num: int, skip_existing: bool = True):
        """Parse entire season: schedule → teams → matches → players → referees."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")
        self._launch_thread(self._full_season_worker, season_num, skip_existing)

    def start_all_seasons(self, start: int, end: int, skip_existing: bool = True):
        """Parse multiple seasons sequentially."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")
        self._launch_thread(self._all_seasons_worker, start, end, skip_existing)

    def start_schedule(self, season_num: int):
        """Parse only schedule for a season."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")
        self._launch_thread(self._schedule_only_worker, season_num)

    def start_matches(self, season_num: int, skip_existing: bool = True):
        """Parse only match details for a season."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")
        self._launch_thread(self._matches_only_worker, season_num, skip_existing)

    def start_players(self, season_num: int):
        """Parse only player details for a season."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")
        self._launch_thread(self._players_only_worker, season_num)

    def start_referees(self, season_num: int):
        """Parse only referees for a season."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")
        self._launch_thread(self._referees_only_worker, season_num)

    def pause(self):
        if self._status == "running":
            self._pause_flag.set()

    def resume(self):
        self._pause_flag.clear()

    def stop(self):
        self._stop_flag.set()
        self._pause_flag.clear()
        if self._current_thread:
            self._current_thread.join(timeout=5)

    def get_stats(self) -> Dict[str, int]:
        with self.db.session() as session:
            svc = BCDataService(session)
            return svc.get_stats()

    # ---- Internal methods ----

    def _launch_thread(self, target, *args):
        self._stop_flag.clear()
        self._pause_flag.clear()
        self._reset_steps()
        self._status = "running"
        self._last_error = ""

        self._current_thread = threading.Thread(target=target, args=args, daemon=True)
        self._current_thread.start()

    def _full_season_worker(self, season_num: int, skip_existing: bool):
        """Worker: full season parse."""
        self._season_num = season_num
        self._mode = "full"
        logger.info(f"Starting full parse for season {season_num}")

        try:
            # Step 1: Schedule
            match_stubs = self._do_schedule(season_num)
            if self._check_stop():
                self._status = "stopped"
                return

            # Step 2: Teams
            self._do_teams(season_num)
            if self._check_stop():
                self._status = "stopped"
                return

            # Step 3: Matches
            self._do_matches(season_num, match_stubs, skip_existing)
            if self._check_stop():
                self._status = "stopped"
                return

            # Step 4: Players
            self._do_players(season_num)
            if self._check_stop():
                self._status = "stopped"
                return

            # Step 5: Referees
            self._do_referees(season_num)

            if not self._check_stop():
                self._status = "completed"

        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)
            logger.error(f"Full season parse failed: {e}", exc_info=True)

    def _all_seasons_worker(self, start: int, end: int, skip_existing: bool):
        """Worker: parse multiple seasons."""
        self._mode = "all-seasons"
        self._all_seasons_total = end - start + 1
        logger.info(f"Starting parse for seasons {start}-{end}")

        try:
            for season_num in range(start, end + 1):
                if self._check_stop():
                    self._status = "stopped"
                    return

                self._all_seasons_current = season_num
                self._season_num = season_num
                self._reset_steps()

                logger.info(f"Parsing season {season_num}/{end}")

                match_stubs = self._do_schedule(season_num)
                if self._check_stop():
                    self._status = "stopped"
                    return

                self._do_teams(season_num)
                if self._check_stop():
                    self._status = "stopped"
                    return

                self._do_matches(season_num, match_stubs, skip_existing)
                if self._check_stop():
                    self._status = "stopped"
                    return

                self._do_players(season_num)
                if self._check_stop():
                    self._status = "stopped"
                    return

                self._do_referees(season_num)
                if self._check_stop():
                    self._status = "stopped"
                    return

            self._status = "completed"
        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)
            logger.error(f"All seasons parse failed: {e}", exc_info=True)

    def _schedule_only_worker(self, season_num: int):
        self._season_num = season_num
        self._mode = "schedule"
        try:
            self._do_schedule(season_num)
            if not self._check_stop():
                self._status = "completed"
            else:
                self._status = "stopped"
        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)

    def _matches_only_worker(self, season_num: int, skip_existing: bool):
        self._season_num = season_num
        self._mode = "matches"
        try:
            # Get match IDs from DB
            with self.db.session() as session:
                svc = BCDataService(session)
                season = svc.get_or_create_season(season_num)
                match_ids = svc.get_season_match_ids(season.id)

            match_stubs = [{"site_id": mid} for mid in match_ids]
            self._steps["schedule"].status = "skipped"
            self._steps["teams"].status = "skipped"
            self._do_matches(season_num, match_stubs, skip_existing)
            if not self._check_stop():
                self._status = "completed"
            else:
                self._status = "stopped"
        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)

    def _players_only_worker(self, season_num: int):
        self._season_num = season_num
        self._mode = "players"
        try:
            self._steps["schedule"].status = "skipped"
            self._steps["teams"].status = "skipped"
            self._steps["matches"].status = "skipped"
            self._do_players(season_num)
            if not self._check_stop():
                self._status = "completed"
            else:
                self._status = "stopped"
        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)

    def _referees_only_worker(self, season_num: int):
        self._season_num = season_num
        self._mode = "referees"
        try:
            for step_name in ["schedule", "teams", "matches", "players"]:
                self._steps[step_name].status = "skipped"
            self._do_referees(season_num)
            if not self._check_stop():
                self._status = "completed"
            else:
                self._status = "stopped"
        except Exception as e:
            self._status = "failed"
            self._last_error = str(e)

    # ---- Step implementations ----

    def _do_schedule(self, season_num: int) -> List[Dict]:
        """Parse schedule (championship + cup) and save to DB."""
        step = self._steps["schedule"]
        step.status = "running"
        step.total = 2  # championship + cup
        self._current_step = "schedule"

        all_matches = []
        try:
            with self.db.session() as session:
                svc = BCDataService(session)
                season = svc.get_or_create_season(season_num)

                # Parse season name
                season_data = self.season_parser.parse_season(season_num)
                if season_data and season_data.get("name"):
                    season.name = season_data["name"]

                # Championship schedule
                self._check_pause()
                if self._check_stop():
                    return []
                championship = self.schedule_parser.parse_schedule(season_num, "championship")
                for m in championship:
                    m["tournament_type"] = "championship"
                    svc.save_schedule_match(m, season.id)
                all_matches.extend(championship)
                step.done = 1

                # Cup schedule
                self._check_pause()
                if self._check_stop():
                    return all_matches
                cup = self.schedule_parser.parse_schedule(season_num, "cup")
                for m in cup:
                    m["tournament_type"] = "cup"
                    svc.save_schedule_match(m, season.id)
                all_matches.extend(cup)
                step.done = 2

            step.status = "completed"
            logger.info(f"Schedule: {len(all_matches)} matches for season {season_num}")
        except Exception as e:
            step.status = "failed"
            step.errors += 1
            self._last_error = f"Schedule: {e}"
            logger.error(f"Schedule parse error: {e}", exc_info=True)

        return all_matches

    def _do_teams(self, season_num: int):
        """Parse teams listing and save standings."""
        step = self._steps["teams"]
        step.status = "running"
        step.total = 1
        self._current_step = "teams"

        try:
            self._check_pause()
            if self._check_stop():
                return

            teams = self.team_parser.parse_teams_listing(season_num)

            with self.db.session() as session:
                svc = BCDataService(session)
                season = svc.get_or_create_season(season_num)

                for team_data in teams:
                    svc.get_or_create_team(
                        site_id=team_data["site_id"],
                        name=team_data.get("name"),
                        is_women=team_data.get("is_women", False),
                    )

            step.done = 1
            step.status = "completed"
            logger.info(f"Teams: {len(teams)} for season {season_num}")
        except Exception as e:
            step.status = "failed"
            step.errors += 1
            self._last_error = f"Teams: {e}"
            logger.error(f"Teams parse error: {e}", exc_info=True)

    def _do_matches(self, season_num: int, match_stubs: List[Dict], skip_existing: bool):
        """Parse match detail pages."""
        step = self._steps["matches"]
        step.status = "running"
        step.total = len(match_stubs)
        self._current_step = "matches"

        for stub in match_stubs:
            self._check_pause()
            if self._check_stop():
                return

            match_site_id = stub.get("site_id")
            if not match_site_id:
                step.done += 1
                continue

            try:
                with self.db.session() as session:
                    svc = BCDataService(session)
                    season = svc.get_or_create_season(season_num)

                    if skip_existing:
                        existing = session.query(
                            BCMatchPlayerStats
                        ).join(BCMatch).filter(
                            BCMatch.site_id == match_site_id
                        ).first()
                        if existing:
                            step.done += 1
                            continue

                    match_data = self.match_parser.parse_match(season_num, match_site_id)
                    if match_data:
                        # Preserve schedule data
                        match_data.setdefault("tournament_type", stub.get("tournament_type"))
                        match_data.setdefault("division_name", stub.get("division_name"))
                        match_data.setdefault("round_name", stub.get("round_name"))
                        match_data.setdefault("venue", stub.get("venue"))
                        svc.save_match(match_data, season.id)

                step.done += 1
            except Exception as e:
                step.errors += 1
                step.done += 1
                self._last_error = f"Match {match_site_id}: {e}"
                logger.error(f"Match {match_site_id} parse error: {e}")

        if step.status == "running":
            step.status = "completed"

    def _do_players(self, season_num: int):
        """Parse player detail pages for bio data."""
        step = self._steps["players"]
        step.status = "running"
        self._current_step = "players"

        try:
            # Get player IDs from match stats in this season
            with self.db.session() as session:
                svc = BCDataService(session)
                season = svc.get_or_create_season(season_num)
                player_site_ids = svc.get_season_player_ids(season.id)

            step.total = len(player_site_ids)

            for player_site_id in player_site_ids:
                self._check_pause()
                if self._check_stop():
                    return

                try:
                    player_data = self.player_parser.parse_player(season_num, player_site_id)
                    if player_data:
                        with self.db.session() as session:
                            svc = BCDataService(session)
                            svc.get_or_create_player(
                                site_id=player_site_id,
                                last_name=player_data.get("last_name", ""),
                                first_name=player_data.get("first_name", ""),
                                birth_date=player_data.get("birth_date"),
                                height=player_data.get("height"),
                                weight=player_data.get("weight"),
                                position=player_data.get("position"),
                                photo_url=player_data.get("photo_url"),
                            )
                    step.done += 1
                except Exception as e:
                    step.errors += 1
                    step.done += 1
                    self._last_error = f"Player {player_site_id}: {e}"
                    logger.error(f"Player {player_site_id} parse error: {e}")

            if step.status == "running":
                step.status = "completed"
        except Exception as e:
            step.status = "failed"
            self._last_error = f"Players: {e}"
            logger.error(f"Players step error: {e}", exc_info=True)

    def _do_referees(self, season_num: int):
        """Parse referees listing."""
        step = self._steps["referees"]
        step.status = "running"
        step.total = 1
        self._current_step = "referees"

        try:
            self._check_pause()
            if self._check_stop():
                return

            refs = self.referee_parser.parse_referees_listing(season_num)

            with self.db.session() as session:
                svc = BCDataService(session)
                for ref_data in refs:
                    svc.get_or_create_referee(
                        site_id=ref_data["site_id"],
                        last_name=ref_data.get("last_name", ""),
                        first_name=ref_data.get("first_name", ""),
                        photo_url=ref_data.get("photo_url"),
                    )

            step.done = 1
            step.status = "completed"
            logger.info(f"Referees: {len(refs)} for season {season_num}")
        except Exception as e:
            step.status = "failed"
            step.errors += 1
            self._last_error = f"Referees: {e}"
            logger.error(f"Referees parse error: {e}", exc_info=True)
