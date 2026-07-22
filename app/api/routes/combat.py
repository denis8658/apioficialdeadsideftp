import uuid
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import resolve_server
from app.core.config import get_settings
from app.db.models import DeathEvent
from app.db.session import get_session
from app.parsers.deathlog import normalize_player_name
from app.services.combat import combat_stats, event_public, leaderboard, period_start, player_matches

kills_router = APIRouter(prefix="/servers/{server_id}/kills", tags=["kills"])
players_router = APIRouter(prefix="/servers/{server_id}/players", tags=["combat"])


def _kill_query(server_uuid, *, date_from=None, date_to=None, killer_id=None, killer_name=None, victim_id=None, victim_name=None, weapon=None, grid=None, min_distance=None, max_distance=None):
    query = select(DeathEvent).where(DeathEvent.server_id == server_uuid, DeathEvent.is_player_kill.is_(True))
    if date_from: query = query.where(DeathEvent.event_time >= date_from)
    if date_to: query = query.where(DeathEvent.event_time <= date_to)
    if killer_id: query = query.where(DeathEvent.killer_id == killer_id)
    if killer_name: query = query.where(DeathEvent.killer_name.ilike(f"%{killer_name}%"))
    if victim_id: query = query.where(DeathEvent.victim_id == victim_id)
    if victim_name: query = query.where(DeathEvent.victim_name.ilike(f"%{victim_name}%"))
    if weapon: query = query.where(DeathEvent.weapon_name.ilike(f"%{weapon}%"))
    if grid: query = query.where(DeathEvent.grid == grid)
    if min_distance is not None: query = query.where(DeathEvent.distance_meters >= min_distance)
    if max_distance is not None: query = query.where(DeathEvent.distance_meters <= max_distance)
    return query


