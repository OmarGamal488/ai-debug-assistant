"""main.py — FastAPI application: auth routes + dashboard for AI Debug Assistant Platform.

SSR with Jinja2 templates. Session state lives in a signed HTTP-only cookie.
All POST → redirect responses use status_code=303 (PRG pattern).
"""

from contextlib import asynccontextmanager

from app import ai_service  # imported as module so monkeypatching works in tests
from app.database import get_session, init_db
from app.models import ReviewSession, User
from app.security import (
    COOKIE_MAX_AGE,
    SESSION_COOKIE,
    get_current_user,
    hash_password,
    make_session_token,
    verify_password,
)
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

load_dotenv()


# ---------------------------------------------------------------------------
# Lifespan (startup)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database tables on startup."""
    init_db()
    yield


# Also call init_db() at import time so the TestClient (which doesn't use
# a context-manager / lifespan trigger) still has tables available.
init_db()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="AI Debug Assistant", lifespan=lifespan)
app.mount("/style", StaticFiles(directory="style"), name="style")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


@app.get("/register")
def register_page(request: Request):
    """Render the registration form."""
    return templates.TemplateResponse(request, "register.html")


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    """Create a new user account.

    Re-renders the form with an error if username or email is already taken.
    On success, redirects to /login (303).
    """
    # Check for duplicate username or email
    existing = session.exec(
        select(User).where((User.username == username) | (User.email == email))
    ).first()

    if existing:
        error = (
            "Username already exists."
            if existing.username == username
            else "Email already registered."
        )
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": error},
            status_code=200,
        )

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
    )
    session.add(user)
    session.commit()

    return RedirectResponse(url="/login", status_code=303)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@app.get("/login")
def login_page(request: Request):
    """Render the login form."""
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    """Authenticate a user and set a signed session cookie.

    Re-renders the form with an error on bad credentials.
    On success, redirects to / (303) with the cookie set.
    """
    user = session.exec(select(User).where(User.username == username)).first()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password."},
            status_code=200,
        )

    token = make_session_token(user.id)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
        # secure=True  # Uncomment in production (HTTPS only)
    )
    return resp


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@app.get("/logout")
def logout():
    """Clear the session cookie and redirect to /login."""
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------------------
# Dashboard (/)
# ---------------------------------------------------------------------------


@app.get("/")
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
):
    """Render the authenticated user's dashboard with their review history.

    Redirects to /login if not authenticated.
    """
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    sessions = session.exec(
        select(ReviewSession)
        .where(ReviewSession.user_id == user.id)
        .order_by(ReviewSession.created_at.desc())
    ).all()

    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "sessions": sessions},
    )


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


@app.post("/submit")
def submit(
    request: Request,
    language: str = Form(...),
    issue_description: str = Form(...),
    session: Session = Depends(get_session),
):
    """Accept a code-review submission, classify it with AI, and redirect to /.

    Redirects to /login if not authenticated.
    Uses PRG (Post/Redirect/Get) to prevent double-submit on refresh.
    """
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Persist with PENDING status before calling AI (ensures the row exists
    # even if the AI call is slow or this process dies mid-flight)
    review = ReviewSession(
        user_id=user.id,
        language=language,
        issue_description=issue_description,
        ai_status="PENDING",
    )
    session.add(review)
    session.commit()
    session.refresh(review)

    # Call AI service — never raises, always returns a dict with the 5 keys
    result = ai_service.analyze_issue(language, issue_description)

    review.ai_category = result["ai_category"]
    review.ai_difficulty = result["ai_difficulty"]
    review.ai_recommendation = result["ai_recommendation"]
    review.ai_status = result["ai_status"]
    review.error_message = result["error_message"]

    session.add(review)
    session.commit()

    return RedirectResponse(url="/", status_code=303)
