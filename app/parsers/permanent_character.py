from pathlib import PurePosixPath
from typing import Any

from app.parsers.base import ParseError, ParseResult
from app.parsers.json_helpers import load_json_object, redact_sensitive


class PermanentCharacterParser:
    name = "deadside.character_permanent.json"
    version = "1.0"

    def parse(self, content: bytes, source_path: str) -> ParseResult:
        data = load_json_object(content, source_path, "permanent character")
        base = data.get("BaseCharacter")
        character = data.get("Character")
        if not isinstance(base, dict) or not isinstance(character, dict):
            raise ParseError("permanent character requires BaseCharacter and Character objects")
        achievements = _achievements(character.get("Achievements"))
        player_id = PurePosixPath(source_path.replace("\\", "/")).stem
        entity = {
            "player_id": player_id,
            "login": base.get("Login") if isinstance(base.get("Login"), str) else None,
            "achievements": achievements,
            "achievement_count": len(achievements),
            "progression": redact_sensitive(character),
            "raw_data": redact_sensitive(data),
        }
        return ParseResult(self.name, self.version, [entity], [])


def _achievements(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    indexes = sorted(
        int(key[4:]) for key in value
        if key.startswith("Type") and key[4:].isdigit() and isinstance(value[key], str)
    )
    return [
        {
            "index": index,
            "type": value[f"Type{index}"],
            "value": value.get(f"Value{index}"),
            "bits_value": value.get(f"BitsValue{index}"),
        }
        for index in indexes
    ]
