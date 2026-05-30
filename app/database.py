"""Database engine, session dependency, and table initialisation for the AI Debug Assistant Platform.

Usage:
  - FastAPI routes declare `session: Session = Depends(get_session)` for DB access.
  - Call `init_db()` once at application startup to create all tables.
"""

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = "sqlite:///./database.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request.

    Opens a SQLModel Session bound to the shared engine, yields it to the
    route handler, then closes it automatically — even if an exception is raised.
    """
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create all SQLModel tables in the database if they do not already exist.

    The models module is imported here (not at the top of this file) to avoid
    circular imports while still ensuring both table classes are registered on
    SQLModel.metadata before create_all is called.
    """
    from app import models  # noqa: F401  registers tables on SQLModel.metadata

    SQLModel.metadata.create_all(engine)
