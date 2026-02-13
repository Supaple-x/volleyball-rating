"""Parser for BC schedule pages (championship/cup)."""

import re
import logging
from typing import Optional, List, Dict
from .base_parser import BCBaseParser

logger = logging.getLogger(__name__)


class BCScheduleParser(BCBaseParser):
    """Parser for /season-N/championship/schedule and /season-N/cup/schedule."""

    def parse_schedule(self, season_num: int, tournament_type: str = "championship") -> List[Dict]:
        """Parse schedule page and return list of match stubs.

        Args:
            season_num: Season number (1-30)
            tournament_type: "championship" or "cup"

        Returns:
            List of match dicts with: site_id, date_str, venue, division_name,
            round_name, home_team, away_team, home_score, away_score
        """
        url = self.get_schedule_url(season_num, tournament_type)
        soup = self.fetch_page(url)
        if not soup:
            return []

        matches = []
        current_division = ""
        current_round = ""

        # Find all article sections - divisions contain rounds which contain match tables
        # Structure: <article><header>Division</header><article class="option"><header>Round</header>...
        content = soup.find('div', class_='content')
        if not content:
            content = soup

        # Iterate through all article/header pairs
        for article in content.find_all('article', recursive=True):
            header = article.find('header', recursive=False)
            if not header:
                continue

            header_text = self.clean_text(header.get_text())

            # Check if this is a round (has class 'option') or a division
            if 'option' in (article.get('class') or []):
                current_round = header_text
            else:
                # Could be a division header
                if not article.find('table', recursive=False) and not article.find('article', class_='option', recursive=False):
                    continue
                current_division = header_text

            # Find match table within this article
            table = article.find('table', recursive=False)
            if not table:
                inner_content = article.find('div', class_='content', recursive=False)
                if inner_content:
                    table = inner_content.find('table')
            if not table:
                continue

            tbody = table.find('tbody')
            if not tbody:
                continue

            for row in tbody.find_all('tr'):
                match_data = self._parse_schedule_row(row, current_division, current_round, tournament_type)
                if match_data:
                    matches.append(match_data)

        logger.info(f"Parsed {len(matches)} matches from {tournament_type} schedule for season {season_num}")
        return matches

    def _parse_schedule_row(self, row, division_name: str, round_name: str,
                            tournament_type: str) -> Optional[Dict]:
        """Parse a single match row from the schedule table."""
        tds = row.find_all('td')
        if len(tds) < 5:
            return None

        result = {
            "division_name": division_name,
            "round_name": round_name,
            "tournament_type": tournament_type,
        }

        # Date/time - first td
        date_text = self.clean_text(tds[0].get_text())
        result["date_str"] = date_text
        result["date_time"] = self.parse_bc_date(date_text)

        # Venue - second td
        result["venue"] = self.clean_text(tds[1].get_text())

        # Home team - look for team link in columns
        home_link = None
        away_link = None
        score_link = None

        for td in tds:
            links = td.find_all('a', href=True)
            for link in links:
                href = link['href']
                if '/teams/' in href:
                    if home_link is None:
                        home_link = link
                    elif away_link is None:
                        away_link = link
                elif '/matches/' in href:
                    score_link = link

        if not home_link or not away_link:
            return None

        # Home team
        home_id = self.extract_id_from_path(home_link['href'], 'teams')
        result["home_team"] = {
            "site_id": home_id,
            "name": self.clean_text(home_link.get_text()),
        }

        # Away team
        away_id = self.extract_id_from_path(away_link['href'], 'teams')
        result["away_team"] = {
            "site_id": away_id,
            "name": self.clean_text(away_link.get_text()),
        }

        # Score and match ID
        if score_link:
            match_id = self.extract_id_from_path(score_link['href'], 'matches')
            result["site_id"] = match_id

            score_text = self.clean_text(score_link.get_text())
            score_match = re.match(r'(\d+)\s*[-:]\s*(\d+)', score_text)
            if score_match:
                result["home_score"] = int(score_match.group(1))
                result["away_score"] = int(score_match.group(2))
                result["status"] = "played"
            else:
                result["home_score"] = None
                result["away_score"] = None
                result["status"] = "scheduled"
        else:
            return None  # No match link = no match ID

        return result

    def parse_all_schedules(self, season_num: int) -> List[Dict]:
        """Parse both championship and cup schedules for a season."""
        all_matches = []

        # Championship
        championship = self.parse_schedule(season_num, "championship")
        all_matches.extend(championship)

        # Cup
        cup = self.parse_schedule(season_num, "cup")
        all_matches.extend(cup)

        logger.info(f"Total matches for season {season_num}: {len(all_matches)} "
                     f"(championship: {len(championship)}, cup: {len(cup)})")
        return all_matches
