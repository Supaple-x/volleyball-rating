"""Flask web application for volleyball parser."""

import os
import logging
from flask import Flask, render_template, jsonify, request

from src.database.db import Database
from src.services.parsing_service import ParsingService
from src.services.data_service import DataService
from src.services.bc_parsing_service import BCParsingService
from src.services.bc_data_service import BCDataService
from src.services.scheduler import AutoUpdater

logger = logging.getLogger(__name__)

# Global instances
db: Database = None
parsing_service: ParsingService = None
bc_parsing_service: BCParsingService = None
auto_updater: AutoUpdater = None


def create_app(db_path: str = None) -> Flask:
    """Create and configure Flask application."""
    global db, parsing_service, bc_parsing_service, auto_updater

    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
                static_folder=os.path.join(os.path.dirname(__file__), 'static'))

    # Initialize database
    if db_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        db_path = os.path.join(project_root, 'data', 'volleyball.db')

    db = Database(db_path)
    db.create_tables()

    # Initialize parsing services
    parsing_service = ParsingService(db)
    bc_parsing_service = BCParsingService(db)

    # Start auto-updater daemon
    auto_updater = AutoUpdater(db)
    auto_updater.start()

    # Register routes
    register_routes(app)
    register_bc_routes(app)

    return app


def register_routes(app: Flask):
    """Register all routes."""

    @app.route('/')
    def index():
        """Main page."""
        with db.session() as session:
            data_service = DataService(session)
            stats = data_service.get_stats()
        return render_template('index.html', stats=stats)

    @app.route('/api/stats')
    def api_stats():
        """Get database statistics."""
        with db.session() as session:
            data_service = DataService(session)
            stats = data_service.get_stats()
        return jsonify(stats)

    @app.route('/api/stats/monthly')
    def api_stats_monthly():
        """Get match count by year-month for the chart."""
        from src.database.models import Match
        from sqlalchemy import func, extract

        with db.session() as session:
            rows = session.query(
                extract('year', Match.date_time).label('year'),
                extract('month', Match.date_time).label('month'),
                func.count(Match.id).label('count')
            ).filter(
                Match.date_time.isnot(None)
            ).group_by('year', 'month').order_by('year', 'month').all()

            result = [{'year': int(r.year), 'month': int(r.month), 'count': r.count} for r in rows]
            years = sorted(set(r.year for r in rows))

        return jsonify({'data': result, 'years': [int(y) for y in years]})

    @app.route('/api/progress')
    def api_progress():
        """Get current parsing progress."""
        progress = parsing_service.progress
        return jsonify({
            'job_type': progress.job_type,
            'start_id': progress.start_id,
            'end_id': progress.end_id,
            'current_id': progress.current_id,
            'total_parsed': progress.total_parsed,
            'total_errors': progress.total_errors,
            'status': progress.status,
            'last_error': progress.last_error,
            'progress_percent': round(progress.progress_percent, 1),
        })

    @app.route('/api/parse/matches', methods=['POST'])
    def api_parse_matches():
        """Start parsing matches."""
        if parsing_service.is_running:
            return jsonify({'error': 'Parsing already in progress'}), 400

        data = request.get_json()
        start_id = data.get('start_id', 1)
        end_id = data.get('end_id', 1000)
        skip_existing = data.get('skip_existing', True)

        try:
            parsing_service.start_parsing_matches(start_id, end_id, skip_existing)
            return jsonify({'status': 'started', 'start_id': start_id, 'end_id': end_id})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/parse/rosters', methods=['POST'])
    def api_parse_rosters():
        """Start parsing rosters."""
        if parsing_service.is_running:
            return jsonify({'error': 'Parsing already in progress'}), 400

        data = request.get_json()
        start_id = data.get('start_id', 1)
        end_id = data.get('end_id', 1000)

        try:
            parsing_service.start_parsing_rosters(start_id, end_id)
            return jsonify({'status': 'started', 'start_id': start_id, 'end_id': end_id})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/parse/pause', methods=['POST'])
    def api_parse_pause():
        """Pause parsing."""
        parsing_service.pause()
        return jsonify({'status': 'paused'})

    @app.route('/api/parse/resume', methods=['POST'])
    def api_parse_resume():
        """Resume parsing."""
        parsing_service.resume()
        return jsonify({'status': 'resumed'})

    @app.route('/api/parse/stop', methods=['POST'])
    def api_parse_stop():
        """Stop parsing."""
        parsing_service.stop()
        return jsonify({'status': 'stopped'})

    @app.route('/api/matches')
    def api_matches():
        """Get list of matches with optional search by team name."""
        from src.database.models import Match, Team
        from sqlalchemy import or_

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()

        with db.session() as session:
            query = session.query(Match)
            if search:
                # Join with teams to search by name
                home_team = session.query(Team).filter(Team.name.ilike(f'%{search}%')).subquery()
                away_team = session.query(Team).filter(Team.name.ilike(f'%{search}%')).subquery()
                query = query.filter(or_(
                    Match.home_team_id.in_(session.query(Team.id).filter(Team.name.ilike(f'%{search}%'))),
                    Match.away_team_id.in_(session.query(Team.id).filter(Team.name.ilike(f'%{search}%')))
                ))
            query = query.order_by(Match.date_time.desc())
            total = query.count()
            matches = query.offset((page - 1) * per_page).limit(per_page).all()

            result = []
            for m in matches:
                result.append({
                    'id': m.id,
                    'site_id': m.site_id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'home_team': m.home_team.name if m.home_team else None,
                    'away_team': m.away_team.name if m.away_team else None,
                    'home_score': m.home_score,
                    'away_score': m.away_score,
                    'set_scores': m.set_scores,
                    'status': m.status,
                    'referee': m.referee.full_name if m.referee else None,
                })

        return jsonify({
            'matches': result,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        })

    @app.route('/api/teams')
    def api_teams():
        """Get list of teams with stats, sorting, pagination, gender filter."""
        from src.database.models import Team, Match
        from sqlalchemy import func

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'name')
        gender = request.args.get('gender', '').strip()

        with db.session() as session:
            # Subqueries for match counts (home + away)
            home_count_sq = session.query(
                Match.home_team_id.label('team_id'),
                func.count(Match.id).label('cnt')
            ).filter(Match.home_team_id.isnot(None)).group_by(Match.home_team_id).subquery()

            away_count_sq = session.query(
                Match.away_team_id.label('team_id'),
                func.count(Match.id).label('cnt')
            ).filter(Match.away_team_id.isnot(None)).group_by(Match.away_team_id).subquery()

            # Subqueries for wins
            home_wins_sq = session.query(
                Match.home_team_id.label('team_id'),
                func.count(Match.id).label('cnt')
            ).filter(
                Match.home_team_id.isnot(None),
                Match.home_score > Match.away_score
            ).group_by(Match.home_team_id).subquery()

            away_wins_sq = session.query(
                Match.away_team_id.label('team_id'),
                func.count(Match.id).label('cnt')
            ).filter(
                Match.away_team_id.isnot(None),
                Match.away_score > Match.home_score
            ).group_by(Match.away_team_id).subquery()

            match_count_expr = (
                func.coalesce(home_count_sq.c.cnt, 0) +
                func.coalesce(away_count_sq.c.cnt, 0)
            )
            wins_expr = (
                func.coalesce(home_wins_sq.c.cnt, 0) +
                func.coalesce(away_wins_sq.c.cnt, 0)
            )

            query = session.query(
                Team,
                match_count_expr.label('match_count'),
                wins_expr.label('wins'),
            ).outerjoin(
                home_count_sq, Team.id == home_count_sq.c.team_id
            ).outerjoin(
                away_count_sq, Team.id == away_count_sq.c.team_id
            ).outerjoin(
                home_wins_sq, Team.id == home_wins_sq.c.team_id
            ).outerjoin(
                away_wins_sq, Team.id == away_wins_sq.c.team_id
            )

            if search:
                query = query.filter(Team.name.ilike(f'%{search}%'))
            if gender:
                query = query.filter(Team.gender == gender)

            if sort == 'matches':
                query = query.order_by(match_count_expr.desc())
            elif sort == 'wins':
                query = query.order_by(wins_expr.desc())
            elif sort == 'win_rate':
                query = query.order_by(
                    (wins_expr * 100.0 / func.nullif(match_count_expr, 0)).desc()
                )
            else:
                query = query.order_by(Team.name)

            total = query.count()
            rows = query.offset((page - 1) * per_page).limit(per_page).all()

            result = []
            for r in rows:
                mc = r.match_count
                w = r.wins
                result.append({
                    'id': r.Team.id,
                    'site_id': r.Team.site_id,
                    'name': r.Team.name,
                    'gender': r.Team.gender,
                    'match_count': mc,
                    'wins': w,
                    'losses': mc - w,
                    'win_rate': round(w / mc * 100, 1) if mc > 0 else 0,
                })

        return jsonify({
            'teams': result,
            'total': total,
            'page': page,
            'per_page': per_page,
        })

    @app.route('/api/players')
    def api_players():
        """Get list of players with MVP count, match count, gender filter."""
        from src.database.models import Player, BestPlayer, MatchPlayer, Team
        from sqlalchemy import or_, func

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'mvp')
        gender = request.args.get('gender', '').strip()

        with db.session() as session:
            # Subqueries for stats
            mvp_sq = session.query(
                BestPlayer.player_id,
                func.count(BestPlayer.id).label('mvp_count')
            ).filter(BestPlayer.player_id.isnot(None)).group_by(BestPlayer.player_id).subquery()

            match_sq = session.query(
                MatchPlayer.player_id,
                func.count(MatchPlayer.id).label('match_count')
            ).group_by(MatchPlayer.player_id).subquery()

            query = session.query(
                Player,
                func.coalesce(mvp_sq.c.mvp_count, 0).label('mvp_count'),
                func.coalesce(match_sq.c.match_count, 0).label('match_count')
            ).outerjoin(
                mvp_sq, Player.id == mvp_sq.c.player_id
            ).outerjoin(
                match_sq, Player.id == match_sq.c.player_id
            )

            if search:
                query = query.filter(or_(
                    Player.last_name.ilike(f'%{search}%'),
                    Player.first_name.ilike(f'%{search}%'),
                    Player.patronymic.ilike(f'%{search}%')
                ))

            if gender:
                # Filter players by team gender via MatchPlayer
                gender_player_ids = session.query(
                    MatchPlayer.player_id
                ).join(
                    Team, MatchPlayer.team_id == Team.id
                ).filter(
                    Team.gender == gender
                ).distinct().subquery()
                query = query.filter(Player.id.in_(
                    session.query(gender_player_ids.c.player_id)
                ))

            if sort == 'mvp':
                query = query.order_by(func.coalesce(mvp_sq.c.mvp_count, 0).desc())
            elif sort == 'matches':
                query = query.order_by(func.coalesce(match_sq.c.match_count, 0).desc())
            else:
                query = query.order_by(Player.last_name)

            total = query.count()
            rows = query.offset((page - 1) * per_page).limit(per_page).all()

            result = []
            for r in rows:
                result.append({
                    'id': r.Player.id,
                    'site_id': r.Player.site_id,
                    'full_name': r.Player.full_name,
                    'birth_year': r.Player.birth_year,
                    'height': r.Player.height,
                    'position': r.Player.position,
                    'mvp_count': r.mvp_count,
                    'match_count': r.match_count,
                })

        return jsonify({
            'players': result,
            'total': total,
            'page': page,
            'per_page': per_page,
        })

    @app.route('/api/referees')
    def api_referees():
        """Get list of referees with match count and average rating."""
        from src.database.models import Referee, Match
        from sqlalchemy import or_, func

        search = request.args.get('search', '').strip()

        with db.session() as session:
            # Subquery for match count per referee
            match_count_sq = session.query(
                Match.referee_id,
                func.count(Match.id).label('match_count')
            ).filter(Match.referee_id.isnot(None)).group_by(Match.referee_id).subquery()

            # Subquery for avg rating per referee
            # Each match can have 0-2 ratings (home + away), avg all non-null
            avg_rating_sq = session.query(
                Match.referee_id,
                (func.sum(
                    func.coalesce(Match.referee_rating_home, 0) * (Match.referee_rating_home != None) +
                    func.coalesce(Match.referee_rating_away, 0) * (Match.referee_rating_away != None)
                ) * 1.0 / func.nullif(
                    func.sum(
                        (Match.referee_rating_home != None) + (Match.referee_rating_away != None)
                    ), 0
                )).label('avg_rating')
            ).filter(Match.referee_id.isnot(None)).group_by(Match.referee_id).subquery()

            query = session.query(
                Referee,
                func.coalesce(match_count_sq.c.match_count, 0).label('match_count'),
                avg_rating_sq.c.avg_rating
            ).outerjoin(
                match_count_sq, Referee.id == match_count_sq.c.referee_id
            ).outerjoin(
                avg_rating_sq, Referee.id == avg_rating_sq.c.referee_id
            )

            if search:
                query = query.filter(or_(
                    Referee.last_name.ilike(f'%{search}%'),
                    Referee.first_name.ilike(f'%{search}%'),
                    Referee.patronymic.ilike(f'%{search}%')
                ))

            rows = query.order_by(func.coalesce(match_count_sq.c.match_count, 0).desc()).all()
            result = [{
                'id': r.Referee.id,
                'full_name': r.Referee.full_name,
                'match_count': r.match_count,
                'avg_rating': round(r.avg_rating, 1) if r.avg_rating else None,
            } for r in rows]

        return jsonify({'referees': result, 'total': len(result)})

    @app.route('/api/referees/<int:referee_id>')
    def api_referee_detail(referee_id):
        """Get detailed referee info with match history."""
        from src.database.models import Referee, Match
        from sqlalchemy import or_, func

        with db.session() as session:
            referee = session.query(Referee).filter_by(id=referee_id).first()
            if not referee:
                return jsonify({'error': 'Referee not found'}), 404

            # All matches for this referee
            matches = session.query(Match).filter_by(
                referee_id=referee_id
            ).order_by(Match.date_time.desc()).all()

            # Compute ratings
            ratings = []
            for m in matches:
                if m.referee_rating_home is not None:
                    ratings.append(m.referee_rating_home)
                if m.referee_rating_away is not None:
                    ratings.append(m.referee_rating_away)

            matches_list = []
            for m in matches:
                matches_list.append({
                    'id': m.id,
                    'site_id': m.site_id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'home_team': m.home_team.name if m.home_team else '?',
                    'away_team': m.away_team.name if m.away_team else '?',
                    'home_team_id': m.home_team_id,
                    'away_team_id': m.away_team_id,
                    'home_score': m.home_score,
                    'away_score': m.away_score,
                    'set_scores': m.set_scores,
                    'rating_home': m.referee_rating_home,
                    'rating_away': m.referee_rating_away,
                    'rating_home_text': m.referee_rating_home_text,
                    'rating_away_text': m.referee_rating_away_text,
                })

            result = {
                'id': referee.id,
                'full_name': referee.full_name,
                'first_name': referee.first_name,
                'last_name': referee.last_name,
                'patronymic': referee.patronymic,
                'stats': {
                    'total_matches': len(matches),
                    'avg_rating': round(sum(ratings) / len(ratings), 1) if ratings else None,
                    'total_ratings': len(ratings),
                    'rating_5': sum(1 for r in ratings if r == 5),
                    'rating_4': sum(1 for r in ratings if r == 4),
                    'rating_3': sum(1 for r in ratings if r == 3),
                    'rating_2': sum(1 for r in ratings if r == 2),
                    'rating_1': sum(1 for r in ratings if r == 1),
                },
                'matches': matches_list,
            }

        return jsonify(result)

    @app.route('/api/matches/<int:match_id>')
    def api_match_detail(match_id):
        """Get detailed match info including rosters."""
        from src.database.models import Match, MatchPlayer, BestPlayer

        with db.session() as session:
            match = session.query(Match).filter_by(id=match_id).first()
            if not match:
                return jsonify({'error': 'Match not found'}), 404

            # Get rosters
            home_roster = []
            away_roster = []
            for mp in match.players:
                player_data = {
                    'id': mp.player.id,
                    'site_id': mp.player.site_id,
                    'full_name': mp.player.full_name,
                    'height': mp.player.height,
                    'position': mp.player.position,
                    'birth_year': mp.player.birth_year,
                    'photo_url': mp.player.photo_url,
                }
                if mp.team_id == match.home_team_id:
                    home_roster.append(player_data)
                else:
                    away_roster.append(player_data)

            # Get best players
            best_players = []
            for bp in match.best_players:
                best_players.append({
                    'team': bp.team.name if bp.team else None,
                    'player_id': bp.player_id,
                    'player_name': bp.player.full_name if bp.player else bp.player_name,
                })

            result = {
                'id': match.id,
                'site_id': match.site_id,
                'date_time': match.date_time.isoformat() if match.date_time else None,
                'home_team': {
                    'id': match.home_team.id,
                    'site_id': match.home_team.site_id,
                    'name': match.home_team.name
                } if match.home_team else None,
                'away_team': {
                    'id': match.away_team.id,
                    'site_id': match.away_team.site_id,
                    'name': match.away_team.name
                } if match.away_team else None,
                'home_score': match.home_score,
                'away_score': match.away_score,
                'set_scores': match.set_scores,
                'status': match.status,
                'tournament_path': match.tournament_path,
                'referee': {
                    'id': match.referee.id,
                    'full_name': match.referee.full_name
                } if match.referee else None,
                'referee_rating_home': match.referee_rating_home,
                'referee_rating_away': match.referee_rating_away,
                'referee_rating_home_text': match.referee_rating_home_text,
                'referee_rating_away_text': match.referee_rating_away_text,
                'home_roster': home_roster,
                'away_roster': away_roster,
                'best_players': best_players,
            }

        return jsonify(result)

    @app.route('/api/teams/<int:team_id>')
    def api_team_detail(team_id):
        """Get detailed team info."""
        from src.database.models import Team, Match, MatchPlayer, TeamRoster
        from sqlalchemy import or_, func

        with db.session() as session:
            team = session.query(Team).filter_by(id=team_id).first()
            if not team:
                return jsonify({'error': 'Team not found'}), 404

            # Get match stats
            home_matches = session.query(Match).filter_by(home_team_id=team_id).count()
            away_matches = session.query(Match).filter_by(away_team_id=team_id).count()
            total_matches = home_matches + away_matches

            # Get wins/losses
            home_wins = session.query(Match).filter(
                Match.home_team_id == team_id,
                Match.home_score > Match.away_score
            ).count()
            away_wins = session.query(Match).filter(
                Match.away_team_id == team_id,
                Match.away_score > Match.home_score
            ).count()
            total_wins = home_wins + away_wins

            # Get players who played for this team
            players_query = session.query(MatchPlayer).filter_by(team_id=team_id).all()
            player_ids = set(mp.player_id for mp in players_query)

            from src.database.models import Player
            players = session.query(Player).filter(Player.id.in_(player_ids)).all() if player_ids else []

            # Get roster info (from members.php)
            roster_entries = session.query(TeamRoster).filter_by(team_id=team_id).all()

            # Recent matches
            recent_matches = session.query(Match).filter(
                or_(Match.home_team_id == team_id, Match.away_team_id == team_id)
            ).order_by(Match.date_time.desc()).limit(10).all()

            result = {
                'id': team.id,
                'site_id': team.site_id,
                'name': team.name,
                'stats': {
                    'total_matches': total_matches,
                    'wins': total_wins,
                    'losses': total_matches - total_wins,
                    'win_rate': round(total_wins / total_matches * 100, 1) if total_matches > 0 else 0,
                },
                'players': [{
                    'id': p.id,
                    'site_id': p.site_id,
                    'full_name': p.full_name,
                    'height': p.height,
                    'position': p.position,
                    'birth_year': p.birth_year,
                    'photo_url': p.photo_url,
                } for p in players],
                'roster': [{
                    'player_id': r.player_id,
                    'player_name': r.player.full_name if r.player else None,
                    'height': r.player.height if r.player else None,
                    'position': r.player.position if r.player else None,
                    'photo_url': r.player.photo_url if r.player else None,
                } for r in roster_entries],
                'recent_matches': [{
                    'id': m.id,
                    'site_id': m.site_id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'opponent': m.away_team.name if m.home_team_id == team_id else m.home_team.name,
                    'score': f"{m.home_score}:{m.away_score}" if m.home_team_id == team_id else f"{m.away_score}:{m.home_score}",
                    'is_win': (m.home_score > m.away_score) if m.home_team_id == team_id else (m.away_score > m.home_score),
                    'is_home': m.home_team_id == team_id,
                } for m in recent_matches if m.home_team and m.away_team],
            }

        return jsonify(result)

    @app.route('/api/players/<int:player_id>')
    def api_player_detail(player_id):
        """Get detailed player info."""
        from src.database.models import Player, MatchPlayer, Match, BestPlayer, Referee
        from sqlalchemy import func

        with db.session() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            if not player:
                return jsonify({'error': 'Player not found'}), 404

            # Get match entries with team info
            match_entries = session.query(MatchPlayer).filter_by(player_id=player_id).all()
            match_team_map = {mp.match_id: mp.team_id for mp in match_entries}
            team_ids = set(mp.team_id for mp in match_entries)

            from src.database.models import Team
            teams = session.query(Team).filter(Team.id.in_(team_ids)).all() if team_ids else []
            teams_map = {t.id: t.name for t in teams}

            # Get best player awards
            best_player_count = session.query(BestPlayer).filter_by(player_id=player_id).count()

            # All matches (sorted by date desc)
            match_ids = [mp.match_id for mp in match_entries]
            all_matches = session.query(Match).filter(
                Match.id.in_(match_ids)
            ).order_by(Match.date_time.desc()).all() if match_ids else []

            # Calculate wins/losses
            wins = 0
            losses = 0
            for m in all_matches:
                if m.home_score is not None and m.away_score is not None:
                    player_team_id = match_team_map.get(m.id)
                    if player_team_id == m.home_team_id:
                        if m.home_score > m.away_score:
                            wins += 1
                        else:
                            losses += 1
                    else:
                        if m.away_score > m.home_score:
                            wins += 1
                        else:
                            losses += 1

            # Check if player is also a referee (by name match)
            referee_stats = None
            referee = session.query(Referee).filter(
                Referee.last_name == player.last_name,
                Referee.first_name == player.first_name
            ).first()

            if referee:
                # Get referee matches and ratings
                ref_matches = session.query(Match).filter_by(referee_id=referee.id).all()
                if ref_matches:
                    ratings = []
                    for rm in ref_matches:
                        if rm.referee_rating_home is not None:
                            ratings.append(rm.referee_rating_home)
                        if rm.referee_rating_away is not None:
                            ratings.append(rm.referee_rating_away)

                    referee_stats = {
                        'matches_refereed': len(ref_matches),
                        'avg_rating': round(sum(ratings) / len(ratings), 2) if ratings else None,
                        'total_ratings': len(ratings),
                    }

            # Build matches list with detailed info
            matches_list = []
            for m in all_matches:
                player_team_id = match_team_map.get(m.id)
                is_home = player_team_id == m.home_team_id
                player_team = teams_map.get(player_team_id, '?')

                if is_home:
                    opponent = m.away_team.name if m.away_team else '?'
                    is_win = m.home_score > m.away_score if m.home_score is not None else None
                    score = f"{m.home_score}:{m.away_score}"
                else:
                    opponent = m.home_team.name if m.home_team else '?'
                    is_win = m.away_score > m.home_score if m.away_score is not None else None
                    score = f"{m.away_score}:{m.home_score}"

                matches_list.append({
                    'id': m.id,
                    'site_id': m.site_id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'player_team': player_team,
                    'opponent': opponent,
                    'score': score,
                    'set_scores': m.set_scores,
                    'is_home': is_home,
                    'is_win': is_win,
                })

            result = {
                'id': player.id,
                'site_id': player.site_id,
                'full_name': player.full_name,
                'first_name': player.first_name,
                'last_name': player.last_name,
                'patronymic': player.patronymic,
                'height': player.height,
                'position': player.position,
                'birth_year': player.birth_year,
                'photo_url': player.photo_url,
                'stats': {
                    'total_matches': len(match_entries),
                    'wins': wins,
                    'losses': losses,
                    'win_rate': round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
                    'best_player_awards': best_player_count,
                },
                'referee_stats': referee_stats,
                'teams': [{
                    'id': t.id,
                    'name': t.name,
                } for t in teams],
                'matches': matches_list,
            }

        return jsonify(result)

    @app.route('/api/autoupdate/status')
    def api_autoupdate_status():
        return jsonify(auto_updater.get_status())


