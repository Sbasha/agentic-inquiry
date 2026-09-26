#!/usr/bin/env python3
"""Verify deterministic writing-workflow contracts without certifying taste."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_REGISTERS = {
    "tutorial",
    "how_to",
    "reference",
    "technical_explanation",
    "architecture_decision",
    "code_comment_docstring",
    "cli_output_error",
    "project_page",
    "technical_essay",
    "personal_cultural_essay",
}
ALLOWED_FORMS = {"argument", "explanation", "story", "mixed", "operational"}
ALLOWED_BASES = {
    "verified_fact",
    "direct_experience",
    "observation",
    "inference",
    "judgment",
    "working_hypothesis",
    "aspiration",
    "speculation",
}
ALLOWED_DISPOSITIONS = {"approved", "rejected", "borderline", "justified_exception"}
ALLOWED_CALIBRATION_AUTHORITIES = {
    "direct_private_calibration",
    "explicit_private_authority",
    "synthetic_system_expectation",
}
ALLOWED_CONTENT_CLASSES = {
    "public_authorial",
    "public_operational",
    "generated_mechanical",
    "private_only",
}
ALLOWED_APPROVAL_CLASSES = {
    "human_approval",
    "delegated_domain",
    "generated_mechanical",
    "private_only",
}
ALLOWED_DISCLOSURE_STATES = {"public", "review_required", "reserved", "private"}
PRIVATE_PLACEHOLDER = re.compile(r"\{\{PRIVATE_PLACEHOLDER:[^}]+\}\}")
MEANING_STRING_FIELDS = {
    "title",
    "summary",
    "body",
    "byline",
    "status_and_limitations",
    "seo_title",
    "seo_description",
}
MEANING_LIST_FIELDS = {
    "headings",
    "captions",
    "alt_text",
    "visible_labels",
    "calls_to_action",
    "distribution_copy",
    "public_links",
}
MEANING_FIELDS = MEANING_STRING_FIELDS | MEANING_LIST_FIELDS


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in strings(child)]
    return []


def verify_brief(brief: dict[str, Any], for_public: bool) -> list[str]:
    errors: list[str] = []
    if brief.get("schema") != "EditorialBrief/v1":
        errors.append("brief.schema must be EditorialBrief/v1")
    if brief.get("register") not in ALLOWED_REGISTERS:
        errors.append("brief.register is unsupported")
    if brief.get("content_class") not in ALLOWED_CONTENT_CLASSES:
        errors.append("brief.content_class is unsupported")
    if brief.get("approval_class") not in ALLOWED_APPROVAL_CLASSES:
        errors.append("brief.approval_class is unsupported")
    if brief.get("disclosure_state") not in ALLOWED_DISCLOSURE_STATES:
        errors.append("brief.disclosure_state is unsupported")
    if for_public and brief.get("approval_class") == "private_only":
        errors.append("a public brief cannot use private_only approval")
    if for_public and brief.get("disclosure_state") != "public":
        errors.append("a public brief requires public disclosure_state")
    form = brief.get("rhetorical_form")
    if form not in ALLOWED_FORMS:
        errors.append("brief.rhetorical_form is unsupported")
    if form == "mixed" and brief.get("primary_form") not in {"argument", "story"}:
        errors.append("mixed work requires primary_form argument or story")
    if brief.get("draftable") and brief.get("blockers"):
        errors.append("a draftable brief cannot have blockers")

    statement = brief.get("governing_statement")
    if not isinstance(statement, dict) or not statement.get("text"):
        errors.append("brief.governing_statement requires text")
    elif (
        for_public
        and form in {"argument", "explanation"}
        and statement.get("ownership")
        not in {
            "user_stated",
            "user_approved",
        }
    ):
        errors.append("public argument or explanation requires user-owned governing statement")

    claims = brief.get("claims", [])
    if not isinstance(claims, list):
        errors.append("brief.claims must be a list")
    else:
        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append(f"claim {index} must be an object")
                continue
            if claim.get("basis") not in ALLOWED_BASES:
                errors.append(f"claim {index} has unsupported basis")
            if for_public and claim.get("disclosure") != "public":
                errors.append(f"claim {index} is not public for this use")
            if claim.get("basis") == "verified_fact" and not claim.get("evidence_refs"):
                errors.append(f"verified claim {index} requires evidence_refs")

    if form in {"story", "mixed"}:
        material = brief.get("story_material")
        if not isinstance(material, dict):
            errors.append("story or mixed work requires story_material")
    return errors


def is_aware_iso8601(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def verify_golden(corpus: Any) -> list[str]:
    if not isinstance(corpus, list):
        return ["golden corpus must be a JSON list"]
    errors: list[str] = []
    seen: dict[str, set[str]] = {register: set() for register in ALLOWED_REGISTERS}
    ids: set[str] = set()
    for index, case in enumerate(corpus):
        if not isinstance(case, dict):
            errors.append(f"golden case {index} must be an object")
            continue
        case_id = case.get("id")
        if not case_id or case_id in ids:
            errors.append(f"golden case {index} has a missing or duplicate id")
        ids.add(case_id)
        register = case.get("register")
        disposition = case.get("disposition")
        if register not in ALLOWED_REGISTERS:
            errors.append(f"golden case {case_id} has unsupported register")
            continue
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(f"golden case {case_id} has unsupported disposition")
            continue
        seen[register].add(disposition)
        if case.get("rhetorical_form") not in ALLOWED_FORMS:
            errors.append(f"golden case {case_id} has unsupported rhetorical_form")
        if case.get("calibration_authority") not in ALLOWED_CALIBRATION_AUTHORITIES:
            errors.append(f"golden case {case_id} has unsupported calibration_authority")
        for key in ("text", "reason", "rule"):
            if not case.get(key):
                errors.append(f"golden case {case_id} requires {key}")
        if disposition == "justified_exception" and not case.get("exception"):
            errors.append(f"golden case {case_id} requires exception")
    for register, dispositions in sorted(seen.items()):
        missing = ALLOWED_DISPOSITIONS - dispositions
        if missing:
            errors.append(f"{register} lacks dispositions: {', '.join(sorted(missing))}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--golden-corpus", type=Path)
    parser.add_argument("--public-review", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    brief = load_json(args.brief) if args.brief else None

    if brief is not None:
        errors.extend(verify_brief(brief, args.public_review))
    if args.golden_corpus:
        errors.extend(verify_golden(load_json(args.golden_corpus)))
    if not any((args.brief, args.golden_corpus)):
        errors.append("provide --brief or --golden-corpus")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "conformant", "taste_certified": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
