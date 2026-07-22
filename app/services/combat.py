from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any, Iterable

from app.db.models import DeathEvent
from app.parsers.deathlog import normalize_player_name


def event_public(event: DeathEvent) -> dict[str, Any]:
    return {
        key: getattr(event, key) for key in (
            "id", "event_time", "event_type", "victim_id", "victim_name", "victim_type", "victim_platform",
            "killer_id", "killer_name", "killer_type", "killer_platform", "weapon_name", "cause",
            "distance_meters", "is_player_kill", "is_suicide", "is_environmental", "world_x", "world_y", "world_z",
            "map_x", "map_y", "grid", "source_file", "source_line", "source_modified_at", "fingerprint", "created_at",
        )
    }


def player_matches(event_id: str | None, event_name: str | None, player: str) -> bool:
    return bool(event_id == player or (not event_id and normalize_player_name(event_name) == normalize_player_name(player)))


def combat_stats(events: Iterable[DeathEvent], player: str) -> dict[str, Any]:
    rows = list(events)
    kills = [row for row in rows if row.is_player_kill and player_matches(row.killer_id, row.killer_name, player)]
    deaths = [row for row in rows if row.is_player_kill and player_matches(row.victim_id, row.victim_name, player)]
    suicides = [row for row in rows if row.is_suicide and player_matches(row.victim_id, row.victim_name, player)]
    npc_kills = [row for row in rows if row.event_type == "npc_kill" and player_matches(row.killer_id, row.killer_name, player)]
    deaths_by_npc = [row for row in rows if row.event_type == "killed_by_npc" and player_matches(row.victim_id, row.victim_name, player)]
    environmental = [row for row in rows if row.is_environmental and player_matches(row.victim_id, row.victim_name, player)]
    distances = [row.distance_meters for row in kills if row.distance_meters is not None]
    weapons = Counter(row.weapon_name for row in kills if row.weapon_name)
    names = [row.killer_name for row in kills if row.killer_name] + [row.victim_name for row in deaths + suicides + environmental if row.victim_name]
    return {
        "player_id": player,
        "player_name": Counter(names).most_common(1)[0][0] if names else None,
        "kills": len(kills), "deaths": len(deaths), "suicides": len(suicides), "npc_kills": len(npc_kills),
        "deaths_by_npc": len(deaths_by_npc), "environmental_deaths": len(environmental),
        "kd_ratio": round(len(kills) / len(deaths), 2) if deaths else None,
        "undefeated": not deaths,
        "longest_kill_meters": max(distances) if distances else None,
        "average_kill_distance_meters": round(mean(distances), 2) if distances else None,
        "favorite_weapon": weapons.most_common(1)[0][0] if weapons else None,
    }


def leaderboard(events: Iterable[DeathEvent], min_kills_for_kd: int, sort: str = "kills") -> list[dict[str, Any]]:
    rows = list(events)
    players: dict[str, dict[str, Any]] = defaultdict(lambda: {"kills": 0, "deaths": 0, "distances": [], "weapons": Counter(), "name": None})
    for row in rows:
        if not row.is_player_kill:
            continue
        killer = row.killer_id or normalize_player_name(row.killer_name)
        victim = row.victim_id or normalize_player_name(row.victim_name)
        if killer:
            data = players[killer]; data["kills"] += 1; data["name"] = row.killer_name or data["name"]
            if row.distance_meters is not None: data["distances"].append(row.distance_meters)
            if row.weapon_name: data["weapons"][row.weapon_name] += 1
        if victim:
            data = players[victim]; data["deaths"] += 1; data["name"] = row.victim_name or data["name"]
    result = []
    for player, data in players.items():
        kd = round(data["kills"] / data["deaths"], 2) if data["deaths"] else None
        result.append({
            "player_id": player, "player_name": data["name"], "kills": data["kills"], "deaths": data["deaths"],
            "kd_ratio": kd, "kd_eligible": data["kills"] >= min_kills_for_kd,
            "longest_kill_meters": max(data["distances"]) if data["distances"] else None,
            "favorite_weapon": data["weapons"].most_common(1)[0][0] if data["weapons"] else None,
        })
    if sort == "kd_ratio":
        result.sort(key=lambda x: (x["kd_eligible"] and x["kd_ratio"] is not None, x["kd_ratio"] if x["kd_ratio"] is not None else -1, x["kills"]), reverse=True)
    else:
        field = {"deaths": "deaths", "longest_kill": "longest_kill_meters"}.get(sort, "kills")
        result.sort(key=lambda x: (x[field] is not None, x[field] or 0), reverse=True)
    return result


def period_start(period: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    if period == "today": return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week": return now - timedelta(days=7)
    if period == "month": return now - timedelta(days=30)
    return None
