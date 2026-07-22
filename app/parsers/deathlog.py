import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from app.parsers.base import ParseError, ParseResult

_PLAYER_ID = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
_NPC_MARKERS = ("npc", "bot", "bandit", "scav", "soldier", "mutant", "wolf", "bear")
_ENVIRONMENT_CAUSES = ("falling", "fall", "bleeding", "radiation", "drowning", "starvation", "dehydration", "environment")
_SUICIDE_CAUSES = ("suicide", "relocation")
_HEADER_NAMES = {"date", "time", "datetime", "killer", "killer_name", "victim", "victim_name", "weapon", "distance"}


def normalize_player_name(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _same_entity(killer_id: str | None, killer_name: str | None, victim_id: str | None, victim_name: str | None) -> bool:
    if killer_id and victim_id:
        return killer_id.casefold() == victim_id.casefold()
    return bool(normalize_player_name(killer_name) and normalize_player_name(killer_name) == normalize_player_name(victim_name))


def _contains(value: str | None, markers: tuple[str, ...]) -> bool:
    normalized = normalize_player_name(value) or ""
    return any(marker in normalized for marker in markers)


def classify_victim_type(victim_name: str | None, victim_id: str | None) -> str:
    if victim_id and _PLAYER_ID.fullmatch(victim_id):
        return "player"
    if _contains(victim_name, _NPC_MARKERS):
        return "npc"
    if victim_name or victim_id:
        return "unknown"
    return "unknown"


def classify_killer_type(killer_name: str | None, killer_id: str | None, victim_name: str | None = None, victim_id: str | None = None, cause: str | None = None) -> str:
    if _contains(cause, _ENVIRONMENT_CAUSES):
        return "environment"
    if _same_entity(killer_id, killer_name, victim_id, victim_name):
        return "self"
    if killer_id and _PLAYER_ID.fullmatch(killer_id):
        return "player"
    if _contains(killer_name, _NPC_MARKERS):
        return "npc"
    if _contains(killer_name, ("environment", "world")):
        return "environment"
    return "unknown"


def classify_death_event(killer_type: str, victim_type: str) -> str:
    if killer_type == "self":
        return "suicide"
    if killer_type == "environment":
        return "environmental_death"
    if killer_type == "player" and victim_type == "player":
        return "player_kill"
    if killer_type == "player" and victim_type == "npc":
        return "npc_kill"
    if killer_type == "npc" and victim_type == "player":
        return "killed_by_npc"
    return "unknown_death"


def is_player_kill(event_type: str) -> bool:
    return event_type == "player_kill"


def is_suicide(event_type: str) -> bool:
    return event_type == "suicide"


def is_environmental_death(event_type: str) -> bool:
    return event_type == "environmental_death"


def combat_fingerprint(event: dict[str, Any]) -> str:
    stable = {
        key: event.get(key) for key in (
            "event_time", "killer_id", "killer_name_normalized", "victim_id", "victim_name_normalized",
            "weapon_name", "cause", "distance_meters", "killer_platform", "victim_platform",
        )
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class DeathlogParser:
    name = "deadside.deathlog.csv"
    version = "1.0"

    def parse(self, content: bytes, source_path: str) -> ParseResult:
        text, encoding = _decode(content)
        delimiter = _delimiter(text)
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        entities: list[dict[str, Any]] = []
        warnings: list[str] = []
        header: list[str] | None = None
        for line, row in enumerate(rows, 1):
            if not any(cell.strip() for cell in row):
                continue
            if header is None and not entities and _is_header(row):
                header = [_header_key(cell) for cell in row]
                continue
            try:
                entity = self._parse_row(row, header, source_path, line)
            except ParseError as exc:
                warnings.append(f"line {line} ignored: {exc}")
                continue
            entities.append(entity)
        if not entities:
            raise ParseError("deathlog has no complete event rows")
        warnings.append(f"encoding={encoding}; delimiter={repr(delimiter)}; header={header is not None}")
        return ParseResult(self.name, self.version, entities, warnings)

    def _parse_row(self, row: list[str], header: list[str] | None, source_path: str, source_line: int) -> dict[str, Any]:
        if header:
            values = {key: row[index].strip() if index < len(row) else "" for index, key in enumerate(header)}
            raw = [
                _pick(values, "date", "time", "datetime", "event_time"),
                _pick(values, "killer", "killer_name"), _pick(values, "killer_id", "killer_steam_id", "killer_eos_id"),
                _pick(values, "victim", "victim_name"), _pick(values, "victim_id", "victim_steam_id", "victim_eos_id"),
                _pick(values, "weapon", "cause"), _pick(values, "distance", "distance_meters"),
                _pick(values, "killer_platform"), _pick(values, "victim_platform"), "",
            ]
        else:
            if len(row) < 7:
                raise ParseError(f"expected at least 7 columns, found {len(row)}")
            raw = [cell.strip() for cell in row] + [""] * max(0, 10 - len(row))
        event_time = _parse_time(raw[0])
        killer_name, killer_id = raw[1] or None, raw[2] or None
        victim_name, victim_id = raw[3] or None, raw[4] or None
        cause_or_weapon = raw[5] or None
        victim_type = classify_victim_type(victim_name, victim_id)
        killer_type = classify_killer_type(killer_name, killer_id, victim_name, victim_id, cause_or_weapon)
        event_type = classify_death_event(killer_type, victim_type)
        known_cause = killer_type in {"environment", "self"} and _contains(cause_or_weapon, _ENVIRONMENT_CAUSES + _SUICIDE_CAUSES)
        event: dict[str, Any] = {
            "event_time": event_time,
            "event_type": event_type,
            "victim_id": victim_id, "victim_name": victim_name, "victim_name_normalized": normalize_player_name(victim_name), "victim_type": victim_type,
            "killer_id": killer_id, "killer_name": killer_name, "killer_name_normalized": normalize_player_name(killer_name), "killer_type": killer_type,
            "weapon_id": None, "weapon_name": None if known_cause else cause_or_weapon, "cause": cause_or_weapon if known_cause else None,
            "distance_meters": _float(raw[6]),
            "killer_platform": raw[7] or None, "victim_platform": raw[8] or None,
            "is_player_kill": is_player_kill(event_type), "is_suicide": is_suicide(event_type), "is_environmental": is_environmental_death(event_type),
            "world_x": None, "world_y": None, "world_z": None, "map_x": None, "map_y": None, "grid": None,
            "source_file": source_path, "source_line": source_line,
            "raw_data": {"columns": raw[:10]},
        }
        event["fingerprint"] = combat_fingerprint(event)
        return event


def _decode(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "cp1251"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ParseError("deathlog encoding is unsupported")


def _delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=";,\t|").delimiter
    except csv.Error:
        return ";"


def _parse_time(value: str) -> datetime:
    for pattern in ("%Y.%m.%d-%H.%M.%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value.strip(), pattern)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            continue
    raise ParseError("invalid event timestamp")


def _is_header(row: list[str]) -> bool:
    if not row:
        return False
    try:
        _parse_time(row[0])
        return False
    except ParseError:
        normalized = {_header_key(cell) for cell in row}
        return bool(normalized & _HEADER_NAMES)


def _header_key(value: str) -> str:
    return (normalize_player_name(value) or "").replace(" ", "_")


def _pick(values: dict[str, str], *keys: str) -> str:
    return next((values[key] for key in keys if values.get(key)), "")


def _float(value: str) -> float | None:
    if not value.strip():
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None
