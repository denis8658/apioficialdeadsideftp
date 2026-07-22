import json
import re
from typing import Any

from app.parsers.base import ParseError
from app.parsers.format_detector import FileFormat, decode_text, detect_format

_SENSITIVE_KEY = re.compile(r"(?:password|passwd|token|secret|api[_-]?key|authorization)", re.IGNORECASE)


def load_json_object(content: bytes, source_path: str, label: str) -> dict[str, Any]:
    """Decode a complete UTF-8 JSON object and provide transport-safe errors."""
    if detect_format(content, source_path) != FileFormat.JSON:
        raise ParseError(f"{label} file is not complete JSON")
    try:
        value = json.loads(decode_text(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        raise ParseError(f"{label} root must be an object")
    return value


def redact_sensitive(value: Any) -> Any:
    """Remove credential-like fields recursively before data is persisted or returned."""
    if isinstance(value, dict):
        return {key: redact_sensitive(item) for key, item in value.items() if not _SENSITIVE_KEY.search(str(key))}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def normalize_numbered_objects(container: Any, prefix: str) -> list[dict[str, Any]]:
    """Convert Deadside's Item0/Item1 style objects to an ordered JSON list."""
    if not isinstance(container, dict):
        return []
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    rows: list[tuple[int, dict[str, Any]]] = []
    for key, value in container.items():
        match = pattern.fullmatch(key)
        if match and isinstance(value, dict):
            rows.append((int(match.group(1)), {"slot": int(match.group(1)), **redact_sensitive(value)}))
    return [value for _, value in sorted(rows)]
