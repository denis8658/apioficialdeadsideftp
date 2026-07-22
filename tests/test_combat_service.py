from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.combat import combat_stats, leaderboard


def event(killer="a", victim="b", event_type="player_kill", distance=100.0, weapon="AR4"):
    return SimpleNamespace(
        killer_id=killer, killer_name=killer, victim_id=victim, victim_name=victim,
        event_type=event_type, is_player_kill=event_type == "player_kill",
        is_suicide=event_type == "suicide", is_environmental=event_type == "environmental_death",
        distance_meters=distance, weapon_name=weapon, event_time=datetime.now(UTC),
    )


def test_kd_uses_only_player_kills_and_player_deaths():
    rows = [event("a", "b"), event("a", "c", distance=200), event("c", "a"), event("a", "a", "suicide"), event("environment", "a", "environmental_death")]
    stats = combat_stats(rows, "a")
    assert stats["kills"] == 2
    assert stats["deaths"] == 1
    assert stats["kd_ratio"] == 2.0
    assert stats["suicides"] == 1
    assert stats["environmental_deaths"] == 1
    assert stats["average_kill_distance_meters"] == 150


def test_kd_with_zero_deaths_is_null_and_undefeated():
    stats = combat_stats([event("a", "b")], "a")
    assert stats["kd_ratio"] is None
    assert stats["undefeated"] is True


def test_leaderboard_orders_kills_and_protects_small_kd_samples():
    rows = [event("a", "b"), event("a", "c"), event("a", "d"), event("b", "a")]
    by_kills = leaderboard(rows, min_kills_for_kd=3, sort="kills")
    assert by_kills[0]["player_id"] == "a"
    assert by_kills[0]["kills"] == 3
    assert by_kills[0]["kd_eligible"] is True
    assert next(row for row in by_kills if row["player_id"] == "b")["kd_eligible"] is False