def register_bc_routes(app: Flask):
    """Register Business Champions League routes."""

    # ---- Parsing control ----

    @app.route('/api/bc/progress')
    def api_bc_progress():
        return jsonify(bc_parsing_service.get_progress())

    @app.route('/api/bc/parse/full-season', methods=['POST'])
    def api_bc_parse_full_season():
        if bc_parsing_service.is_running:
            return jsonify({'error': 'BC parsing already in progress'}), 400
        data = request.get_json()
        season_num = data.get('season_num', 30)
        skip_existing = data.get('skip_existing', True)
        try:
            bc_parsing_service.start_full_season(season_num, skip_existing)
            return jsonify({'status': 'started', 'season_num': season_num})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bc/parse/all-seasons', methods=['POST'])
    def api_bc_parse_all_seasons():
        if bc_parsing_service.is_running:
            return jsonify({'error': 'BC parsing already in progress'}), 400
        data = request.get_json()
        start = data.get('start', 1)
        end = data.get('end', 30)
        skip_existing = data.get('skip_existing', True)
        try:
            bc_parsing_service.start_all_seasons(start, end, skip_existing)
            return jsonify({'status': 'started', 'start': start, 'end': end})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bc/parse/schedule', methods=['POST'])
    def api_bc_parse_schedule():
        if bc_parsing_service.is_running:
            return jsonify({'error': 'BC parsing already in progress'}), 400
        data = request.get_json()
        season_num = data.get('season_num', 30)
        try:
            bc_parsing_service.start_schedule(season_num)
            return jsonify({'status': 'started', 'season_num': season_num})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bc/parse/matches', methods=['POST'])
    def api_bc_parse_matches():
        if bc_parsing_service.is_running:
            return jsonify({'error': 'BC parsing already in progress'}), 400
        data = request.get_json()
        season_num = data.get('season_num', 30)
        skip_existing = data.get('skip_existing', True)
        try:
            bc_parsing_service.start_matches(season_num, skip_existing)
            return jsonify({'status': 'started', 'season_num': season_num})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bc/parse/players', methods=['POST'])
    def api_bc_parse_players():
        if bc_parsing_service.is_running:
            return jsonify({'error': 'BC parsing already in progress'}), 400
        data = request.get_json()
        season_num = data.get('season_num', 30)
        try:
            bc_parsing_service.start_players(season_num)
            return jsonify({'status': 'started', 'season_num': season_num})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bc/parse/referees', methods=['POST'])
    def api_bc_parse_referees():
        if bc_parsing_service.is_running:
            return jsonify({'error': 'BC parsing already in progress'}), 400
        data = request.get_json()
        season_num = data.get('season_num', 30)
        try:
            bc_parsing_service.start_referees(season_num)
            return jsonify({'status': 'started', 'season_num': season_num})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bc/parse/pause', methods=['POST'])
    def api_bc_parse_pause():
        bc_parsing_service.pause()
        return jsonify({'status': 'paused'})

    @app.route('/api/bc/parse/resume', methods=['POST'])
    def api_bc_parse_resume():
        bc_parsing_service.resume()
        return jsonify({'status': 'resumed'})

    @app.route('/api/bc/parse/stop', methods=['POST'])
    def api_bc_parse_stop():
        bc_parsing_service.stop()
        return jsonify({'status': 'stopped'})

    # ---- Data endpoints ----

    @app.route('/api/bc/stats')
    def api_bc_stats():
        with db.session() as session:
            svc = BCDataService(session)
            return jsonify(svc.get_stats())

    @app.route('/api/bc/stats/monthly')
    def api_bc_stats_monthly():
        from src.database.models import BCMatch
        from sqlalchemy import func, extract
        with db.session() as session:
            data = session.query(
                extract('year', BCMatch.date_time).label('year'),
                extract('month', BCMatch.date_time).label('month'),
                func.count(BCMatch.id).label('count')
            ).filter(BCMatch.date_time.isnot(None)
            ).group_by('year', 'month'
            ).order_by('year', 'month').all()
            result = [{'year': int(r.year), 'month': int(r.month), 'count': r.count} for r in data]
            years = sorted(set(r['year'] for r in result))
            return jsonify({'data': result, 'years': years})

    @app.route('/api/bc/seasons')
    def api_bc_seasons():
        from src.database.models import BCSeason
        with db.session() as session:
            seasons = session.query(BCSeason).order_by(BCSeason.number.desc()).all()
            return jsonify({'seasons': [{
                'id': s.id, 'number': s.number, 'name': s.name
            } for s in seasons]})

    @app.route('/api/bc/matches')
    def api_bc_matches():
        from src.database.models import BCMatch, BCTeam
        from sqlalchemy import or_

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()
        season = request.args.get('season', '', type=str)
        division = request.args.get('division', '').strip()

        with db.session() as session:
            query = session.query(BCMatch)

            if season:
                from src.database.models import BCSeason
                s = session.query(BCSeason).filter_by(number=int(season)).first()
                if s:
                    query = query.filter(BCMatch.season_id == s.id)

            if division:
                query = query.filter(BCMatch.division_name == division)

            if search:
                team_ids = session.query(BCTeam.id).filter(
                    BCTeam.name.ilike(f'%{search}%')
                ).subquery()
                query = query.filter(or_(
                    BCMatch.home_team_id.in_(team_ids),
                    BCMatch.away_team_id.in_(team_ids)
                ))

            query = query.order_by(BCMatch.date_time.desc())
            total = query.count()
            matches = query.offset((page - 1) * per_page).limit(per_page).all()

            result = []
            for m in matches:
                result.append({
                    'id': m.id,
                    'site_id': m.site_id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'home_team': m.home_team.name if m.home_team else None,
                    'away_team': m.away_team.name if m.away_team else None,
                    'home_score': m.home_score,
                    'away_score': m.away_score,
                    'set_scores': m.set_scores,
                    'division_name': m.division_name,
                    'round_name': m.round_name,
                    'tournament_type': m.tournament_type,
                    'venue': m.venue,
                    'status': m.status,
                })

        return jsonify({
            'matches': result, 'total': total,
            'page': page, 'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        })

    @app.route('/api/bc/matches/<int:match_id>')
    def api_bc_match_detail(match_id):
        from src.database.models import BCMatch, BCSeason
        with db.session() as session:
            match = session.query(BCMatch).filter_by(id=match_id).first()
            if not match:
                return jsonify({'error': 'Match not found'}), 404

            home_stats = []
            away_stats = []
            for ps in match.player_stats:
                entry = {
                    'player_id': ps.player.id,
                    'player_name': ps.player.full_name,
                    'jersey_number': ps.jersey_number,
                    'points': ps.points,
                    'attacks': ps.attacks,
                    'serves': ps.serves,
                    'blocks': ps.blocks,
                }
                if ps.team_id == match.home_team_id:
                    home_stats.append(entry)
                else:
                    away_stats.append(entry)

            best_players = [{
                'player_id': bp.player_id,
                'player_name': bp.player.full_name if bp.player else bp.player_name,
                'points': bp.points, 'attacks': bp.attacks,
                'serves': bp.serves, 'blocks': bp.blocks,
            } for bp in match.best_players]

            referees = [{
                'id': mr.referee.id, 'full_name': mr.referee.full_name,
            } for mr in match.referees]

            season_num = 30
            if match.season_id:
                season = session.query(BCSeason).filter_by(id=match.season_id).first()
                if season:
                    season_num = season.number

            result = {
                'id': match.id, 'site_id': match.site_id, 'season_num': season_num,
                'date_time': match.date_time.isoformat() if match.date_time else None,
                'home_team': {'id': match.home_team.id, 'name': match.home_team.name} if match.home_team else None,
                'away_team': {'id': match.away_team.id, 'name': match.away_team.name} if match.away_team else None,
                'home_score': match.home_score, 'away_score': match.away_score,
                'set_scores': match.set_scores,
                'home_total_points': match.home_total_points,
                'away_total_points': match.away_total_points,
                'division_name': match.division_name, 'round_name': match.round_name,
                'tournament_type': match.tournament_type, 'venue': match.venue,
                'status': match.status,
                'home_stats': home_stats, 'away_stats': away_stats,
                'best_players': best_players, 'referees': referees,
            }
        return jsonify(result)

    @app.route('/api/bc/teams')
    def api_bc_teams():
        from src.database.models import BCTeam, BCMatch
        from sqlalchemy import func

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'name')

        with db.session() as session:
            home_sq = session.query(
                BCMatch.home_team_id.label('tid'), func.count(BCMatch.id).label('cnt')
            ).filter(BCMatch.home_team_id.isnot(None)).group_by(BCMatch.home_team_id).subquery()
            away_sq = session.query(
                BCMatch.away_team_id.label('tid'), func.count(BCMatch.id).label('cnt')
            ).filter(BCMatch.away_team_id.isnot(None)).group_by(BCMatch.away_team_id).subquery()
            home_wins = session.query(
                BCMatch.home_team_id.label('tid'), func.count(BCMatch.id).label('cnt')
            ).filter(BCMatch.home_team_id.isnot(None), BCMatch.home_score > BCMatch.away_score
            ).group_by(BCMatch.home_team_id).subquery()
            away_wins = session.query(
                BCMatch.away_team_id.label('tid'), func.count(BCMatch.id).label('cnt')
            ).filter(BCMatch.away_team_id.isnot(None), BCMatch.away_score > BCMatch.home_score
            ).group_by(BCMatch.away_team_id).subquery()

            mc_expr = func.coalesce(home_sq.c.cnt, 0) + func.coalesce(away_sq.c.cnt, 0)
            wins_expr = func.coalesce(home_wins.c.cnt, 0) + func.coalesce(away_wins.c.cnt, 0)

            query = session.query(BCTeam, mc_expr.label('mc'), wins_expr.label('wins')
            ).outerjoin(home_sq, BCTeam.id == home_sq.c.tid
            ).outerjoin(away_sq, BCTeam.id == away_sq.c.tid
            ).outerjoin(home_wins, BCTeam.id == home_wins.c.tid
            ).outerjoin(away_wins, BCTeam.id == away_wins.c.tid)

            if search:
                query = query.filter(BCTeam.name.ilike(f'%{search}%'))
            if sort == 'matches':
                query = query.order_by(mc_expr.desc())
            elif sort == 'wins':
                query = query.order_by(wins_expr.desc())
            else:
                query = query.order_by(BCTeam.name)

            total = query.count()
            rows = query.offset((page - 1) * per_page).limit(per_page).all()
            result = []
            for r in rows:
                mc = r.mc; w = r.wins
                result.append({
                    'id': r.BCTeam.id, 'site_id': r.BCTeam.site_id,
                    'name': r.BCTeam.name, 'is_women': r.BCTeam.is_women,
                    'match_count': mc, 'wins': w, 'losses': mc - w,
                    'win_rate': round(w / mc * 100, 1) if mc > 0 else 0,
                })

        return jsonify({'teams': result, 'total': total, 'page': page, 'per_page': per_page})

    @app.route('/api/bc/teams/<int:team_id>')
    def api_bc_team_detail(team_id):
        from src.database.models import BCTeam, BCMatch, BCMatchPlayerStats, BCPlayer, BCSeason
        from sqlalchemy import or_, func, distinct

        with db.session() as session:
            team = session.query(BCTeam).filter_by(id=team_id).first()
            if not team:
                return jsonify({'error': 'Team not found'}), 404

            total = session.query(BCMatch).filter(or_(
                BCMatch.home_team_id == team_id, BCMatch.away_team_id == team_id)).count()
            wins = session.query(BCMatch).filter(or_(
                (BCMatch.home_team_id == team_id) & (BCMatch.home_score > BCMatch.away_score),
                (BCMatch.away_team_id == team_id) & (BCMatch.away_score > BCMatch.home_score))).count()

            # Seasons the team played in
            season_ids = session.query(distinct(BCMatch.season_id)).filter(
                or_(BCMatch.home_team_id == team_id, BCMatch.away_team_id == team_id),
                BCMatch.season_id.isnot(None)
            ).all()
            seasons_list = []
            for (sid,) in season_ids:
                s = session.query(BCSeason).filter_by(id=sid).first()
                if s:
                    seasons_list.append({'id': s.id, 'number': s.number, 'name': s.name})
            seasons_list.sort(key=lambda x: x['number'], reverse=True)

            players = session.query(
                BCPlayer,
                func.count(BCMatchPlayerStats.id).label('games'),
                func.coalesce(func.sum(BCMatchPlayerStats.points), 0).label('points'),
                func.coalesce(func.sum(BCMatchPlayerStats.attacks), 0).label('attacks'),
                func.coalesce(func.sum(BCMatchPlayerStats.serves), 0).label('serves'),
                func.coalesce(func.sum(BCMatchPlayerStats.blocks), 0).label('blocks'),
            ).join(BCMatchPlayerStats, BCMatchPlayerStats.player_id == BCPlayer.id
            ).filter(BCMatchPlayerStats.team_id == team_id
            ).group_by(BCPlayer.id
            ).order_by(func.sum(BCMatchPlayerStats.points).desc()).all()

            recent = session.query(BCMatch).filter(or_(
                BCMatch.home_team_id == team_id, BCMatch.away_team_id == team_id
            )).order_by(BCMatch.date_time.desc()).limit(20).all()

            result = {
                'id': team.id, 'site_id': team.site_id, 'name': team.name,
                'logo_url': team.logo_url,
                'stats': {'total_matches': total, 'wins': wins, 'losses': total - wins,
                          'win_rate': round(wins / total * 100, 1) if total > 0 else 0},
                'seasons': seasons_list,
                'roster': [{'id': p.BCPlayer.id, 'full_name': p.BCPlayer.full_name,
                    'height': p.BCPlayer.height, 'match_count': p.games,
                    'total_points': p.points, 'total_attacks': p.attacks,
                    'total_serves': p.serves, 'total_blocks': p.blocks} for p in players],
                'recent_matches': [{'id': m.id, 'site_id': m.site_id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'opponent': m.away_team.name if m.home_team_id == team_id else (m.home_team.name if m.home_team else '?'),
                    'score': f"{m.home_score}:{m.away_score}" if m.home_team_id == team_id else f"{m.away_score}:{m.home_score}",
                    'is_win': (m.home_score > m.away_score) if m.home_team_id == team_id else (m.away_score > m.home_score) if m.away_score is not None else None,
                } for m in recent if m.home_team and m.away_team],
            }
        return jsonify(result)

    @app.route('/api/bc/players')
    def api_bc_players():
        from src.database.models import BCPlayer, BCMatchPlayerStats, BCBestPlayer
        from sqlalchemy import func, or_

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'mvp')

        with db.session() as session:
            stats_sq = session.query(
                BCMatchPlayerStats.player_id,
                func.count(BCMatchPlayerStats.id).label('games'),
                func.coalesce(func.sum(BCMatchPlayerStats.points), 0).label('pts'),
                func.coalesce(func.sum(BCMatchPlayerStats.attacks), 0).label('atk'),
                func.coalesce(func.sum(BCMatchPlayerStats.serves), 0).label('srv'),
                func.coalesce(func.sum(BCMatchPlayerStats.blocks), 0).label('blk'),
            ).group_by(BCMatchPlayerStats.player_id).subquery()

            mvp_sq = session.query(
                BCBestPlayer.player_id,
                func.count(BCBestPlayer.id).label('mvp')
            ).filter(BCBestPlayer.player_id.isnot(None)
            ).group_by(BCBestPlayer.player_id).subquery()

            query = session.query(
                BCPlayer, stats_sq.c.games, stats_sq.c.pts,
                stats_sq.c.atk, stats_sq.c.srv, stats_sq.c.blk,
                func.coalesce(mvp_sq.c.mvp, 0).label('mvp')
            ).outerjoin(stats_sq, BCPlayer.id == stats_sq.c.player_id
            ).outerjoin(mvp_sq, BCPlayer.id == mvp_sq.c.player_id)

            if search:
                query = query.filter(or_(
                    BCPlayer.last_name.ilike(f'%{search}%'),
                    BCPlayer.first_name.ilike(f'%{search}%')))

            if sort == 'mvp':
                query = query.order_by(func.coalesce(mvp_sq.c.mvp, 0).desc())
            elif sort == 'points':
                query = query.order_by(func.coalesce(stats_sq.c.pts, 0).desc())
            elif sort == 'matches':
                query = query.order_by(func.coalesce(stats_sq.c.games, 0).desc())
            elif sort == 'attacks':
                query = query.order_by(func.coalesce(stats_sq.c.atk, 0).desc())
            elif sort == 'serves':
                query = query.order_by(func.coalesce(stats_sq.c.srv, 0).desc())
            elif sort == 'blocks':
                query = query.order_by(func.coalesce(stats_sq.c.blk, 0).desc())
            else:
                query = query.order_by(BCPlayer.last_name)

            total = query.count()
            rows = query.offset((page - 1) * per_page).limit(per_page).all()
            result = [{'id': r.BCPlayer.id, 'site_id': r.BCPlayer.site_id,
                'full_name': r.BCPlayer.full_name,
                'height': r.BCPlayer.height, 'weight': r.BCPlayer.weight,
                'match_count': r.games or 0, 'total_points': r.pts or 0,
                'total_attacks': r.atk or 0, 'total_serves': r.srv or 0, 'total_blocks': r.blk or 0,
                'mvp_count': r.mvp,
            } for r in rows]

        return jsonify({'players': result, 'total': total, 'page': page, 'per_page': per_page})

    @app.route('/api/bc/players/<int:player_id>')
    def api_bc_player_detail(player_id):
        from src.database.models import BCPlayer, BCMatchPlayerStats, BCMatch, BCBestPlayer, BCTeam
        from sqlalchemy import func, distinct

        with db.session() as session:
            player = session.query(BCPlayer).filter_by(id=player_id).first()
            if not player:
                return jsonify({'error': 'Player not found'}), 404

            stats = session.query(
                func.count(BCMatchPlayerStats.id).label('games'),
                func.coalesce(func.sum(BCMatchPlayerStats.points), 0).label('points'),
                func.coalesce(func.sum(BCMatchPlayerStats.attacks), 0).label('attacks'),
                func.coalesce(func.sum(BCMatchPlayerStats.serves), 0).label('serves'),
                func.coalesce(func.sum(BCMatchPlayerStats.blocks), 0).label('blocks'),
            ).filter(BCMatchPlayerStats.player_id == player_id).first()

            best_count = session.query(BCBestPlayer).filter_by(player_id=player_id).count()

            # Teams the player played for
            team_ids = session.query(distinct(BCMatchPlayerStats.team_id)).filter(
                BCMatchPlayerStats.player_id == player_id
            ).all()
            teams_list = []
            for (tid,) in team_ids:
                if tid:
                    t = session.query(BCTeam).filter_by(id=tid).first()
                    if t:
                        teams_list.append({'id': t.id, 'name': t.name, 'site_id': t.site_id})

            match_stats = session.query(BCMatchPlayerStats, BCMatch).join(
                BCMatch, BCMatch.id == BCMatchPlayerStats.match_id
            ).filter(BCMatchPlayerStats.player_id == player_id
            ).order_by(BCMatch.date_time.desc()).all()

            matches_list = []
            for ps, m in match_stats:
                is_home = ps.team_id == m.home_team_id
                team_name = ''
                if ps.team_id:
                    for t in teams_list:
                        if t['id'] == ps.team_id:
                            team_name = t['name']; break
                opponent = m.away_team.name if is_home and m.away_team else (m.home_team.name if m.home_team else '?')
                matches_list.append({
                    'match_id': m.id,
                    'date_time': m.date_time.isoformat() if m.date_time else None,
                    'team_name': team_name, 'opponent': opponent,
                    'division': m.division_name, 'round': m.round_name,
                    'points': ps.points, 'attacks': ps.attacks, 'serves': ps.serves, 'blocks': ps.blocks,
                    'score': f"{m.home_score}:{m.away_score}" if is_home else f"{m.away_score}:{m.home_score}",
                })

            result = {
                'id': player.id, 'site_id': player.site_id,
                'full_name': player.full_name,
                'first_name': player.first_name, 'last_name': player.last_name,
                'height': player.height, 'weight': player.weight,
                'birth_date': player.birth_date, 'position': player.position,
                'photo_url': player.photo_url,
                'stats': {'total_matches': stats.games, 'total_points': stats.points,
                    'total_attacks': stats.attacks, 'total_serves': stats.serves,
                    'total_blocks': stats.blocks, 'best_player_awards': best_count},
                'teams': teams_list,
                'matches': matches_list,
            }
        return jsonify(result)

    @app.route('/api/bc/referees')
    def api_bc_referees():
        from src.database.models import BCReferee, BCMatchReferee
        from sqlalchemy import func, or_

        search = request.args.get('search', '').strip()
        with db.session() as session:
            mc_sq = session.query(
                BCMatchReferee.referee_id, func.count(BCMatchReferee.id).label('mc')
            ).group_by(BCMatchReferee.referee_id).subquery()
            query = session.query(
                BCReferee, func.coalesce(mc_sq.c.mc, 0).label('mc')
            ).outerjoin(mc_sq, BCReferee.id == mc_sq.c.referee_id)
            if search:
                query = query.filter(or_(
                    BCReferee.last_name.ilike(f'%{search}%'),
                    BCReferee.first_name.ilike(f'%{search}%')))
            rows = query.order_by(func.coalesce(mc_sq.c.mc, 0).desc()).all()
            result = [{'id': r.BCReferee.id, 'full_name': r.BCReferee.full_name,
                'match_count': r.mc} for r in rows]
        return jsonify({'referees': result, 'total': len(result)})

    @app.route('/api/bc/referees/<int:referee_id>')
    def api_bc_referee_detail(referee_id):
        from src.database.models import BCReferee, BCMatchReferee, BCMatch
        with db.session() as session:
            referee = session.query(BCReferee).filter_by(id=referee_id).first()
            if not referee:
                return jsonify({'error': 'Referee not found'}), 404
            assignments = session.query(BCMatchReferee, BCMatch).join(
                BCMatch, BCMatch.id == BCMatchReferee.match_id
            ).filter(BCMatchReferee.referee_id == referee_id
            ).order_by(BCMatch.date_time.desc()).all()
            matches_list = [{'id': m.id, 'site_id': m.site_id,
                'date_time': m.date_time.isoformat() if m.date_time else None,
                'home_team': m.home_team.name if m.home_team else '?',
                'away_team': m.away_team.name if m.away_team else '?',
                'home_score': m.home_score, 'away_score': m.away_score,
                'division': m.division_name, 'round': m.round_name,
            } for mr, m in assignments]
            result = {
                'id': referee.id, 'full_name': referee.full_name,
                'photo_url': referee.photo_url,
                'stats': {'total_matches': len(matches_list)},
                'matches': matches_list,
            }
        return jsonify(result)
