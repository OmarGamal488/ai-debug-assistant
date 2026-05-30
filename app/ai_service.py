"""
ai_service.py — Isolated AI analysis layer for the Debug Assistant Platform.

Fully decoupled: no FastAPI, no SQLModel imports. Import this module in any
route and call analyze_issue(); it never raises, even on API or parse failures.
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

# Load .env without overriding env vars that are already set in the shell.
# This is intentional: tests that inject a bad key via the shell environment
# must see that key, not the real one from .env.
load_dotenv()

_ALLOWED_DIFFICULTIES = {"Beginner", "Intermediate", "Advanced"}

_SYSTEM_PROMPT = (
    "You are an expert programming mentor and code-review assistant. "
    "Your sole task is to analyse a coding problem described by the user and "
    "respond ONLY with a JSON object — no prose, no markdown. "
    "The JSON must contain exactly three keys:\n"
    '  "category"       – a short classification of the error or topic (string)\n'
    '  "difficulty"     – exactly one of "Beginner", "Intermediate", or "Advanced" (string)\n'
    '  "recommendation" – a concise learning topic or documentation suggestion (string)'
)


def _normalize_difficulty(value: str | None) -> str | None:
    """Case-insensitive match to allowed values; passthrough if unrecognised."""
    if value is None:
        return None
    stripped = value.strip()
    for allowed in _ALLOWED_DIFFICULTIES:
        if stripped.lower() == allowed.lower():
            return allowed
    return stripped  # best-effort: keep model's string if unexpected


def _build_client() -> OpenAI:
    """Construct the OpenAI-compatible client from environment variables."""
    return OpenAI(
        base_url=os.getenv("LIGHTNING_BASE_URL"),
        api_key=os.getenv("LIGHTNING_API_KEY"),
    )


def analyze_issue(language: str, issue_description: str) -> dict:
    """
    Classify a coding problem using the Lightning AI LLM.

    Parameters
    ----------
    language : str
        The programming language of the submitted issue (e.g. "python").
    issue_description : str
        Free-text description of the coding problem.

    Returns
    -------
    dict with keys:
        ai_category       (str | None)
        ai_difficulty     (str | None)  — "Beginner" | "Intermediate" | "Advanced"
        ai_recommendation (str | None)
        ai_status         (str)         — "SUCCESS" | "FAILED"
        error_message     (str | None)  — None on success; error string on failure
    """
    try:
        client = _build_client()

        user_text = (
            f"Programming language: {language}\n\n"
            f"Issue description:\n{issue_description}\n\n"
            "Respond with a JSON object containing exactly these keys: "
            '"category", "difficulty" (must be one of: Beginner, Intermediate, Advanced), '
            '"recommendation".'
        )

        response = client.chat.completions.create(
            model=os.getenv("LIGHTNING_MODEL"),
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": [{"type": "text", "text": _SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_text}],
                },
            ],
        )

        raw_content: str = response.choices[0].message.content
        parsed: dict = json.loads(raw_content)

        return {
            "ai_category": parsed.get("category"),
            "ai_difficulty": _normalize_difficulty(parsed.get("difficulty")),
            "ai_recommendation": parsed.get("recommendation"),
            "ai_status": "SUCCESS",
            "error_message": None,
        }

    except Exception as e:
        return {
            "ai_category": None,
            "ai_difficulty": None,
            "ai_recommendation": None,
            "ai_status": "FAILED",
            "error_message": str(e)[:1000],
        }
