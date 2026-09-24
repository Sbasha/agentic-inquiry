"""Load the labelled long-session set. Questions and gold ids stay data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_sessions(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    sessions = document.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("sessions.json needs a non-empty sessions list")
    for session in sessions:
        if not isinstance(session, dict) or not session.get("id"):
            raise ValueError("each session needs an id")
        turns = session.get("turns")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"{session['id']} has no turns")
        known: list[str] = []
        questions = 0
        for turn in turns:
            if not isinstance(turn, dict):
                raise ValueError(f"{session['id']} has a turn that is not an object")
            if turn.get("role") == "question":
                questions += 1
                _check_question(str(session["id"]), turn, known)
                continue
            identifier = turn.get("id")
            content = turn.get("content")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError(f"{session['id']} has a capture without an id")
            if identifier in known:
                raise ValueError(f"{session['id']} repeats {identifier}")
            if not isinstance(content, str) or not content:
                raise ValueError(f"{session['id']} capture {identifier} has no content")
            known.append(identifier)
        if questions != 1:
            raise ValueError(f"{session['id']} needs exactly one question")
    return sessions


def _check_question(session_id: str, turn: dict[str, Any], known: list[str]) -> None:
    relevant = turn.get("relevant")
    if not isinstance(relevant, list) or not all(isinstance(item, str) for item in relevant):
        raise ValueError(f"{session_id} question needs a relevant id list")
    if turn.get("abstain"):
        if relevant:
            raise ValueError(f"{session_id} abstention has a gold location")
        return
    if not relevant:
        raise ValueError(f"{session_id} question has no relevant id")
    missing = [item for item in relevant if item not in known]
    if missing:
        raise ValueError(f"{session_id} question names unknown ids: {', '.join(missing)}")
    omit = turn.get("must_omit") or []
    if not isinstance(omit, list) or not all(isinstance(item, str) and item in known for item in omit):
        raise ValueError(f"{session_id} must_omit names an unknown id")
