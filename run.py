#!/usr/bin/env python
"""Main entry point for the volleyball parser application."""

import argparse
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('parser.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)


def run_web(host: str = '127.0.0.1', port: int = 5000, debug: bool = False):
    """Run the web interface."""
    from src.web import create_app

    app = create_app()
    logger.info(f"Starting web server at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


def run_cli_parse_matches(start_id: int, end_id: int):
    """Run match parsing from command line."""
    from src.database.db import Database
    from src.parser import MatchParser
    from src.services.data_service import DataService

    logger.info(f"Parsing matches from {start_id} to {end_id}")

    db = Database()
    db.create_tables()
    parser = MatchParser()

    parsed = 0
    errors = 0

    for match_id in range(start_id, end_id + 1):
        try:
            with db.session() as session:
                data_service = DataService(session)

                if data_service.match_exists(match_id):
                    logger.debug(f"Match {match_id} exists, skipping")
                    continue

                match_data = parser.parse_match(match_id)
                if match_data:
                    data_service.save_match(match_data)
                    parsed += 1
                    logger.info(f"Parsed match {match_id}")

        except Exception as e:
            errors += 1
            logger.error(f"Error parsing match {match_id}: {e}")

        if match_id % 100 == 0:
            logger.info(f"Progress: {match_id}/{end_id} (parsed: {parsed}, errors: {errors})")

    logger.info(f"Finished. Parsed: {parsed}, Errors: {errors}")


def main():
    parser = argparse.ArgumentParser(description='VolleyMSK Parser')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Web command
    web_parser = subparsers.add_parser('web', help='Run web interface')
    web_parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    web_parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    web_parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    # Parse matches command
    parse_parser = subparsers.add_parser('parse', help='Parse matches from CLI')
    parse_parser.add_argument('--start', type=int, required=True, help='Start match ID')
    parse_parser.add_argument('--end', type=int, required=True, help='End match ID')

    args = parser.parse_args()

    if args.command == 'web':
        run_web(args.host, args.port, args.debug)
    elif args.command == 'parse':
        run_cli_parse_matches(args.start, args.end)
    else:
        # Default: run web interface
        run_web()


if __name__ == '__main__':
    main()
