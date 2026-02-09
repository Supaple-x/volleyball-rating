"""Flask web application for volleyball parser."""

import os
import logging
from flask import Flask, render_template, jsonify, request

from src.database.db import Database
from src.services.parsing_service import ParsingService
from src.services.data_service import DataService

logger = logging.getLogger(__name__)

# Global instances
db: Database = None
parsing_service: ParsingService = None


def create_app(db_path: str = None) -> Flask:
    """Create and configure Flask application."""
    global db, parsing_service

    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
                static_folder=os.path.join(os.path.dirname(__file__), 'static'))

    # Initialize database
    if db_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        db_path = os.path.join(project_root, 'data', 'volleyball.db')

    db = Database(db_path)
    db.create_tables()

    # Initialize parsing service
    parsing_service = ParsingService(db)

    # Register routes
    register_routes(app)

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
        """Get list of teams."""
        from src.database.models import Team

        search = request.args.get('search', '').strip()

        with db.session() as session:
            query = session.query(Team)
            if search:
                query = query.filter(Team.name.ilike(f'%{search}%'))
            teams = query.order_by(Team.name).all()
            result = [{'id': t.id, 'site_id': t.site_id, 'name': t.name} for t in teams]

        return jsonify({'teams': result, 'total': len(result)})

    @app.route('/api/players')
    def api_players():
        """Get list of players with MVP count and match count."""
        from src.database.models import Player, BestPlayer, MatchPlayer
        from sqlalchemy import or_, func

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'name')  # 'name' or 'mvp'

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

            if sort == 'mvp':
                query = query.order_by(func.coalesce(mvp_sq.c.mvp_count, 0).desc())
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
