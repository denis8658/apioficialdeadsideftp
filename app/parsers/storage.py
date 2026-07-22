import re
from pathlib import PurePosixPath

from app.parsers.base import ParseError, ParseResult
from app.parsers.json_helpers import load_json_object, normalize_numbered_objects, redact_sensitive

_STORAGE_NAME = re.compile(
    r"^(?P<player_id>-?\d+)_itemstorage_(?P<world>world_\d+)_(?P<grid>X\d+_Y\d+)_(?P<storage_type>.+)$",
    re.IGNORECASE,
)


class StorageParser:
    name = "deadside.storage.json"
    version = "1.0"

    def parse(self, content: bytes, source_path: str) -> ParseResult:
        data = load_json_object(content, source_path, "storage")
        inventory = data.get("Inventory")
        if not isinstance(inventory, dict):
            raise ParseError("storage Inventory must be an object")
        storage_id = PurePosixPath(source_path.replace("\\", "/")).stem
        match = _STORAGE_NAME.fullmatch(storage_id)
        warnings: list[str] = []
        if match is None:
            warnings.append("storage filename does not match the known Deadside pattern")
            metadata = {"player_id": None, "world": None, "grid": None, "storage_type": None}
        else:
            metadata = match.groupdict()
        entity = {
            "storage_id": storage_id,
            **metadata,
            "inventory": redact_sensitive(inventory),
            "items": normalize_numbered_objects(inventory, "Item"),
            "item_count": len(normalize_numbered_objects(inventory, "Item")),
            "raw_data": redact_sensitive(data),
        }
        return ParseResult(self.name, self.version, [entity], warnings)
