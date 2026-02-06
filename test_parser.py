#!/usr/bin/env python
"""Test script for the parser."""

import sys
import json
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add src to path
sys.path.insert(0, '.')

from src.parser.match_parser import MatchParser
from src.database.db import Database
from src.services.data_service import DataService


def test_parse_single_match(match_id: int):
    """Test parsing a single match."""
    print(f"\n{'='*60}")
    print(f"Testing match_id={match_id}")
    print('='*60)

    parser = MatchParser()
    data = parser.parse_match(match_id)

    if data is None:
        print("ERROR: Failed to parse match (returned None)")
        return False

    # Remove raw_html for cleaner output
    data_clean = {k: v for k, v in data.items() if k != 'raw_html'}

    print("\nParsed data:")
    print(json.dumps(data_clean, indent=2, ensure_ascii=False, default=str))

    # Check key fields
    print("\n--- Key fields check ---")
    checks = [
        ("site_id", data.get("site_id")),
        ("date_time", data.get("date_time")),
        ("home_team", data.get("home_team")),
        ("away_team", data.get("away_team")),
        ("home_score", data.get("home_score")),
        ("away_score", data.get("away_score")),
        ("set_scores", data.get("set_scores")),
        ("referee", data.get("referee")),
        ("referee_rating_home", data.get("referee_rating_home")),
        ("referee_rating_away", data.get("referee_rating_away")),
        ("best_players count", len(data.get("best_players", []))),
        ("home_roster count", len(data.get("home_roster", []))),
        ("away_roster count", len(data.get("away_roster", []))),
    ]

    for name, value in checks:
        status = "OK" if value else "MISSING"
        print(f"  {name}: {value} [{status}]")

    return True


def test_save_to_db(match_id: int):
    """Test saving parsed data to database."""
    print(f"\n{'='*60}")
    print(f"Testing save to DB for match_id={match_id}")
    print('='*60)

    parser = MatchParser()
    data = parser.parse_match(match_id)

    if data is None:
        print("ERROR: Failed to parse match")
        return False

    db = Database()
    db.create_tables()

    with db.session() as session:
        service = DataService(session)
        match = service.save_match(data)

        if match:
            print(f"SUCCESS: Saved match with internal ID={match.id}")
            stats = service.get_stats()
            print(f"DB Stats: {stats}")
            return True
        else:
            print("ERROR: Failed to save match")
            return False


if __name__ == '__main__':
    # Test match ID (from user's example)
    test_match_id = 42131

    if len(sys.argv) > 1:
        test_match_id = int(sys.argv[1])

    print("VolleyMSK Parser Test")
    print(f"Testing with match_id={test_match_id}")

    # Test 1: Parse single match
    success = test_parse_single_match(test_match_id)

    if success:
        # Test 2: Save to database
        test_save_to_db(test_match_id)

    print("\n" + "="*60)
    print("Test completed!")
