"""Parser for match pages."""

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup, Tag

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class MatchParser(BaseParser):
    """Parser for match pages (match.php)."""

    def parse_match(self, match_id: int) -> Optional[Dict[str, Any]]:
        """Parse a match page and return structured data."""
        url = self.get_match_url(match_id)
        soup = self.fetch_page(url)

        if soup is None:
            return None

        # Check if match exists
        if self._is_match_not_found(soup):
            logger.debug(f"Match {match_id} not found")
            return None

        try:
            data = {
                "site_id": match_id,
                "url": url,
                "raw_html": str(soup),
            }

            # Find the main match info table (gray background table)
            main_table = self._find_main_table(soup)

            if main_table:
                # Parse all data from the main table
                table_data = self._parse_main_table(main_table)
                data.update(table_data)

            # Parse header for date/time if not found in table
            if not data.get("date_time"):
                header_data = self._parse_header(soup)
                data.update({k: v for k, v in header_data.items() if not data.get(k)})

            # Parse team rosters from separate tables
            rosters = self._parse_rosters(soup, data.get("home_team"), data.get("away_team"))
            data["home_roster"] = rosters.get("home", [])
            data["away_roster"] = rosters.get("away", [])

            # Determine match status
            data["status"] = self._determine_status(data)

            return data

        except Exception as e:
            logger.error(f"Error parsing match {match_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _is_match_not_found(self, soup: BeautifulSoup) -> bool:
        """Check if the match page indicates match not found."""
        text = soup.get_text().lower()
        return "матч не найден" in text or "страница не найдена" in text

    def _find_main_table(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Find the main table with match info (gray background table)."""
        # Look for table with bgcolor="#CCCCCC" which contains match results
        for table in soup.find_all('table', bgcolor="#CCCCCC"):
            text = table.get_text()
            if 'Результат матча' in text:
                return table
        return None

    def _parse_main_table(self, table: Tag) -> Dict[str, Any]:
        """Parse all data from the main match table."""
        data = {
            "home_team": None,
            "away_team": None,
            "home_score": None,
            "away_score": None,
            "set_scores": None,
            "date_time": None,
            "tournament_path": None,
            "referee": None,
            "referee_rating_home": None,
            "referee_rating_away": None,
            "referee_rating_home_text": None,
            "referee_rating_away_text": None,
            "best_players": [],
        }

        rows = table.find_all('tr')

        for i, row in enumerate(rows):
            cells = row.find_all('td')
            if not cells:
                continue

            # Get text content
            first_cell_text = self.clean_text(cells[0].get_text()) if cells else ""
            second_cell_text = self.clean_text(cells[1].get_text()) if len(cells) > 1 else ""

            # Tournament path (first row with link to trntable.php)
            link = row.find('a', href=re.compile(r'trntable\.php'))
            if link and '>' in link.get_text():
                data["tournament_path"] = self.clean_text(link.get_text())

            # Date/time row (format: "26.01.2026, 20:00")
            date_match = re.search(r'(\d{2}\.\d{2}\.\d{4}),?\s*(\d{2}:\d{2})', first_cell_text)
            if date_match:
                try:
                    data["date_time"] = datetime.strptime(
                        f"{date_match.group(1)} {date_match.group(2)}", "%d.%m.%Y %H:%M"
                    )
                except ValueError:
                    pass

            # Result row (contains team links and score)
            if 'Результат матча' in first_cell_text:
                # Next row should have teams and score
                continue

            # Teams and score row
            team_links = row.find_all('a', href=re.compile(r'team\.php\?id=\d+'))
            if len(team_links) >= 2:
                # Home team
                home_id = self.extract_id_from_url(team_links[0]['href'], 'id')
                home_name = self.clean_text(team_links[0].get_text())
                data["home_team"] = {"site_id": home_id, "name": home_name}

                # Away team
                away_id = self.extract_id_from_url(team_links[1]['href'], 'id')
                away_name = self.clean_text(team_links[1].get_text())
                data["away_team"] = {"site_id": away_id, "name": away_name}

                # Score (in second cell or after teams)
                if len(cells) > 1:
                    score_text = cells[1].get_text()
                    # Main score pattern: "1 - 3"
                    score_match = re.search(r'(\d+)\s*-\s*(\d+)', score_text)
                    if score_match:
                        data["home_score"] = int(score_match.group(1))
                        data["away_score"] = int(score_match.group(2))

                    # Set scores pattern: "(19:25, 19:25, 25:19, 21:25)"
                    sets_match = re.search(r'\(([^)]+)\)', score_text)
                    if sets_match:
                        data["set_scores"] = sets_match.group(1)

            # Referee row
            if 'Первый судья' in first_cell_text:
                if second_cell_text:
                    data["referee"] = self.parse_name(second_cell_text)

            # Referee rating row
            if 'Оценка судейства' in first_cell_text:
                rating_text = second_cell_text

                # Parse "Гости: 4 отличное, идеальное судейство"
                guests_match = re.search(r'Гости[:\s]*(\d+)\s*([^Х\d]*)', rating_text)
                if guests_match:
                    data["referee_rating_away"] = int(guests_match.group(1))
                    data["referee_rating_away_text"] = self.clean_text(guests_match.group(2))

                # Parse "Хозяева: 4 отличное, идеальное судейство"
                hosts_match = re.search(r'Хозяева[:\s]*(\d+)\s*(.*)$', rating_text)
                if hosts_match:
                    data["referee_rating_home"] = int(hosts_match.group(1))
                    data["referee_rating_home_text"] = self.clean_text(hosts_match.group(2))

            # Best players section
            if 'Лучшие игроки' in first_cell_text:
                # Next rows contain best players
                continue

            # Best player row (team name in first cell, player name in second)
            # Skip if second_cell contains score pattern or is empty
            if second_cell_text and not re.match(r'^\d+\s*-\s*\d+', second_cell_text) and 'Лучшие' not in second_cell_text:
                if data.get("home_team") and data["home_team"]["name"] == first_cell_text:
                    data["best_players"].append({
                        "team": data["home_team"].copy(),
                        "player": self.parse_name(second_cell_text)
                    })
                elif data.get("away_team") and data["away_team"]["name"] == first_cell_text:
                    data["best_players"].append({
                        "team": data["away_team"].copy(),
                        "player": self.parse_name(second_cell_text)
                    })

        return data

    def _parse_header(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Parse match header (fallback for date/time and teams)."""
        data = {
            "home_team": None,
            "away_team": None,
            "date_time": None,
        }

        # Look for title or header with ::: markers
        title_pattern = re.compile(r':::\s*(.+?)\s*-\s*(.+?),\s*(\d{2}\.\d{2}\.\d{4}),\s*(\d{2}:\d{2})\s*:::')

        for text_node in soup.find_all(string=title_pattern):
            match = title_pattern.search(text_node)
            if match:
                home_name, away_name, date_str, time_str = match.groups()
                data["home_team"] = {"name": self.clean_text(home_name)}
                data["away_team"] = {"name": self.clean_text(away_name)}

                try:
                    data["date_time"] = datetime.strptime(
                        f"{date_str} {time_str}", "%d.%m.%Y %H:%M"
                    )
                except ValueError:
                    pass
                break

        # Extract team IDs from links if not found
        if data["home_team"] and not data["home_team"].get("site_id"):
            for link in soup.find_all('a', href=re.compile(r'team\.php\?id=\d+')):
                team_id = self.extract_id_from_url(link['href'], 'id')
                team_name = self.clean_text(link.get_text())

                if team_id and team_name:
                    if data["home_team"] and team_name == data["home_team"].get("name"):
                        data["home_team"]["site_id"] = team_id
                    elif data["away_team"] and team_name == data["away_team"].get("name"):
                        data["away_team"]["site_id"] = team_id

        return data

    def _parse_rosters(self, soup: BeautifulSoup, home_team: dict, away_team: dict) -> Dict[str, List]:
        """Parse team rosters from the match page."""
        rosters = {"home": [], "away": []}

        if not home_team or not away_team:
            return rosters

        home_name = home_team.get("name", "")
        away_name = away_team.get("name", "")

        # Find the roster table (second table with bgcolor="#CCCCCC", after main results table)
        tables = soup.find_all('table', bgcolor="#CCCCCC")

        for table in tables:
            text = table.get_text()

            # Skip the main info table
            if 'Результат матча' in text:
                continue

            # This should be the roster table - it has two columns with team names
            # Structure: <tr><td>INEX team</td><td>КПРФ Москва</td></tr>
            # Then player rows with nested tables

            # Find the header row with team names
            first_row = table.find('tr')
            if not first_row:
                continue

            cells = first_row.find_all('td')
            if len(cells) != 2:
                continue

            # Check if this is roster table by looking for team names in header
            cell_texts = [self.clean_text(c.get_text()) for c in cells]
            if home_name not in cell_texts and away_name not in cell_texts:
                continue

            # Determine column positions
            home_col = 0 if home_name in cell_texts[0] else 1
            away_col = 1 - home_col

            # Find the data row (second row with nested tables)
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue

            data_row = rows[1]
            data_cells = data_row.find_all('td', recursive=False)

            if len(data_cells) < 2:
                continue

            # Parse each team's players from nested tables
            for col_idx, team_key in [(home_col, "home"), (away_col, "away")]:
                if col_idx >= len(data_cells):
                    continue

                cell = data_cells[col_idx]
                nested_table = cell.find('table')

                if not nested_table:
                    continue

                # Each row in nested table has: photo cell, name cell
                for player_row in nested_table.find_all('tr'):
                    player_cells = player_row.find_all('td')
                    if len(player_cells) < 2:
                        continue

                    # Extract player ID and photo URL: /uploads/player/t/778979.PNG
                    img = player_cells[0].find('img')
                    player_id = None
                    photo_url = None
                    if img and img.get('src'):
                        src = img['src']
                        id_match = re.search(r'/uploads/player/t/(\d+)', src)
                        if id_match:
                            player_id = int(id_match.group(1))
                            # Build full photo URL
                            photo_url = f"https://volleymsk.ru{src}" if src.startswith('/') else src

                    # Extract player name from second cell
                    player_name = self.clean_text(player_cells[1].get_text())

                    if player_id and player_name:
                        rosters[team_key].append({
                            "site_id": player_id,
                            "photo_url": photo_url,
                            **self.parse_name(player_name)
                        })

            break  # Found roster table, no need to continue

        return rosters

    def _determine_status(self, data: Dict[str, Any]) -> str:
        """Determine match status based on parsed data."""
        if data.get("home_score") is not None and data.get("away_score") is not None:
            return "played"
        elif data.get("date_time"):
            if data["date_time"] > datetime.now():
                return "scheduled"
            else:
                return "unknown"
        return "unknown"

    def find_max_match_id(self, start_from: int = 50000, step: int = 1000) -> int:
        """Find approximate maximum match_id by binary search."""
        logger.info("Searching for maximum match_id...")

        upper = start_from
        while True:
            url = self.get_match_url(upper)
            soup = self.fetch_page(url)
            if soup and not self._is_match_not_found(soup):
                upper += step
            else:
                break

        lower = max(1, upper - step)

        while lower < upper - 1:
            mid = (lower + upper) // 2
            url = self.get_match_url(mid)
            soup = self.fetch_page(url)

            if soup and not self._is_match_not_found(soup):
                lower = mid
            else:
                upper = mid

        logger.info(f"Maximum match_id found: approximately {lower}")
        return lower
