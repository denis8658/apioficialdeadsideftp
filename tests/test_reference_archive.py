import os
import zipfile
from pathlib import Path

import pytest

from app.parsers.character import CharacterParser
from app.parsers.vehicle import VehicleParser


ARCHIVE = Path(os.getenv("DEADSIDE_SAMPLE_ZIP", r"C:\Users\denis\Downloads\Deadside.zip"))


@pytest.mark.skipif(not ARCHIVE.exists(), reason="reference ZIP is not available")
def test_real_reference_character_and_vehicles_parse():
    with zipfile.ZipFile(ARCHIVE) as source:
        character = source.read("Deadside/Saved/actual1/characters1-9/world_0/1549878660.sav")
        vehicles = source.read("Deadside/Saved/actual1/new_vehicles1-9/world_0/new_vehicles.sav")
    parsed_character = CharacterParser().parse(character, "1549878660.sav")
    parsed_vehicles = VehicleParser().parse(vehicles, "new_vehicles.sav")
    assert parsed_character.entities[0]["player_id"] == "1549878660"
    assert len(parsed_vehicles.entities) == 3
    assert all(item["vehicle_uid"] for item in parsed_vehicles.entities)
