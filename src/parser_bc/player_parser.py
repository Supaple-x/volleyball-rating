"""Parser for BC player pages."""

import re
import logging
from typing import Optional, Dict
from .base_parser import BCBaseParser

logger = logging.getLogger(__name__)


class BCPlayerParser(BCBaseParser):
    """Parser for /season-N/players/{ID} pages."""

    def parse_player(self, season_num: int, player_id: int) -> Optional[Dict]:
        """Parse player detail page - bio + season stats."""
        url = self.get_player_url(season_num, player_id)
        soup = self.fetch_page(url)
        if not soup:
            return None

        title = soup.find('title')
        if title and ('404' in title.get_text() or 'не найден' in title.get_text().lower()):
            return None

        result = {
            "site_id": player_id,
            "last_name": "",
            "first_name": "",
        }

        # Name from h1
        h1 = soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            parsed = self.parse_bc_name(name)
            result["last_name"] = parsed["last_name"]
            result["first_name"] = parsed["first_name"]

        # Photo
        img = soup.find('img', class_='bordered-image')
        if not img:
            # Try finding player photo in any bordered div
            bordered = soup.find('div', class_='bordered-image')
            if bordered:
                img = bordered.find('img')
        if img and img.get('src'):
            src = img['src']
            if not src.startswith('http'):
                src = self.BASE_URL + src
            result["photo_url"] = src

        # Bio from values-table
        info_table = soup.find('table', class_='values-table')
        if info_table:
            for row in info_table.find_all('tr'):
                th = row.find('th')
                td = row.find('td')
                if not th or not td:
                    continue
                key = self.clean_text(th.get_text()).rstrip(':').lower()
                val = self.clean_text(td.get_text())

                if 'команд' in key:
                    team_link = td.find('a', href=True)
                    if team_link:
                        result["team_site_id"] = self.extract_id_from_path(team_link['href'], 'teams')
                        result["team_name"] = self.clean_text(team_link.get_text())
                elif 'должност' in key or 'позици' in key:
                    result["position"] = val
                elif 'рост' in key:
                    try:
                        result["height"] = int(re.search(r'\d+', val).group())
                    except (AttributeError, ValueError):
                        pass
                elif 'вес' in key:
                    try:
                        result["weight"] = int(re.search(r'\d+', val).group())
                    except (AttributeError, ValueError):
                        pass
                elif 'дата рожд' in key or 'рожден' in key:
                    result["birth_date"] = val  # "20.06.2004"

        return result
