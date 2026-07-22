import re
from typing import Any

from app.parsers.base import ParseError, ParseResult
from app.parsers.character import _number
from app.parsers.json_helpers import load_json_object, redact_sensitive

_VEHICLE_KEY = re.compile(r"^Vehicle\d+$")


class VehicleParser:
    name = "deadside.vehicle.json"
    version = "1.0"

    def parse(self, content: bytes, source_path: str) -> ParseResult:
        data = load_json_object(content, source_path, "vehicle")
        warnings: list[str] = []
        keys = [key for key in data if _VEHICLE_KEY.fullmatch(key) and isinstance(data[key], dict)]
        if isinstance(data.get("Count"), int) and data["Count"] != len(keys):
            warnings.append(f"Count={data['Count']} but found {len(keys)} VehicleN objects")
        entities: list[dict[str, Any]] = []
        for key in sorted(keys, key=lambda value: int(value[7:])):
            row = data[key]
            inner = row.get("Vehicle") if isinstance(row.get("Vehicle"), dict) else {}
            uid = inner.get("VehicleUID")
            if not uid:
                warnings.append(f"{key} ignored: VehicleUID missing")
                continue
            actor_id = row.get("ActorID")
            entities.append({
                "vehicle_uid": str(uid),
                "actor_id": actor_id,
                "display_name": friendly_vehicle_name(actor_id),
                "pos_x": _number(row.get("X")),
                "pos_y": _number(row.get("Y")),
                "pos_z": _number(row.get("Z")),
                "rotation": {k: row[k] for k in ("qX", "qY", "qZ", "qW", "RotYaw") if k in row},
                "fuel": _number(inner.get("Fuel")),
                "durability": _number(inner.get("Durability", inner.get("Drb"))),
                "lock_state": inner.get("LockValue") if isinstance(inner.get("LockValue"), int) else None,
                "inventory": redact_sensitive(inner.get("Inventory")) if isinstance(inner.get("Inventory"), dict) else {},
                "metadata": redact_sensitive({k: v for k, v in inner.items() if k not in {"Inventory", "VehicleUID"}}),
                "raw_data": redact_sensitive(row),
            })
        if keys and not entities:
            raise ParseError("no vehicle has a stable VehicleUID")
        return ParseResult(self.name, self.version, entities, warnings)


def friendly_vehicle_name(actor_id: Any) -> str | None:
    if not isinstance(actor_id, str):
        return None
    name = re.sub(r"^BP_(?:SFPS)?Vehicle_", "", actor_id)
    name = re.sub(r"_C$", "", name)
    return name.replace("_", " ").strip() or actor_id


def public_vehicle_data(entity: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove secrets before data crosses an API boundary."""
    return redact_sensitive(entity)