@kills_router.get("")
async def kills(server_id: str, date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"), killer_id: str | None = None, killer_name: str | None = None, victim_id: str | None = None, victim_name: str | None = None, weapon: str | None = None, grid: str | None = None, min_distance: float | None = None, max_distance: float | None = None, limit: int = Query(20, ge=1, le=1000), offset: int = Query(0, ge=0), sort: str = Query("event_time", pattern="^(event_time|distance)$"), order: str = Query("desc", pattern="^(asc|desc)$"), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    query = _kill_query(server.id, date_from=date_from, date_to=date_to, killer_id=killer_id, killer_name=killer_name, victim_id=victim_id, victim_name=victim_name, weapon=weapon, grid=grid, min_distance=min_distance, max_distance=max_distance)
    column = DeathEvent.distance_meters if sort == "distance" else DeathEvent.event_time
    query = query.order_by(asc(column) if order == "asc" else desc(column)).offset(offset).limit(limit)
    return [event_public(row) for row in (await session.scalars(query)).all()]


@kills_router.get("/latest")
async def latest(server_id: str, limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    rows = (await session.scalars(_kill_query(server.id).order_by(DeathEvent.event_time.desc()).limit(limit))).all()
    return [event_public(row) for row in rows]


@kills_router.get("/feed")
async def feed(server_id: str, limit: int = Query(20, ge=1, le=100), session: AsyncSession = Depends(get_session)):
    items = await latest(server_id, limit, session)
    for item in items:
        weapon = f" com {item['weapon_name']}" if item["weapon_name"] else ""
        distance = f" a {item['distance_meters']:.1f} m".replace(".", ",") if item["distance_meters"] is not None else ""
        item["message"] = f"{item['killer_name'] or 'Desconhecido'} eliminou {item['victim_name'] or 'Desconhecido'}{weapon}{distance}"
    return items


async def _all_events(session: AsyncSession, server_uuid, start: datetime | None = None) -> list[DeathEvent]:
    query = select(DeathEvent).where(DeathEvent.server_id == server_uuid)
    if start: query = query.where(DeathEvent.event_time >= start)
    return list((await session.scalars(query)).all())


@kills_router.get("/statistics")
async def statistics(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = await _all_events(session, server.id)
    types = Counter(row.event_type for row in rows)
    distances = [row.distance_meters for row in rows if row.is_player_kill and row.distance_meters is not None]
    return {"events": len(rows), "by_event_type": types, "player_kills": types["player_kill"], "average_kill_distance_meters": round(mean(distances), 2) if distances else None, "longest_kill_meters": max(distances) if distances else None}


@kills_router.get("/leaderboard")
async def kills_leaderboard(server_id: str, period: str = Query("all", pattern="^(today|week|month|all)$"), sort: str = Query("kills", pattern="^(kills|deaths|kd_ratio|longest_kill)$"), limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = await _all_events(session, server.id, period_start(period))
    items = leaderboard(rows, get_settings().kills_leaderboard_min_kills_for_kd, sort)
    return {"period": period, "sort": sort, "items": items[offset:offset + limit]}


@kills_router.get("/weapons")
async def weapons(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [row for row in await _all_events(session, server.id) if row.is_player_kill]
    grouped: dict[str, list[DeathEvent]] = defaultdict(list)
    for row in rows:
        if row.weapon_name: grouped[row.weapon_name].append(row)
    items = []
    for weapon, events in grouped.items():
        distances = [row.distance_meters for row in events if row.distance_meters is not None]
        items.append({"weapon": weapon, "kills": len(events), "percentage": round(len(events) * 100 / len(rows), 2) if rows else 0, "average_distance_meters": round(mean(distances), 2) if distances else None, "longest_distance_meters": max(distances) if distances else None})
    return {"items": sorted(items, key=lambda item: item["kills"], reverse=True)}


@kills_router.get("/timeline")
async def timeline(server_id: str, interval: str = Query("day", pattern="^(hour|day|week)$"), date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"), session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = (await session.scalars(_kill_query(server.id, date_from=date_from, date_to=date_to))).all(); buckets = Counter()
    for row in rows:
        dt = row.event_time
        key = dt.strftime("%Y-%m-%dT%H:00:00Z") if interval == "hour" else (f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}" if interval == "week" else dt.strftime("%Y-%m-%d"))
        buckets[key] += 1
    return {"interval": interval, "items": [{"bucket": key, "kills": buckets[key]} for key in sorted(buckets)]}


@kills_router.get("/head-to-head")
async def head_to_head(server_id: str, player_a: str, player_b: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [row for row in await _all_events(session, server.id) if row.is_player_kill]
    ab = sum(player_matches(r.killer_id, r.killer_name, player_a) and player_matches(r.victim_id, r.victim_name, player_b) for r in rows)
    ba = sum(player_matches(r.killer_id, r.killer_name, player_b) and player_matches(r.victim_id, r.victim_name, player_a) for r in rows)
    return {"player_a": {"id": player_a, "kills_against_player_b": ab}, "player_b": {"id": player_b, "kills_against_player_a": ba}}


@kills_router.get("/geojson")
async def geojson(server_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = (await session.scalars(_kill_query(server.id).where(DeathEvent.map_x.is_not(None), DeathEvent.map_y.is_not(None)))).all()
    if not rows: return {"available": False, "reason": "Deathlog sem coordenadas de morte."}
    return {"available": True, "type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.map_x, r.map_y]}, "properties": {"kill_id": str(r.id), "killer": r.killer_name, "victim": r.victim_name, "weapon": r.weapon_name, "distance_meters": r.distance_meters, "event_time": r.event_time}} for r in rows]}


@kills_router.get("/heatmap")
async def heatmap(server_id: str, session: AsyncSession = Depends(get_session)):
    data = await geojson(server_id, session)
    if not data.get("available"): return data
    return {"available": True, "points": [{"map_x": f["geometry"]["coordinates"][0], "map_y": f["geometry"]["coordinates"][1], "weight": 1} for f in data["features"]]}


@kills_router.get("/{kill_id}")
async def kill(server_id: str, kill_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); row = await session.scalar(select(DeathEvent).where(DeathEvent.server_id == server.id, DeathEvent.id == kill_id, DeathEvent.is_player_kill.is_(True)))
    if row is None: raise HTTPException(404, "kill not found")
    return event_public(row)


@players_router.get("/{player_id}/kills")
async def player_kills(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [r for r in await _all_events(session, server.id) if r.is_player_kill and player_matches(r.killer_id, r.killer_name, player_id)]
    return [event_public(row) for row in sorted(rows, key=lambda x: x.event_time, reverse=True)]


@players_router.get("/{player_id}/deaths")
async def player_deaths(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [r for r in await _all_events(session, server.id) if player_matches(r.victim_id, r.victim_name, player_id)]
    return [event_public(row) for row in sorted(rows, key=lambda x: x.event_time, reverse=True)]


@players_router.get("/{player_id}/combat-stats")
async def player_combat_stats(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id)
    return combat_stats(await _all_events(session, server.id), player_id)


@players_router.get("/{player_id}/rivals")
async def rivals(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [r for r in await _all_events(session, server.id) if r.is_player_kill]; scores = Counter()
    for row in rows:
        if player_matches(row.killer_id, row.killer_name, player_id): scores[row.victim_id or row.victim_name] += 1
        if player_matches(row.victim_id, row.victim_name, player_id): scores[row.killer_id or row.killer_name] += 1
    return {"items": [{"player": key, "encounters": count} for key, count in scores.most_common()]}


@players_router.get("/{player_id}/victims")
async def victims(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [r for r in await _all_events(session, server.id) if r.is_player_kill and player_matches(r.killer_id, r.killer_name, player_id)]; counts = Counter(r.victim_id or r.victim_name for r in rows)
    return {"items": [{"player": key, "kills": count} for key, count in counts.most_common()]}


@players_router.get("/{player_id}/killers")
async def killers(server_id: str, player_id: str, session: AsyncSession = Depends(get_session)):
    server = await resolve_server(session, server_id); rows = [r for r in await _all_events(session, server.id) if r.is_player_kill and player_matches(r.victim_id, r.victim_name, player_id)]; counts = Counter(r.killer_id or r.killer_name for r in rows)
    return {"items": [{"player": key, "deaths": count} for key, count in counts.most_common()]}
