"""Parser for team pages."""

import re
import logging
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class TeamParser(BaseParser):
    """Parser for team pages (team.php)."""

    def parse_team(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Parse a team page and return structured data."""
        url = self.get_team_url(team_id)
        soup = self.fetch_page(url)

        if soup is None:
            return None

        if self._is_team_not_found(soup):
            logger.debug(f"Team {team_id} not found")
            return None

        try:
            data = {
                "site_id": team_id,
                "url": url,
                "name": None,
                "organization": None,
                "tournament_history": [],
            }

            # Parse team name
            data["name"] = self._parse_team_name(soup)

            # Parse organization
            data["organization"] = self._parse_organization(soup)

            # Parse tournament history (links to members.php)
            data["tournament_history"] = self._parse_tournament_history(soup)

            return data

        except Exception as e:
            logger.error(f"Error parsing team {team_id}: {e}")
            return None

    def _is_team_not_found(self, soup: BeautifulSoup) -> bool:
        """Check if team page indicates not found."""
        text = soup.get_text().lower()
        return "команда не найдена" in text or "страница не найдена" in text

    def _parse_team_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Parse team name from page."""
        # Usually in a header or bold element
        for tag in ['h1', 'h2', 'h3', 'b', 'strong']:
            elem = soup.find(tag)
            if elem:
                name = self.clean_text(elem.get_text())
                if name and len(name) > 1:
                    return name
        return None

    def _parse_organization(self, soup: BeautifulSoup) -> Optional[str]:
        """Parse organization/school name."""
        # Look for patterns like "СШ" or "Организация"
        text = soup.get_text()
        org_match = re.search(r'(?:СШ|Организация)[:\s]+"?([^"\n]+)', text)
        if org_match:
            return self.clean_text(org_match.group(1))
        return None

    def _parse_tournament_history(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parse tournament history from team page."""
        history = []

        # Find links to members.php (historical rosters)
        for link in soup.find_all('a', href=re.compile(r'members\.php\?id=\d+')):
            roster_id = self.extract_id_from_url(link['href'], 'id')
            text = self.clean_text(link.get_text())

            if roster_id:
                # Try to extract season from text (e.g., "2024/25", "2025-2026")
                season_match = re.search(r'(\d{4})[/-](\d{2,4})', text)
                season = None
                if season_match:
                    start = season_match.group(1)
                    end = season_match.group(2)
                    if len(end) == 2:
                        end = start[:2] + end
                    season = f"{start}-{end}"

                history.append({
                    "roster_id": roster_id,
                    "description": text,
                    "season": season,
                })

        return history
