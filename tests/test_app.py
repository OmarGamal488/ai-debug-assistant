"""test_app.py — pytest integration tests for the AI Debug Assistant FastAPI app.

Strategy: in-memory SQLite engine shared via dependency override so tests
never touch the real database.db.  All 11 specified behaviors are covered.

SECRET_KEY must be set before any import that pulls in security.py.
"""

# ---------------------------------------------------------------------------
# Bootstrap — must happen before any import of main / security
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!!")

# ---------------------------------------------------------------------------
# Standard imports
# ---------------------------------------------------------------------------
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

from app import ai_service  # noqa: E402 — needed for monkeypatch target
from app import models  # noqa: E402, F401 — registers tables on SQLModel.metadata
from app.database import get_session  # noqa: E402
from app.main import app  # noqa: E402

# ---------------------------------------------------------------------------
# In-memory test engine + dependency override (module-level, applied once)
# ---------------------------------------------------------------------------

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Override the FastAPI dependency so every request goes through test_engine.
def _override_get_session():
    """Yield a Session bound to the in-memory test engine."""
    with Session(test_engine) as session:
        yield session


app.dependency_overrides[get_session] = _override_get_session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test for full isolation."""
    SQLModel.metadata.drop_all(test_engine)
    SQLModel.metadata.create_all(test_engine)
    yield


@pytest.fixture()
def client() -> TestClient:
    """Return a TestClient with redirect-following disabled by default.

    Cookies persist across calls within the same client instance, which
    correctly models a browser session once a Set-Cookie is received.
    """
    return TestClient(app, follow_redirects=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGISTER_FORM = dict(username="alice", email="alice@example.com", password="secret123")
_LOGIN_FORM = dict(username="alice", password="secret123")


def _register(client: TestClient, *, username: str = "alice",
              email: str = "alice@example.com", password: str = "secret123") -> None:
    """Register a user; asserts success redirect."""
    resp = client.post("/register", data=dict(username=username, email=email, password=password))
    assert resp.status_code == 303, f"registration failed: {resp.text[:200]}"


def _login(client: TestClient, *, username: str = "alice", password: str = "secret123") -> None:
    """Login; asserts success redirect and cookie presence."""
    resp = client.post("/login", data=dict(username=username, password=password))
    assert resp.status_code == 303, f"login failed: {resp.text[:200]}"
    assert "session" in client.cookies, "session cookie not set after login"


_SUCCESS_AI_RESULT = {
    "ai_category": "Off-by-one Error",
    "ai_difficulty": "Intermediate",
    "ai_recommendation": "Review loop bounds",
    "ai_status": "SUCCESS",
    "error_message": None,
}

_FAILED_AI_RESULT = {
    "ai_category": None,
    "ai_difficulty": None,
    "ai_recommendation": None,
    "ai_status": "FAILED",
    "error_message": "unauthorized: invalid API key",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegister:
    """POST /register"""

    def test_success_redirects_to_login_and_persists_hashed_password(self, client):
        """On valid new credentials returns 303 to /login and stores a hashed password."""
        resp = client.post("/register", data=_REGISTER_FORM)

        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

        # Verify DB row has a non-plaintext password
        with Session(test_engine) as session:
            user = session.exec(
                select(models.User).where(models.User.username == "alice")
            ).first()
        assert user is not None, "User row not created"
        assert user.hashed_password != "secret123", "password stored in plaintext"
        assert len(user.hashed_password) > 20, "hash too short to be bcrypt"

    def test_duplicate_username_returns_200_with_error(self, client):
        """Second registration with same username re-renders form with an error."""
        _register(client)
        resp = client.post(
            "/register",
            data=dict(username="alice", email="other@example.com", password="pw123456"),
        )

        assert resp.status_code == 200
        assert "Username already exists." in resp.text

    def test_duplicate_email_returns_200_with_error(self, client):
        """Registration with existing email re-renders form with a distinct error."""
        _register(client)  # alice@example.com is now taken
        resp = client.post(
            "/register",
            data=dict(username="bob", email="alice@example.com", password="pw123456"),
        )

        assert resp.status_code == 200
        assert "Email already registered." in resp.text


class TestLogin:
    """POST /login"""

    def test_success_redirects_to_dashboard_and_sets_cookie(self, client):
        """Valid credentials return 303 to / and set a session cookie."""
        _register(client)
        resp = client.post("/login", data=_LOGIN_FORM)

        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert "session" in client.cookies

    def test_bad_credentials_returns_200_with_error(self, client):
        """Wrong password re-renders login with the standard error message."""
        _register(client)
        resp = client.post(
            "/login",
            data=dict(username="alice", password="wrongpassword"),
        )

        assert resp.status_code == 200
        assert "Invalid username or password." in resp.text


class TestDashboard:
    """GET /"""

    def test_unauthenticated_redirects_to_login(self, client):
        """GET / without a cookie is a 303 to /login."""
        resp = client.get("/")

        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"


class TestSubmit:
    """POST /submit"""

    def test_unauthenticated_redirects_to_login(self, client):
        """POST /submit without a cookie is a 303 to /login."""
        resp = client.post(
            "/submit",
            data=dict(language="python", issue_description="IndexError on empty list"),
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_success_persists_and_renders_on_dashboard(self, client, monkeypatch):
        """SUCCESS result is persisted and appears on the authenticated dashboard."""
        calls: list[tuple[str, str]] = []

        def fake_analyze(language: str, issue_description: str) -> dict:
            calls.append((language, issue_description))
            return _SUCCESS_AI_RESULT

        monkeypatch.setattr(ai_service, "analyze_issue", fake_analyze)

        _register(client)
        _login(client)

        # Submit
        resp = client.post(
            "/submit",
            data=dict(language="python", issue_description="IndexError on empty list"),
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"

        # Fake was actually called with the right arguments (no network call)
        assert len(calls) == 1
        assert calls[0] == ("python", "IndexError on empty list")

        # Dashboard shows the result
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Off-by-one Error" in dashboard.text
        assert "Intermediate" in dashboard.text
        assert "Review loop bounds" in dashboard.text
        assert "SUCCESS" in dashboard.text

        # Exactly one row persisted with the correct status
        with Session(test_engine) as session:
            rows = session.exec(select(models.ReviewSession)).all()
        assert len(rows) == 1
        assert rows[0].ai_status == "SUCCESS"
        assert rows[0].error_message is None

    def test_ai_failure_persists_and_renders_on_dashboard(self, client, monkeypatch):
        """FAILED result (with error_message) is persisted and shown on the dashboard."""
        monkeypatch.setattr(
            ai_service,
            "analyze_issue",
            lambda lang, desc: _FAILED_AI_RESULT,
        )

        _register(client)
        _login(client)

        resp = client.post(
            "/submit",
            data=dict(language="javascript", issue_description="undefined is not a function"),
        )
        assert resp.status_code == 303

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "FAILED" in dashboard.text
        assert "unauthorized: invalid API key" in dashboard.text

        with Session(test_engine) as session:
            rows = session.exec(select(models.ReviewSession)).all()
        assert len(rows) == 1
        assert rows[0].ai_status == "FAILED"
        assert rows[0].error_message == "unauthorized: invalid API key"


class TestMultiTenancy:
    """Per-user data isolation (IDOR guard)."""

    def test_user_a_submission_not_visible_on_user_b_dashboard(self, client, monkeypatch):
        """User B's dashboard must not contain any of User A's review data."""
        monkeypatch.setattr(
            ai_service,
            "analyze_issue",
            lambda lang, desc: {
                **_SUCCESS_AI_RESULT,
                "ai_category": "UniqueCategory_UserA",
            },
        )

        # Register and submit as User A
        _register(client, username="alice", email="alice@example.com")
        _login(client, username="alice")
        client.post(
            "/submit",
            data=dict(language="python", issue_description="Alice's bug"),
        )

        # Clear cookies, register and login as User B
        client.cookies.clear()
        _register(client, username="bob", email="bob@example.com")
        _login(client, username="bob")

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "UniqueCategory_UserA" not in dashboard.text, (
            "User B can see User A's review session — IDOR leak!"
        )


class TestLogout:
    """GET /logout"""

    def test_logout_clears_cookie_and_subsequent_dashboard_redirects(self, client):
        """Logout returns 303 to /login, removes the cookie, and GET / then redirects."""
        _register(client)
        _login(client)

        # Cookie should be present before logout
        assert "session" in client.cookies

        resp = client.get("/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

        # After logout the cookie jar should be empty (or not contain session)
        assert "session" not in client.cookies

        # The real guard: GET / must redirect back to login
        resp2 = client.get("/")
        assert resp2.status_code == 303
        assert resp2.headers["location"] == "/login"
