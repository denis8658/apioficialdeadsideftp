import json

import pytest

from app.parsers.base import ParseError
from app.parsers.json_helpers import normalize_numbered_objects, redact_sensitive
from app.parsers.permanent_character import PermanentCharacterParser
from app.parsers.storage import StorageParser


def test_storage_parser_uses_filename_metadata_and_normalizes_items():
    payload = {"Inventory": {"Item3": {"Index": 7, "Count": 2}, "Item0": {"Index": 4, "Count": 1}}}
    path = "Deadside/Saved/actual1/storages1-9/world_0/-20_itemstorage_world_0_X08_Y07_ItemStorage01_2.sav"
    entity = StorageParser().parse(json.dumps(payload).encode(), path).entities[0]
    assert entity["storage_id"].startswith("-20_itemstorage")
    assert entity["player_id"] == "-20"
    assert entity["world"] == "world_0"
    assert entity["grid"] == "X08_Y07"
    assert entity["storage_type"] == "ItemStorage01_2"
    assert [item["slot"] for item in entity["items"]] == [0, 3]
    assert entity["item_count"] == 2


def test_empty_storage_inventory_is_valid():
    entity = StorageParser().parse(b'{"Inventory":{}}', "unrecognized.sav").entities[0]
    assert entity["items"] == []
    assert entity["item_count"] == 0


def test_storage_requires_inventory_object():
    with pytest.raises(ParseError):
        StorageParser().parse(b'{"Inventory":[]}', "storage.sav")


def test_permanent_character_normalizes_achievements():
    payload = {
        "BaseCharacter": {"Login": "Player"},
        "Character": {"Achievements": {"Count": 2, "Type1": "Second", "Value1": 8, "BitsValue1": 4, "Type0": "First", "Value0": 3}},
    }
    entity = PermanentCharacterParser().parse(json.dumps(payload).encode(), "-374951184.sav").entities[0]
    assert entity["player_id"] == "-374951184"
    assert entity["login"] == "Player"
    assert [row["type"] for row in entity["achievements"]] == ["First", "Second"]
    assert entity["achievement_count"] == 2


def test_permanent_character_requires_known_objects():
    with pytest.raises(ParseError):
        PermanentCharacterParser().parse(b'{"BaseCharacter":{}}', "1.sav")


def test_sensitive_json_keys_are_removed_recursively():
    value = {"ok": 1, "nested": {"LockPassword": "x", "ApiKey": "y", "items": [{"token": "z", "value": 2}]}}
    assert redact_sensitive(value) == {"ok": 1, "nested": {"items": [{"value": 2}]}}


def test_numbered_objects_ignore_unknown_values():
    assert normalize_numbered_objects({"Item2": {"Index": 1}, "Count": 4, "ItemX": {}}, "Item") == [{"slot": 2, "Index": 1}]
