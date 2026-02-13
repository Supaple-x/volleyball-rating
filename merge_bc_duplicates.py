"""Merge duplicate BC players (same last_name + first_name + birth_date)."""

import logging
from collections import defaultdict
from src.database.db import Database
from src.database.models import BCPlayer, BCMatchPlayerStats, BCBestPlayer
from sqlalchemy import func

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def merge_duplicates(db_path='data/volleyball.db', dry_run=False):
    db = Database(db_path)

    with db.session() as s:
        # Find groups with same name + birth_date (confirmed same person)
        groups = s.query(
            BCPlayer.last_name, BCPlayer.first_name, BCPlayer.birth_date,
            func.count(BCPlayer.id).label('cnt')
        ).filter(
            BCPlayer.birth_date.isnot(None),
            BCPlayer.birth_date != '',
        ).group_by(
            BCPlayer.last_name, BCPlayer.first_name, BCPlayer.birth_date
        ).having(func.count(BCPlayer.id) > 1).all()

        logger.info(f"Found {len(groups)} duplicate groups to merge")

        merged_count = 0
        deleted_count = 0

        for g in groups:
            players = s.query(BCPlayer).filter_by(
                last_name=g.last_name, first_name=g.first_name, birth_date=g.birth_date
            ).all()

            if len(players) < 2:
                continue

            # Pick primary: the one with most match stats
            stats_counts = []
            for p in players:
                cnt = s.query(func.count(BCMatchPlayerStats.id)).filter(
                    BCMatchPlayerStats.player_id == p.id
                ).scalar()
                stats_counts.append((p, cnt))

            stats_counts.sort(key=lambda x: -x[1])
            primary = stats_counts[0][0]
            duplicates = [sc[0] for sc in stats_counts[1:]]

            # Merge bio data into primary (take best available)
            for dup in duplicates:
                if dup.height and not primary.height:
                    primary.height = dup.height
                if dup.weight and not primary.weight:
                    primary.weight = dup.weight
                if dup.position and not primary.position:
                    primary.position = dup.position
                if dup.photo_url and not primary.photo_url:
                    primary.photo_url = dup.photo_url

            if dry_run:
                dup_ids = [d.site_id for d in duplicates]
                logger.info(f"  Would merge {g.last_name} {g.first_name} ({g.birth_date}): "
                           f"keep site_id={primary.site_id} (id={primary.id}), "
                           f"merge site_ids={dup_ids}")
                continue

            # Move stats and best_player records to primary
            for dup in duplicates:
                # Update match player stats
                # Check for conflicts first (same match_id + player_id)
                dup_stats = s.query(BCMatchPlayerStats).filter_by(player_id=dup.id).all()
                for stat in dup_stats:
                    existing = s.query(BCMatchPlayerStats).filter_by(
                        match_id=stat.match_id, player_id=primary.id
                    ).first()
                    if existing:
                        # Primary already has stats for this match, delete duplicate
                        s.delete(stat)
                    else:
                        stat.player_id = primary.id

                # Update best player records
                dup_bps = s.query(BCBestPlayer).filter_by(player_id=dup.id).all()
                for bp in dup_bps:
                    bp.player_id = primary.id

                # Delete duplicate player
                s.delete(dup)
                deleted_count += 1

            merged_count += 1

        if not dry_run:
            s.commit()

        logger.info(f"\nMerged {merged_count} groups, deleted {deleted_count} duplicate players")

        # Show final stats
        total = s.query(BCPlayer).count()
        logger.info(f"Total players remaining: {total}")


if __name__ == '__main__':
    import sys
    dry = '--dry-run' in sys.argv
    if dry:
        logger.info("=== DRY RUN ===")
    merge_duplicates(dry_run=dry)
