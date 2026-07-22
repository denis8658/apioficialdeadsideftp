import re
from urllib.parse import urlsplit


def parse_csv(value: str, *, uppercase: bool = False) -> list[str]:
    """Parse a CSV setting, trimming blanks and removing duplicates in order."""
    result: list[str] = []
    seen: set[str] = set()
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if uppercase:
            item = item.upper()
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def normalize_origin(origin: str) -> str:
    """Validate and normalize an HTTP(S) browser origin."""
    value = origin.strip()
    if value == "*":
        return value
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid origin: {origin!r}") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"origin must use http or https: {origin!r}")
    if not parsed.hostname:
        raise ValueError(f"origin must contain a hostname: {origin!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"origin cannot contain credentials: {origin!r}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"origin cannot contain path, query, or fragment: {origin!r}")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port_suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme.lower()}://{host}{port_suffix}"


def normalize_origins(value: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in parse_csv(value):
        normalized = normalize_origin(item)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def validate_origin_regex(value: str) -> str | None:
    pattern = value.strip()
    if not pattern:
        return None
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError("CORS_ALLOWED_ORIGIN_REGEX is not a valid regular expression") from exc
    return pattern


def websocket_origin_allowed(origin: str | None, allowed_origins: list[str], allow_missing: bool) -> bool:
    if origin is None:
        return allow_missing
    try:
        normalized = normalize_origin(origin)
    except ValueError:
        return False
    return "*" in allowed_origins or normalized in allowed_origins
