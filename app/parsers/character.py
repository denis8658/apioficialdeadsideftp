from pathlib import PurePosixPath
from typing import Any

from app.parsers.base import ParseError, ParseResult
from app.parsers.json_helpers import load_json_object, redact_sensitive


class CharacterParser:
    name = "deadside.character.json"
    version = "1.0"

    def parse(self, content: bytes, source_path: str) -> ParseResult:
        data = load_json_object(content, source_path, "character")
        if not isinstance(data, dict) or not isinstance(data.get("BaseCharacter"), dict):
            raise ParseError("missing BaseCharacter object")
        base: dict[str, Any] = data["BaseCharacter"]
        player_id = PurePosixPath(source_path.replace("\\", "/")).stem
        inventory = {key: value for key, value in base.items() if "Inventory" in key}
        entity = {
            "player_id": player_id,
            "login": base.get("Login"),
            "map_name": base.get("Map"),
            "pos_x": _number(base.get("PosX")),
            "pos_y": _number(base.get("PosY")),
            "pos_z": _number(base.get("PosZ")),
            "rot_yaw": _number(base.get("RotYaw")),
            "health": _number(base.get("Health")),
            "inventory": inventory,
            "raw_data": redact_sensitive(data),
        }
        return ParseResult(self.name, self.version, [entity], [])


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
