from __future__ import annotations

INSIGHT_FIELDS = (
    "objections",
    "commitments",
    "follow_up_hints",
    "customer_questions",
    "agent_action_items",
    "escalation_notes",
)
MAX_INSIGHT_ITEMS_PER_FIELD = 10
MAX_INSIGHT_TEXT_LENGTH = 500


def empty_analysis_insights() -> dict[str, list[str]]:
    return {field: [] for field in INSIGHT_FIELDS}


def normalize_analysis_insights(value: object) -> dict[str, list[str]]:
    insights = empty_analysis_insights()
    if not isinstance(value, dict):
        return insights

    for field in INSIGHT_FIELDS:
        items = value.get(field)
        if not isinstance(items, list):
            continue

        normalized_items: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, str):
                continue
            normalized = _normalize_insight_text(item)
            if not normalized or normalized in seen:
                continue
            normalized_items.append(normalized)
            seen.add(normalized)
            if len(normalized_items) == MAX_INSIGHT_ITEMS_PER_FIELD:
                break
        insights[field] = normalized_items

    return insights


def _normalize_insight_text(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= MAX_INSIGHT_TEXT_LENGTH:
        return normalized
    return normalized[:MAX_INSIGHT_TEXT_LENGTH].rstrip()
