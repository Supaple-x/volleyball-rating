"""Base parser with common functionality."""

import time
import logging
import requests
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class BaseParser:
    """Base class for all parsers."""

    BASE_URL = "https://volleymsk.ru"
    RATE_LIMIT = 0.05  # seconds between requests (50ms)

    def __init__(self, rate_limit: float = None):
        self.rate_limit = rate_limit or self.RATE_LIMIT
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        })
        self._last_request_time = 0

    def _wait_rate_limit(self):
        """Wait to respect rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

    def fetch_page(self, url: str, timeout: int = 30) -> Optional[BeautifulSoup]:
        """Fetch a page and return BeautifulSoup object."""
        self._wait_rate_limit()

        try:
            response = self.session.get(url, timeout=timeout)
            self._last_request_time = time.time()

            response.raise_for_status()

            # Site uses windows-1251 encoding
            response.encoding = 'windows-1251'

            soup = BeautifulSoup(response.text, 'lxml')
            return soup

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def get_match_url(self, match_id: int) -> str:
        """Get URL for a match page."""
        return f"{self.BASE_URL}/ap/match.php?match_id={match_id}"

    def get_team_url(self, team_id: int) -> str:
        """Get URL for a team page."""
        return f"{self.BASE_URL}/ap/team.php?id={team_id}"

    def get_roster_url(self, roster_id: int) -> str:
        """Get URL for a roster page (members.php)."""
        return f"{self.BASE_URL}/ap/members.php?id={roster_id}"

    def get_player_url(self, player_id: int) -> str:
        """Get URL for a player page."""
        return f"{self.BASE_URL}/ap/player.php?id={player_id}"

    def get_schedule_url(self, schedule_id: int) -> str:
        """Get URL for schedule page (rasp.php)."""
        return f"{self.BASE_URL}/ap/rasp.php?id={schedule_id}"

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        return " ".join(text.split()).strip()

    @staticmethod
    def parse_name(full_name: str) -> dict:
        """Parse full name into components (Фамилия Имя Отчество)."""
        parts = full_name.strip().split()
        result = {
            "last_name": "",
            "first_name": "",
            "patronymic": None
        }

        if len(parts) >= 1:
            result["last_name"] = parts[0]
        if len(parts) >= 2:
            result["first_name"] = parts[1]
        if len(parts) >= 3:
            result["patronymic"] = parts[2]

        return result

    @staticmethod
    def extract_id_from_url(url: str, param: str = "id") -> Optional[int]:
        """Extract ID parameter from URL."""
        if not url:
            return None

        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        if param in params:
            try:
                return int(params[param][0])
            except (ValueError, IndexError):
                pass

        return None
