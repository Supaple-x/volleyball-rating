"""Parser for BC referee pages."""

import re
import logging
from typing import Optional, List, Dict
from .base_parser import BCBaseParser

logger = logging.getLogger(__name__)


class BCRefereeParser(BCBaseParser):
    """Parser for /season-N/referees and /season-N/referees/{ID} pages."""

    def parse_referees_listing(self, season_num: int) -> List[Dict]:
        """Parse referees listing page."""
        url = self.get_referees_url(season_num)
        soup = self.fetch_page(url)
        if not soup:
            return []

        referees = []
        seen_ids = set()

        for link in soup.find_all('a', href=True):
            if '/referees/' not in link['href']:
                continue
            ref_id = self.extract_id_from_path(link['href'], 'referees')
            if not ref_id or ref_id in seen_ids:
                continue

            name = self.clean_text(link.get_text())
            if not name or len(name) < 2:
                continue

            seen_ids.add(ref_id)
            parsed = self.parse_bc_name(name)

            # Try to find photo nearby
            photo_url = None
            parent = link.parent
            if parent:
                img = parent.find('img')
                if img and img.get('src'):
                    src = img['src']
                    if not src.startswith('http'):
                        src = self.BASE_URL + src
                    photo_url = src

            # Try to find match count
            match_count = None
            if parent:
                text = parent.get_text()
                m = re.search(r'Игр:\s*(\d+)', text)
                if m:
                    match_count = int(m.group(1))

            referees.append({
                "site_id": ref_id,
                "name": name,
                "last_name": parsed["last_name"],
                "first_name": parsed["first_name"],
                "photo_url": photo_url,
                "match_count": match_count,
            })

        logger.info(f"Found {len(referees)} referees for season {season_num}")
        return referees
