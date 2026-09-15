"""Deterministic identifiers derived from names, used to build child workflow ids (pure, usable in workflow code)."""

import re


def event_slug(name: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:limit].rstrip("-") or "event"
