from datetime import UTC

import pytest

from app.parsers.base import ParseError
from app.parsers.deathlog import (
    DeathlogParser,
    classify_death_event,
    classify_killer_type,
    classify_victim_type,
    combat_fingerprint,
    normalize_player_name,
)

PLAYER_A = "a" * 32
PLAYER_B = "b" * 32


def row(killer="Player A", killer_id=PLAYER_A, victim="Player B", victim_id=PLAYER_B, weapon="AR4", distance="120.5", delimiter=";"):
    return delimiter.join(["2026.07.21-22.15.30", killer, killer_id, victim, victim_id, weapon, distance, "PC", "PC", ""])


def parse(line: str):
    return DeathlogParser().parse(line.encode(), "deathlogs/world_0/day.csv").entities[0]


def test_player_killed_player():
    event = parse(row())
    assert event["event_type"] == "player_kill"
    assert event["is_player_kill"] is True
    assert event["weapon_name"] == "AR4"
    assert event["distance_meters"] == 120.5


def test_npc_killed_player():
    event = parse(row("Bandit NPC", "", victim_id=PLAYER_B))
    assert event["event_type"] == "killed_by_npc"
    assert event["is_player_kill"] is False


def test_player_killed_npc():
    event = parse(row(victim="Bandit NPC", victim_id=""))
    assert event["event_type"] == "npc_kill"


def test_suicide_by_same_identity():
    event = parse(row(victim="Player A", victim_id=PLAYER_A, weapon="Dynamite", distance="0"))
    assert event["event_type"] == "suicide"
    assert event["is_suicide"] is True


def test_environmental_falling_overrides_duplicated_killer():
    event = parse(row(victim="Player A", victim_id=PLAYER_A, weapon="falling", distance="0"))
    assert event["event_type"] == "environmental_death"
    assert event["cause"] == "falling"
    assert event["is_environmental"] is True


def test_unknown_killer_and_unknown_victim():
    assert classify_killer_type(None, None) == "unknown"
    assert classify_victim_type(None, None) == "unknown"
    assert classify_death_event("unknown", "unknown") == "unknown_death"


def test_fingerprint_ignores_source_file_and_line():
    first = parse(row())
    second = dict(first, source_file="rotated.csv", source_line=900)
    assert combat_fingerprint(first) == combat_fingerprint(second) == first["fingerprint"]


def test_source_line_is_physical_csv_line():
    result = DeathlogParser().parse(("\n" + row()).encode(), "day.csv")
    assert result.entities[0]["source_line"] == 2


def test_csv_with_header_and_comma_delimiter():
    header = "Date,Killer,Killer ID,Victim,Victim ID,Weapon,Distance,Killer Platform,Victim Platform,Extra\n"
    event = DeathlogParser().parse((header + row(delimiter=",")).encode(), "day.csv").entities[0]
    assert event["killer_id"] == PLAYER_A
    assert event["victim_id"] == PLAYER_B


def test_cp1252_encoding_is_supported():
    event = DeathlogParser().parse(row(killer="João").encode("cp1252"), "day.csv").entities[0]
    assert event["killer_name"] == "João"


def test_missing_distance_is_null():
    assert parse(row(distance=""))["distance_meters"] is None


def test_coordinates_are_never_invented():
    event = parse(row())
    assert event["world_x"] is event["map_x"] is None


def test_partial_last_line_is_ignored_when_prior_event_is_complete():
    result = DeathlogParser().parse((row() + "\n2026.07.21").encode(), "day.csv")
    assert len(result.entities) == 1
    assert any("line 2 ignored" in warning for warning in result.warnings)


def test_only_partial_content_is_rejected():
    with pytest.raises(ParseError):
        DeathlogParser().parse(b"2026.07.21;partial", "day.csv")


def test_name_normalization_preserves_original_parser_value():
    event = parse(row(killer="  Jõão   Silva  "))
    assert event["killer_name"] == "Jõão   Silva"
    assert normalize_player_name(event["killer_name"]) == "jõão silva"
    assert event["event_time"].tzinfo == UTC
