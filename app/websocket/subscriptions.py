from typing import Any

ALLOWED_FILTERS = {"entity_type", "entity_id", "player_id", "grid"}


def sanitize_filters(filters: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in filters.items() if key in ALLOWED_FILTERS and value is not None}


def subscription_matches(event: dict[str, Any], events: set[str] | None, filters: dict[str, str]) -> bool:
    if events is not None and event.get("event") not in events:
        return False
    data = event.get("data") or {}
    for key, expected in filters.items():
        if key in {"entity_type", "entity_id"}:
            actual = event.get(key)
        elif key == "player_id":
            candidates = {
                data.get("player_id"),
                (data.get("killer") or {}).get("id") if isinstance(data.get("killer"), dict) else None,
                (data.get("victim") or {}).get("id") if isinstance(data.get("victim"), dict) else None,
            }
            if expected not in candidates:
                return False
            continue
        else:
            actual = data.get(key) or (data.get("map_position") or {}).get(key)
        if str(actual) != expected:
            return False
    return True
