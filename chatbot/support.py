"""Deterministic post-purchase language helpers for ApBot.

These rules complement—not replace—the trained intent model. Returns and order
support need predictable behavior even when customers use typos or wording that
was not represented during model training.
"""
from __future__ import annotations

import re
from datetime import datetime

RETURN_INCIDENT_WORDS = {
    "damaged": "damaged",
    "damage": "damaged",
    "damged": "damaged",  # common customer typo
    "broken": "damaged",
    "defective": "defective",
    "faulty": "defective",
    "not working": "defective",
    "wrong item": "wrong_item",
    "wrong product": "wrong_item",
    "missing": "missing_item",
    "refund": "return",
    "return": "return",
    "exchange": "exchange",
}


def detect_commerce_intent(message: str, predicted_intent: str) -> str:
    """Override uncertain ML output for high-value commerce/support requests."""
    text = message.casefold()
    if any(term in text for term in RETURN_INCIDENT_WORDS):
        return "returns"
    if any(term in text for term in (
        "customer support", "customer service", "support number", "toll free",
        "toll-free", "helpline", "representative", "human agent", "real person",
        "contact support", "contact number",
    )):
        return "contact_support"
    if any(term in text for term in ("track", "where is", "order status", "delivery status")) and any(
        term in text for term in ("order", "package", "delivery", "shipment", "product", "headphone")
    ):
        return "order_tracking"
    return predicted_intent


def _simple_terms(value: str) -> set[str]:
    """Normalize simple plurals so headphone/headphones both match."""
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", (value or "").casefold()):
        terms.add(token)
        if token.endswith("ies") and len(token) > 4:
            terms.add(token[:-3] + "y")
        elif token.endswith("s") and len(token) > 3:
            terms.add(token[:-1])
    return terms


def match_order_items(message: str, items: list[dict]) -> list[dict]:
    """Rank a customer's purchased items by product words used in a message."""
    ignored = {
        "order", "product", "item", "received", "receive", "recievded", "arrived",
        "want", "wanna", "return", "refund", "exchange", "damaged", "damage",
        "damged", "broken", "defective", "faulty", "wrong", "missing", "please",
        "help", "my", "the", "this", "that", "and", "with", "not", "working",
        "delivery",
    }
    message_terms = _simple_terms(message) - ignored
    ranked: list[tuple[int, dict]] = []
    for item in items:
        searchable = " ".join(str(item.get(key) or "") for key in ("name", "brand", "category"))
        product_terms = _simple_terms(searchable)
        score = len(message_terms & product_terms)
        name = (item.get("name") or "").casefold()
        if name and name in message.casefold():
            score += 5
        if score:
            ranked.append((score, item))
    if not ranked:
        return []
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("order_date") or datetime.min), reverse=True)
    top_score = ranked[0][0]
    return [item for score, item in ranked if score == top_score]


def product_name_summary(items: list[dict], limit: int = 3) -> str:
    """Build a readable product-first order label instead of exposing only IDs."""
    names = list(dict.fromkeys(item.get("name") or "Product" for item in items))
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more item(s)"


def classify_return_issue(message: str) -> str:
    text = message.casefold()
    for phrase, issue_type in RETURN_INCIDENT_WORDS.items():
        if phrase in text:
            return issue_type
    return "return"
