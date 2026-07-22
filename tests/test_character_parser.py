import json

import pytest

from app.parsers.base import ParseError
from app.parsers.character import CharacterParser


def test_character_parser_preserves_unknown_fields_and_inventory():
    payload = {"BaseCharacter": {"Login": "Player", "Map": "World_0", "PosX": -300245, "PosY": -76290.4, "PosZ": -19252.7, "RotYaw": 148.535, "Health": 81.4228, "ACInventory": {"Item0": {"Index": 1}}, "FutureField": 123}, "Character": {"Food": 50}}
    result = CharacterParser().parse(json.dumps(payload).encode(), "Deadside/Saved/actual1/characters1-9/world_0/1549878660.sav")
    entity = result.entities[0]
    assert entity["player_id"] == "1549878660"
    assert entity["login"] == "Player"
    assert entity["pos_x"] == -300245.0
    assert entity["inventory"]["ACInventory"]["Item0"]["Index"] == 1
    assert entity["raw_data"]["BaseCharacter"]["FutureField"] == 123


def test_character_secondary_fields_may_be_absent():
    entity = CharacterParser().parse(b'{"BaseCharacter":{"Login":"P"}}', "-12.sav").entities[0]
    assert entity["player_id"] == "-12"
    assert entity["health"] is None


def test_incomplete_character_file_is_rejected():
    with pytest.raises(ParseError):
        CharacterParser().parse(b'{"BaseCharacter": {', "42.sav")
