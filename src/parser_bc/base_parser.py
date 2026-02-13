"""Base parser for volleyball.businesschampions.ru."""

import re
import time
import logging
import requests
from typing import Optional
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RUSSIAN_MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
}


class BCBaseParser:
    """Base class for Business Champions League parsers."""

    BASE_URL = "https://volleyball.businesschampions.ru"
    RATE_LIMIT = 0.1  # 100ms between requests

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
        """Fetch a page and return BeautifulSoup object. UTF-8 encoding."""
        self._wait_rate_limit()
        try:
            response = self.session.get(url, timeout=timeout)
            self._last_request_time = time.time()
            response.raise_for_status()
            response.encoding = 'utf-8'
            return BeautifulSoup(response.text, 'lxml')
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    # URL helpers
    def get_season_url(self, season_num: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}"

    def get_schedule_url(self, season_num: int, tournament_type: str = "championship") -> str:
        return f"{self.BASE_URL}/season-{season_num}/{tournament_type}/schedule"

    def get_match_url(self, season_num: int, match_id: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}/matches/{match_id}"

    def get_teams_url(self, season_num: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}/teams"

    def get_team_url(self, season_num: int, team_id: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}/teams/{team_id}"

    def get_player_url(self, season_num: int, player_id: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}/players/{player_id}"

    def get_referees_url(self, season_num: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}/referees"

    def get_referee_url(self, season_num: int, referee_id: int) -> str:
        return f"{self.BASE_URL}/season-{season_num}/referees/{referee_id}"

    @staticmethod
    def extract_id_from_path(url: str, entity: str) -> Optional[int]:
        """Extract entity ID from path-based URL like /season-30/players/7561."""
        if not url:
            return None
        match = re.search(rf'/{entity}/(\d+)', url)
        return int(match.group(1)) if match else None

    @staticmethod
    def extract_season_num(url: str) -> Optional[int]:
        """Extract season number from URL."""
        if not url:
            return None
        match = re.search(r'/season-(\d+)', url)
        return int(match.group(1)) if match else None

    @staticmethod
    def parse_bc_name(full_name: str) -> dict:
        """Parse 'Фамилия Имя' format (no patronymic in BC)."""
        parts = full_name.strip().split()
        return {
            "last_name": parts[0] if parts else "",
            "first_name": parts[1] if len(parts) > 1 else "",
        }

    @staticmethod
    def parse_bc_date(date_str: str) -> Optional[datetime]:
        """Parse BC date formats.
        Formats:
        - '26 Октября 2025 года Вс, 11:00 мск'
        - '11.10.2025 (Сб) - 10:00'
        - '11.10.2025'
        """
        if not date_str:
            return None
        date_str = date_str.strip()

        # Format: "11.10.2025 (Сб) - 10:00"
        m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})\s*(?:\([^)]*\))?\s*-?\s*(\d{2}):(\d{2})', date_str)
        if m:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                                int(m.group(4)), int(m.group(5)))
            except ValueError:
                pass

        # Format: "11.10.2025"
        m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
        if m:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        # Format: "26 Октября 2025 года Вс, 11:00 мск"
        m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})\s+года\s+\w+,?\s*(\d{2}):(\d{2})', date_str)
        if m:
            month = RUSSIAN_MONTHS.get(m.group(2).lower())
            if month:
                try:
                    return datetime(int(m.group(3)), month, int(m.group(1)),
                                    int(m.group(4)), int(m.group(5)))
                except ValueError:
                    pass

        # Format: "26 Октября 2025 года"
        m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str)
        if m:
            month = RUSSIAN_MONTHS.get(m.group(2).lower())
            if month:
                try:
                    return datetime(int(m.group(3)), month, int(m.group(1)))
                except ValueError:
                    pass

        logger.warning(f"Could not parse date: {date_str}")
        return None

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        return " ".join(text.split()).strip()
