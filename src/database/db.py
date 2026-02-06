"""Database connection and session management."""

import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base


class Database:
    """Database connection manager."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default path: data/volleyball.db relative to project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            db_path = os.path.join(project_root, "data", "volleyball.db")

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def create_tables(self):
        """Create all tables in the database."""
        Base.metadata.create_all(self.engine)

    def drop_tables(self):
        """Drop all tables (use with caution!)."""
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session(self) -> Session:
        """Context manager for database sessions."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self) -> Session:
        """Get a new session (caller is responsible for closing)."""
        return self.SessionLocal()


# Global database instance
_db: Database = None


def get_db(db_path: str = None) -> Database:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        _db = Database(db_path)
        _db.create_tables()
    return _db


def init_db(db_path: str = None) -> Database:
    """Initialize database with fresh tables."""
    db = Database(db_path)
    db.create_tables()
    return db
