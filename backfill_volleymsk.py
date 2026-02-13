"""One-time backfill of missing VolleyMSK matches (gaps in site_id range)."""

import logging
import sys
from src.database.db import Database
from src.database.models import Match
from src.parser import MatchParser
from src.services.data_service import DataService
from sqlalchemy import func

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def backfill(db_path='data/volleyball.db'):
    db = Database(db_path)
    parser = MatchParser()

    with db.session() as session:
        # Get max valid site_id
        max_valid = session.query(func.max(Match.site_id)).filter(
            Match.home_team_id.isnot(None)
        ).scalar() or 0

        # Get all existing site_ids
        existing_ids = set(
            r[0] for r in session.query(Match.site_id).all()
        )

    # Find gaps: IDs in 1..max_valid that are not in DB at all
    gaps = [i for i in range(1, max_valid + 1) if i not in existing_ids]
    logger.info(f"Max valid site_id: {max_valid}")
    logger.info(f"Gaps to check: {len(gaps)}")

    new_count = 0
    errors = 0

    for idx, match_id in enumerate(gaps):
        try:
            with db.session() as session:
                ds = DataService(session)
                match_data = parser.parse_match(match_id)
                if match_data and match_data.get("home_team"):
                    ds.save_match(match_data)
                    new_count += 1
                    logger.info(f"[{idx+1}/{len(gaps)}] New match {match_id}")
                else:
                    # Save empty record so we don't retry
                    if not ds.match_exists(match_id):
                        empty = Match(site_id=match_id, status='empty')
                        session.add(empty)
                        session.commit()

        except Exception as e:
            errors += 1
            logger.error(f"Error parsing {match_id}: {e}")

        if (idx + 1) % 100 == 0:
            logger.info(f"Progress: {idx+1}/{len(gaps)}, new: {new_count}, errors: {errors}")

    logger.info(f"Done. New matches: {new_count}, Errors: {errors}")

    # Also check beyond max for new matches
    logger.info(f"Checking new matches beyond {max_valid}...")
    empty_streak = 0
    current_id = max_valid + 1

    while empty_streak < 50:
        try:
            with db.session() as session:
                ds = DataService(session)
                if ds.match_exists(current_id):
                    current_id += 1
                    empty_streak = 0
                    continue

                match_data = parser.parse_match(current_id)
                if match_data and match_data.get("home_team"):
                    ds.save_match(match_data)
                    new_count += 1
                    empty_streak = 0
                    logger.info(f"New match beyond max: {current_id}")
                else:
                    empty_streak += 1

        except Exception as e:
            errors += 1
            empty_streak += 1

        current_id += 1

    logger.info(f"Final total. New matches: {new_count}, checked up to: {current_id - 1}")


if __name__ == '__main__':
    backfill()
