"""SQLModel table models for the AI Debug Assistant Platform.

Two tables with a 1:N relationship:
  - User          (users)
  - ReviewSession (review_sessions)
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """Registered platform user.

    Stores credentials (hashed) and owns zero or more ReviewSession rows.
    """

    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, nullable=False)
    email: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)

    sessions: list["ReviewSession"] = Relationship(back_populates="user")


class ReviewSession(SQLModel, table=True):
    """A single code-review request submitted by a user.

    Records the submitted problem, the AI's structured analysis, and execution
    telemetry (status, error message) so every outcome is auditable.
    """

    __tablename__ = "review_sessions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)

    language: str = Field(nullable=False)
    issue_description: str = Field(nullable=False)

    # AI analysis fields — populated after a successful AI call
    ai_category: str | None = Field(default=None)
    ai_difficulty: str | None = Field(default=None)        # Beginner / Intermediate / Advanced
    ai_recommendation: str | None = Field(default=None)

    # Execution telemetry
    ai_status: str = Field(default="PENDING", nullable=False)  # PENDING / SUCCESS / FAILED
    error_message: str | None = Field(default=None)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    user: Optional["User"] = Relationship(back_populates="sessions")
