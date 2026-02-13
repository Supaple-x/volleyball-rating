"""Parser for BC match detail pages."""

import re
import logging
from typing import Optional, Dict, List
from .base_parser import BCBaseParser

logger = logging.getLogger(__name__)


class BCMatchParser(BCBaseParser):
    """Parser for /season-N/matches/{ID} pages."""

    def parse_match(self, season_num: int, match_id: int) -> Optional[Dict]:
        """Parse full match detail page."""
        url = self.get_match_url(season_num, match_id)
        soup = self.fetch_page(url)
        if not soup:
            return None

        # Check for 404 / empty page
        title = soup.find('title')
        if title and ('404' in title.get_text() or 'не найден' in title.get_text().lower()):
            return None

        result = {
            "site_id": match_id,
            "season_num": season_num,
        }

        # Parse match header (score, teams, date)
        self._parse_header(soup, result)

        # Parse set scores table
        self._parse_set_scores(soup, result)

        # Parse best players
        result["best_players"] = self._parse_best_players(soup)

        # Parse team stats (player stats per team)
        result["home_stats"], result["away_stats"] = self._parse_team_stats(soup)

        # Parse referees
        result["referees"] = self._parse_referees(soup)

        return result

    def _parse_header(self, soup, result: Dict):
        """Parse match header: score, teams, division, date."""
        # Score from .score div
        score_div = soup.find('div', class_='score')
        if score_div:
            spans = score_div.find_all('span')
            if len(spans) >= 2:
                try:
                    result["home_score"] = int(spans[0].get_text(strip=True))
                    result["away_score"] = int(spans[1].get_text(strip=True))
                    result["status"] = "played"
                except ValueError:
                    result["status"] = "unknown"

        # Team names from .team-name divs or team links
        team_links = []
        for div in soup.find_all('div', class_='team-name'):
            link = div.find('a', href=True)
            if link:
                team_links.append(link)

        # Fallback: look for command-block links
        if len(team_links) < 2:
            team_links = []
            for div in soup.find_all('div', class_='command-block'):
                link = div.find('a', href=True)
                if link and '/teams/' in link['href']:
                    team_links.append(link)

        # If still not enough, try any team links in the title area
        if len(team_links) < 2:
            title_div = soup.find('div', class_='title')
            if title_div:
                team_links = [a for a in title_div.find_all('a', href=True)
                              if '/teams/' in a['href']]

        if len(team_links) >= 2:
            result["home_team"] = {
                "site_id": self.extract_id_from_path(team_links[0]['href'], 'teams'),
                "name": self.clean_text(team_links[0].get_text()),
            }
            result["away_team"] = {
                "site_id": self.extract_id_from_path(team_links[1]['href'], 'teams'),
                "name": self.clean_text(team_links[1].get_text()),
            }

        # Division and round from "text-center bold clear" div
        bold_div = soup.find('div', class_=lambda c: c and 'bold' in c and 'clear' in c)
        if bold_div:
            text = self.clean_text(bold_div.get_text())
            # "Кварц - Тур 3"
            parts = text.split(' - ', 1)
            result["division_name"] = parts[0].strip() if parts else text
            result["round_name"] = parts[1].strip() if len(parts) > 1 else ""

        # Date/time from text-center div (after the bold div)
        for div in soup.find_all('div', class_='text-center'):
            text = self.clean_text(div.get_text())
            if re.search(r'\d{4}\s+года', text) or re.search(r'\d{2}:\d{2}\s*мск', text):
                result["date_time"] = self.parse_bc_date(text)
                break

    def _parse_set_scores(self, soup, result: Dict):
        """Parse set-by-set scores from score-table."""
        score_table_div = soup.find('div', class_='score-table')
        if not score_table_div:
            return

        table = score_table_div.find('table')
        if not table:
            return

        rows = table.find_all('tr')
        if len(rows) < 2:
            return

        set_scores = []
        home_total = None
        away_total = None

        for i, row in enumerate(rows[:2]):
            tds = row.find_all('td')
            scores = []
            for td in tds:
                # Skip team name td (has a link or class 'name')
                if td.find('a') or 'name' in (td.get('class') or []):
                    continue
                text = td.get_text(strip=True)
                if text.isdigit():
                    if 'final-score' in (td.get('class') or []):
                        if i == 0:
                            home_total = int(text)
                        else:
                            away_total = int(text)
                    else:
                        scores.append(int(text))

            if i == 0:
                home_sets = scores
            else:
                away_sets = scores

        # Build set_scores string like "25:20, 17:25, 15:13"
        if home_sets and away_sets and len(home_sets) == len(away_sets):
            set_scores = [f"{h}:{a}" for h, a in zip(home_sets, away_sets)]
            result["set_scores"] = ", ".join(set_scores)

        result["home_total_points"] = home_total
        result["away_total_points"] = away_total

    def _parse_best_players(self, soup) -> List[Dict]:
        """Parse best players section."""
        best_players = []

        # Find section with "Лучшие игроки" header
        for section in soup.find_all('section'):
            header = section.find('header')
            if not header or 'лучши' not in header.get_text().lower():
                continue

            # Find player cards
            for div in section.find_all('div', class_='bordered'):
                player_link = div.find('a', class_='blue')
                if not player_link:
                    player_link = div.find('a', href=lambda h: h and '/players/' in h)
                if not player_link:
                    continue

                bp = {
                    "player_site_id": self.extract_id_from_path(player_link['href'], 'players'),
                    "player_name": self.clean_text(player_link.get_text()),
                }
                best_players.append(bp)

            # Parse stats from best-table
            best_table = section.find('table', class_='best-table')
            if best_table and len(best_players) >= 2:
                rows = best_table.find_all('tr')
                for row in rows:
                    tds = row.find_all('td')
                    th = row.find('th')
                    if not th or len(tds) < 2:
                        continue
                    stat_name = self.clean_text(th.get_text()).lower()
                    try:
                        left_val = int(tds[0].get_text(strip=True))
                        right_val = int(tds[1].get_text(strip=True))
                    except (ValueError, IndexError):
                        continue

                    key = None
                    if 'очк' in stat_name:
                        key = 'points'
                    elif 'подач' in stat_name:
                        key = 'serves'
                    elif 'атак' in stat_name:
                        key = 'attacks'
                    elif 'блок' in stat_name:
                        key = 'blocks'

                    if key:
                        best_players[0][key] = left_val
                        best_players[-1][key] = right_val

            break

        return best_players

    def _parse_team_stats(self, soup) -> tuple:
        """Parse per-team player statistics tables.

        Returns (home_stats, away_stats) - each is a list of dicts.
        """
        home_stats = []
        away_stats = []
        stats_tables = []

        for section in soup.find_all('section'):
            header = section.find('header')
            if not header or 'статистика команды' not in header.get_text().lower():
                continue

            table = section.find('table', class_='ruler')
            if table:
                stats_tables.append(table)

        for idx, table in enumerate(stats_tables[:2]):
            tbody = table.find('tbody')
            if not tbody:
                continue

            players = []
            for row in tbody.find_all('tr'):
                tds = row.find_all('td')
                if len(tds) < 5:
                    continue

                player = {}

                # Jersey number
                try:
                    player["jersey_number"] = int(tds[0].get_text(strip=True))
                except ValueError:
                    player["jersey_number"] = None

                # Player name and ID
                player_link = tds[1].find('a', href=True)
                if player_link:
                    player["player_site_id"] = self.extract_id_from_path(player_link['href'], 'players')
                    player["player_name"] = self.clean_text(player_link.get_text())
                else:
                    player["player_name"] = self.clean_text(tds[1].get_text())
                    player["player_site_id"] = None

                # Stats: points, attacks, serves, blocks
                try:
                    player["points"] = int(tds[2].get_text(strip=True)) if tds[2].get_text(strip=True) else 0
                except ValueError:
                    player["points"] = 0
                try:
                    player["attacks"] = int(tds[3].get_text(strip=True)) if tds[3].get_text(strip=True) else 0
                except ValueError:
                    player["attacks"] = 0
                try:
                    player["serves"] = int(tds[4].get_text(strip=True)) if tds[4].get_text(strip=True) else 0
                except ValueError:
                    player["serves"] = 0
                try:
                    player["blocks"] = int(tds[5].get_text(strip=True)) if len(tds) > 5 and tds[5].get_text(strip=True) else 0
                except (ValueError, IndexError):
                    player["blocks"] = 0

                players.append(player)

            if idx == 0:
                home_stats = players
            else:
                away_stats = players

        return home_stats, away_stats

    def _parse_referees(self, soup) -> List[Dict]:
        """Parse referee section."""
        referees = []

        for section in soup.find_all('section'):
            header = section.find('header')
            if not header or 'судей' not in header.get_text().lower():
                continue

            for link in section.find_all('a', href=True):
                if '/referees/' in link['href']:
                    ref_id = self.extract_id_from_path(link['href'], 'referees')
                    ref_name = self.clean_text(link.get_text())
                    if ref_id and ref_name:
                        parsed = self.parse_bc_name(ref_name)
                        referees.append({
                            "site_id": ref_id,
                            "name": ref_name,
                            "last_name": parsed["last_name"],
                            "first_name": parsed["first_name"],
                        })
            break

        return referees
