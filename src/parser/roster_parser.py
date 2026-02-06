"""Parser for roster pages (members.php)."""

import re
import logging
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class RosterParser(BaseParser):
    """Parser for roster pages (members.php)."""

    def parse_roster(self, roster_id: int) -> Optional[Dict[str, Any]]:
        """Parse a roster page and return structured data."""
        url = self.get_roster_url(roster_id)
        soup = self.fetch_page(url)

        if soup is None:
            return None

        if self._is_roster_not_found(soup):
            logger.debug(f"Roster {roster_id} not found")
            return None

        try:
            data = {
                "roster_id": roster_id,
                "url": url,
                "team": None,
                "tournament": None,
                "season": None,
                "league": None,
                "players": [],
                "avg_height": None,
                "avg_age": None,
            }

            # Parse team info
            data["team"] = self._parse_team_info(soup)

            # Parse tournament info
            tournament_data = self._parse_tournament_info(soup)
            data.update(tournament_data)

            # Parse players
            data["players"] = self._parse_players(soup)

            # Parse stats
            stats = self._parse_stats(soup)
            data.update(stats)

            return data

        except Exception as e:
            logger.error(f"Error parsing roster {roster_id}: {e}")
            return None

    def _is_roster_not_found(self, soup: BeautifulSoup) -> bool:
        """Check if roster page indicates not found."""
        text = soup.get_text().lower()
        return "состав не найден" in text or "страница не найдена" in text

    def _parse_team_info(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Parse team information from roster page."""
        # Look for team link
        team_link = soup.find('a', href=re.compile(r'team\.php\?id=\d+'))
        if team_link:
            return {
                "site_id": self.extract_id_from_url(team_link['href'], 'id'),
                "name": self.clean_text(team_link.get_text())
            }
        return None

    def _parse_tournament_info(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Parse tournament and season information."""
        data = {
            "tournament": None,
            "season": None,
            "league": None,
        }

        text = soup.get_text()

        # Look for season pattern
        season_match = re.search(r'[Сс]езон[:\s]+(\d{4}[/-]\d{2,4})', text)
        if season_match:
            data["season"] = season_match.group(1)

        # Look for league
        league_match = re.search(r'([Сс]уперлига|[Вв]ысшая\s+лига|[Пп]ервая\s+лига|[Лл]ига\s+\d+)', text)
        if league_match:
            data["league"] = league_match.group(1)

        # Look for tournament name
        for header in soup.find_all(['h1', 'h2', 'h3', 'title']):
            header_text = self.clean_text(header.get_text())
            if 'турнир' in header_text.lower():
                data["tournament"] = header_text
                break

        return data

    def _parse_players(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parse player list from roster page."""
        players = []

        # Find all player photo images (ID in URL like /uploads/player/t/50478.jpeg)
        for img in soup.find_all('img', src=re.compile(r'/uploads/player/t/')):
            src = img.get('src', '')
            # Extract ID from URL (handles both 50478.jpeg and 2337_50f2aae6a1b04.jpg)
            id_match = re.search(r'/uploads/player/t/(\d+)', src)
            if not id_match:
                continue

            player_id = int(id_match.group(1))
            # Build full photo URL
            photo_url = f"https://volleymsk.ru{src}" if src.startswith('/') else src

            # Find the parent row containing player info
            parent_row = img.find_parent('tr')
            if not parent_row:
                continue

            player_data = {
                "site_id": player_id,
                "photo_url": photo_url,
                "first_name": None,
                "last_name": None,
                "middle_name": None,
                "height": None,
                "position": None,
                "birth_year": None,
                "jersey_number": None,
            }

            # Find nested table with player details
            nested_table = parent_row.find('table')
            if nested_table:
                # Parse name from <strong> tag with line breaks
                name_tag = nested_table.find('strong')
                if name_tag:
                    # Get all text nodes separated by <br>
                    name_parts = []
                    for elem in name_tag.children:
                        if isinstance(elem, str):
                            text = elem.strip()
                            if text:
                                name_parts.append(text)

                    # Usually: last_name, first_name, patronymic
                    if len(name_parts) >= 1:
                        player_data["last_name"] = name_parts[0]
                    if len(name_parts) >= 2:
                        player_data["first_name"] = name_parts[1]
                    if len(name_parts) >= 3:
                        player_data["middle_name"] = name_parts[2]

                # Parse height and birth year from text
                text = nested_table.get_text()

                # Height: "Рост: 185"
                height_match = re.search(r'Рост[:\s]*(\d{3})', text)
                if height_match:
                    height = int(height_match.group(1))
                    if 150 <= height <= 230:
                        player_data["height"] = height

                # Birth year: "Год рожд: 1986"
                year_match = re.search(r'Год\s*рожд[:\s]*(19|20)\d{2}', text)
                if year_match:
                    full_match = re.search(r'Год\s*рожд[:\s]*(\d{4})', text)
                    if full_match:
                        player_data["birth_year"] = int(full_match.group(1))

                # Position (if present)
                for pos in ['Связующий', 'Диагональ', 'Доигровщик', 'Центральный',
                           'Либеро', 'ЛБ', 'СВ', 'ДИ', 'ДО', 'ЦБ']:
                    if pos in text:
                        player_data["position"] = pos
                        break

            # Only add if we have at least ID and name
            if player_data["last_name"] or player_data["first_name"]:
                players.append(player_data)

        return players

    def _parse_stats(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Parse aggregate stats (average height, age)."""
        data = {
            "avg_height": None,
            "avg_age": None,
        }

        text = soup.get_text()

        # Average height
        height_match = re.search(r'[Сс]редний\s+рост[:\s]+(\d+)', text)
        if height_match:
            data["avg_height"] = int(height_match.group(1))

        # Average age
        age_match = re.search(r'[Сс]редний\s+возраст[:\s]+([\d.]+)', text)
        if age_match:
            data["avg_age"] = float(age_match.group(1))

        return data
