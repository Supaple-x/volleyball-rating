"""Parser for BC team pages."""

import re
import logging
from typing import Optional, List, Dict
from .base_parser import BCBaseParser

logger = logging.getLogger(__name__)


class BCTeamParser(BCBaseParser):
    """Parser for /season-N/teams and /season-N/teams/{ID} pages."""

    def parse_teams_listing(self, season_num: int) -> List[Dict]:
        """Parse teams listing page - all teams grouped by division with standings.

        Returns list of dicts: {division_name, teams: [{site_id, name, games, wins, losses, points, is_women}]}
        """
        url = self.get_teams_url(season_num)
        soup = self.fetch_page(url)
        if not soup:
            return []

        divisions = []
        current_division = None

        # The page has team cards grouped by division
        # Look for structure with division headings and team links
        content = soup.find('div', class_='content')
        if not content:
            content = soup

        # Find all team links to extract team IDs and names
        all_teams = []
        seen_teams = set()

        for link in content.find_all('a', href=True):
            if '/teams/' not in link['href']:
                continue
            team_id = self.extract_id_from_path(link['href'], 'teams')
            if not team_id or team_id in seen_teams:
                continue

            name = self.clean_text(link.get_text())
            if not name or len(name) < 2:
                continue

            seen_teams.add(team_id)
            is_women = name.endswith('(ж)') or '(ж)' in name
            all_teams.append({
                "site_id": team_id,
                "name": name.replace('(ж)', '').strip(),
                "is_women": is_women,
            })

        logger.info(f"Found {len(all_teams)} teams for season {season_num}")
        return all_teams

    def parse_team_detail(self, season_num: int, team_id: int) -> Optional[Dict]:
        """Parse team detail page - roster with stats."""
        url = self.get_team_url(season_num, team_id)
        soup = self.fetch_page(url)
        if not soup:
            return None

        result = {
            "site_id": team_id,
            "name": "",
            "players": [],
            "standings": {},
        }

        # Team name from h1
        h1 = soup.find('h1')
        if h1:
            result["name"] = self.clean_text(h1.get_text())

        # Basic info from values-table
        info_table = soup.find('table', class_='values-table')
        if info_table:
            for row in info_table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if not th or not td:
                    continue
                key = self.clean_text(th.get_text()).rstrip(':').lower()
                val = self.clean_text(td.get_text())

                if 'позиция' in key:
                    result["standings"]["position"] = val
                elif 'игр' in key:
                    try:
                        result["standings"]["games"] = int(val)
                    except ValueError:
                        pass
                elif 'побед' in key:
                    try:
                        result["standings"]["wins"] = int(val)
                    except ValueError:
                        pass
                elif 'поражен' in key:
                    try:
                        result["standings"]["losses"] = int(val)
                    except ValueError:
                        pass

        # Player roster from stats table
        for section in soup.find_all('section'):
            header = section.find('header')
            if not header:
                continue
            header_text = header.get_text().lower()
            if 'статистика' not in header_text and 'состав' not in header_text:
                continue

            table = section.find('table', class_='ruler')
            if not table:
                continue

            tbody = table.find('tbody')
            if not tbody:
                continue

            for row in tbody.find_all('tr'):
                tds = row.find_all('td')
                if len(tds) < 3:
                    continue

                player = {}
                # Find player link
                player_link = row.find('a', href=lambda h: h and '/players/' in h)
                if player_link:
                    player["site_id"] = self.extract_id_from_path(player_link['href'], 'players')
                    player["name"] = self.clean_text(player_link.get_text())
                else:
                    continue

                # Stats columns: games, points, attacks, serves, blocks
                stat_tds = [td for td in tds if not td.find('a')]
                for i, td in enumerate(stat_tds):
                    text = td.get_text(strip=True)
                    try:
                        val = int(text)
                    except ValueError:
                        continue
                    if i == 0:
                        player["games"] = val
                    elif i == 1:
                        player["points"] = val
                    elif i == 2:
                        player["attacks"] = val
                    elif i == 3:
                        player["serves"] = val
                    elif i == 4:
                        player["blocks"] = val

                result["players"].append(player)

        return result
