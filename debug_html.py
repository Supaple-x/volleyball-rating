#!/usr/bin/env python
"""Debug script to save and analyze HTML."""

import sys
sys.path.insert(0, '.')

from src.parser.base_parser import BaseParser

def save_html(match_id: int):
    parser = BaseParser()
    soup = parser.fetch_page(f"https://volleymsk.ru/ap/match.php?match_id={match_id}")

    if soup:
        # Save full HTML
        with open(f"debug_match_{match_id}.html", "w", encoding="utf-8") as f:
            f.write(str(soup))
        print(f"Saved to debug_match_{match_id}.html")

        # Print text content for quick analysis
        text = soup.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        print("\n--- First 100 non-empty lines ---")
        for i, line in enumerate(lines[:100]):
            print(f"{i:3}: {line[:100]}")
    else:
        print("Failed to fetch page")

if __name__ == '__main__':
    match_id = int(sys.argv[1]) if len(sys.argv) > 1 else 42131
    save_html(match_id)
