"""Parser for BC season pages."""

import logging
from typing import Optional, Dict, List
from .base_parser import BCBaseParser

logger = logging.getLogger(__name__)


class BCSeasonParser(BCBaseParser):
    """Parser for season pages (season name, divisions)."""

    def parse_season(self, season_num: int) -> Optional[Dict]:
        """Parse season page to get name and divisions."""
        url = self.get_season_url(season_num)
        soup = self.fetch_page(url)
        if not soup:
            return None

        result = {
            "number": season_num,
            "name": "",
            "divisions": [],
        }

        # Season name from navigation link matching /season-{N}
        # The dropdown contains links like <a href="/season-30">Осень 2025</a>
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.rstrip('/') == f'/season-{season_num}' or href.rstrip('/').endswith(f'/season-{season_num}'):
                text = self.clean_text(link.get_text())
                if text and len(text) > 2 and len(text) < 50:
                    result["name"] = text
                    break

        if not result["name"]:
            result["name"] = f"Season {season_num}"

        return result

    def get_all_season_numbers(self) -> List[int]:
        """Get all available season numbers (1-30+)."""
        url = self.BASE_URL
        soup = self.fetch_page(url)
        if not soup:
            return list(range(1, 31))  # Fallback

        seasons = []
        for link in soup.find_all('a', href=True):
            num = self.extract_season_num(link['href'])
            if num and num not in seasons:
                seasons.append(num)

        return sorted(seasons) if seasons else list(range(1, 31))
