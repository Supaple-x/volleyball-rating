"""Service for coordinating parsing operations."""

import logging
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field

from src.database.db import Database
from src.database.models import ParsingJob
from src.parser import MatchParser, TeamParser, RosterParser
from src.services.data_service import DataService

logger = logging.getLogger(__name__)


@dataclass
class ParsingProgress:
    """Current parsing progress."""
    job_type: str
    start_id: int
    end_id: int
    current_id: int
    total_parsed: int = 0
    total_errors: int = 0
    status: str = "idle"  # idle, running, paused, completed, failed
    last_error: str = ""
    started_at: datetime = None
    estimated_remaining: int = 0

    @property
    def progress_percent(self) -> float:
        total = self.end_id - self.start_id + 1
        if total <= 0:
            return 0
        done = self.current_id - self.start_id
        return min(100, max(0, (done / total) * 100))


class ParsingService:
    """Service for managing parsing jobs."""

    def __init__(self, db: Database):
        self.db = db
        self.match_parser = MatchParser()
        self.team_parser = TeamParser()
        self.roster_parser = RosterParser()

        self._progress = ParsingProgress(
            job_type="",
            start_id=0,
            end_id=0,
            current_id=0
        )
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._current_thread: Optional[threading.Thread] = None
        self._callbacks: list = []

    @property
    def progress(self) -> ParsingProgress:
        return self._progress

    @property
    def is_running(self) -> bool:
        return self._progress.status == "running"

    def add_progress_callback(self, callback: Callable[[ParsingProgress], None]):
        """Add callback to be called on progress updates."""
        self._callbacks.append(callback)

    def _notify_progress(self):
        """Notify all callbacks of progress update."""
        for callback in self._callbacks:
            try:
                callback(self._progress)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")

    def start_parsing_matches(self, start_id: int, end_id: int, skip_existing: bool = True):
        """Start parsing matches in a range."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")

        self._stop_flag.clear()
        self._pause_flag.clear()

        self._progress = ParsingProgress(
            job_type="matches",
            start_id=start_id,
            end_id=end_id,
            current_id=start_id,
            status="running",
            started_at=datetime.now()
        )

        self._current_thread = threading.Thread(
            target=self._parse_matches_worker,
            args=(start_id, end_id, skip_existing),
            daemon=True
        )
        self._current_thread.start()

    def _parse_matches_worker(self, start_id: int, end_id: int, skip_existing: bool):
        """Worker thread for parsing matches."""
        logger.info(f"Starting match parsing from {start_id} to {end_id}")

        try:
            for match_id in range(start_id, end_id + 1):
                # Check for stop/pause
                if self._stop_flag.is_set():
                    self._progress.status = "stopped"
                    break

                while self._pause_flag.is_set():
                    self._progress.status = "paused"
                    self._notify_progress()
                    self._pause_flag.wait(1)

                self._progress.status = "running"
                self._progress.current_id = match_id

                try:
                    with self.db.session() as session:
                        data_service = DataService(session)

                        # Skip if already exists
                        if skip_existing and data_service.match_exists(match_id):
                            logger.debug(f"Match {match_id} already exists, skipping")
                            continue

                        # Parse match
                        match_data = self.match_parser.parse_match(match_id)

                        if match_data:
                            data_service.save_match(match_data)
                            self._progress.total_parsed += 1
                            logger.info(f"Parsed match {match_id}")
                        else:
                            logger.debug(f"Match {match_id} not found or empty")

                except Exception as e:
                    self._progress.total_errors += 1
                    self._progress.last_error = f"Match {match_id}: {str(e)}"
                    logger.error(f"Error parsing match {match_id}: {e}")

                self._notify_progress()

            if not self._stop_flag.is_set():
                self._progress.status = "completed"

        except Exception as e:
            self._progress.status = "failed"
            self._progress.last_error = str(e)
            logger.error(f"Parsing failed: {e}")

        finally:
            self._notify_progress()
            logger.info(f"Parsing finished. Parsed: {self._progress.total_parsed}, Errors: {self._progress.total_errors}")

    def start_parsing_rosters(self, start_id: int, end_id: int):
        """Start parsing rosters (members.php) in a range."""
        if self.is_running:
            raise RuntimeError("Parsing already in progress")

        self._stop_flag.clear()
        self._pause_flag.clear()

        self._progress = ParsingProgress(
            job_type="rosters",
            start_id=start_id,
            end_id=end_id,
            current_id=start_id,
            status="running",
            started_at=datetime.now()
        )

        self._current_thread = threading.Thread(
            target=self._parse_rosters_worker,
            args=(start_id, end_id),
            daemon=True
        )
        self._current_thread.start()

    def _parse_rosters_worker(self, start_id: int, end_id: int):
        """Worker thread for parsing rosters."""
        logger.info(f"Starting roster parsing from {start_id} to {end_id}")

        try:
            for roster_id in range(start_id, end_id + 1):
                if self._stop_flag.is_set():
                    self._progress.status = "stopped"
                    break

                while self._pause_flag.is_set():
                    self._progress.status = "paused"
                    self._notify_progress()
                    self._pause_flag.wait(1)

                self._progress.status = "running"
                self._progress.current_id = roster_id

                try:
                    roster_data = self.roster_parser.parse_roster(roster_id)

                    if roster_data and roster_data.get("players"):
                        with self.db.session() as session:
                            data_service = DataService(session)
                            data_service.save_roster(roster_data)
                            self._progress.total_parsed += 1
                            logger.info(f"Parsed roster {roster_id}")

                except Exception as e:
                    self._progress.total_errors += 1
                    self._progress.last_error = f"Roster {roster_id}: {str(e)}"
                    logger.error(f"Error parsing roster {roster_id}: {e}")

                self._notify_progress()

            if not self._stop_flag.is_set():
                self._progress.status = "completed"

        except Exception as e:
            self._progress.status = "failed"
            self._progress.last_error = str(e)

        finally:
            self._notify_progress()

    def pause(self):
        """Pause current parsing."""
        if self.is_running:
            self._pause_flag.set()

    def resume(self):
        """Resume paused parsing."""
        self._pause_flag.clear()

    def stop(self):
        """Stop current parsing."""
        self._stop_flag.set()
        self._pause_flag.clear()
        if self._current_thread:
            self._current_thread.join(timeout=5)

    def get_stats(self) -> Dict[str, Any]:
        """Get current database statistics."""
        with self.db.session() as session:
            data_service = DataService(session)
            return data_service.get_stats()
