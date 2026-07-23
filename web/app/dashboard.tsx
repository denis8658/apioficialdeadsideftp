"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Dict = Record<string, any>;
type Section = "overview" | "map" | "characters" | "vehicles" | "storages" | "combat" | "events" | "api";

const SERVER = "deadside-01";
const API_ROOT = `/api/v1/servers/${SERVER}`;
const WS_ROOT = "wss://apioficialdeadsideftp-production.up.railway.app/api/v1/servers/deadside-01/ws";

const nav: { id: Section; label: string; glyph: string }[] = [
  { id: "overview", label: "Visão geral", glyph: "◫" },
  { id: "map", label: "Mapa tático", glyph: "⌖" },
  { id: "characters", label: "Personagens", glyph: "◎" },
  { id: "vehicles", label: "Veículos", glyph: "◆" },
  { id: "storages", label: "Storages", glyph: "▣" },
  { id: "combat", label: "Combate", glyph: "✦" },
  { id: "events", label: "Eventos ao vivo", glyph: "⌁" },
  { id: "api", label: "API Explorer", glyph: "⌘" },
];

const endpointCatalog = [
  ["Saúde", "GET", "/health"], ["Servidor", "GET", `${API_ROOT}`], ["FTP", "GET", `${API_ROOT}/ftp/status`],
  ["Personagens", "GET", `${API_ROOT}/characters`], ["Personagem permanente", "GET", `${API_ROOT}/characters/{player_id}/permanent`],
  ["Veículos", "GET", `${API_ROOT}/vehicles`], ["Storages", "GET", `${API_ROOT}/storages`], ["Kills", "GET", `${API_ROOT}/kills`],
  ["Últimas kills", "GET", `${API_ROOT}/kills/latest`], ["Feed", "GET", `${API_ROOT}/kills/feed`], ["Estatísticas", "GET", `${API_ROOT}/kills/statistics`],
  ["Leaderboard", "GET", `${API_ROOT}/kills/leaderboard`], ["Armas", "GET", `${API_ROOT}/kills/weapons`], ["Timeline", "GET", `${API_ROOT}/kills/timeline`],
  ["GeoJSON", "GET", `${API_ROOT}/kills/geojson`], ["Heatmap", "GET", `${API_ROOT}/kills/heatmap`], ["Mapa config", "GET", `${API_ROOT}/map/config`],
  ["Entidades do mapa", "GET", `${API_ROOT}/map/entities`], ["Jogadores ao vivo", "GET", `${API_ROOT}/map/live-players`], ["WebSocket status", "GET", `${API_ROOT}/ws/status`], ["Eventos", "GET", `${API_ROOT}/events`],
  ["Testar FTP", "POST", `${API_ROOT}/ftp/test`], ["Descobrir FTP", "POST", `${API_ROOT}/ftp/discover`],
  ["Sincronizar", "POST", `${API_ROOT}/sync/run`], ["Iniciar polling", "POST", `${API_ROOT}/sync/start`], ["Parar polling", "POST", `${API_ROOT}/sync/stop`],
];

const fmtDate = (value?: string) => value ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)) : "—";
const fmtNumber = (value?: number | null, suffix = "") => value == null ? "—" : `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(value)}${suffix}`;
const shorten = (value?: string, size = 14) => !value ? "—" : value.length > size ? `${value.slice(0, size)}…` : value;

async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/proxy?path=${encodeURIComponent(path)}`, init);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload?.detail || payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

function Badge({ tone = "neutral", children }: { tone?: "good" | "warn" | "bad" | "neutral" | "blue"; children: React.ReactNode }) {
  return <span className={`badge badge-${tone}`}><i />{children}</span>;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="empty"><span>◇</span><strong>{title}</strong><p>{detail}</p></div>;
}

function SparkBars({ values, color = "green" }: { values: number[]; color?: "green" | "orange" }) {
  const max = Math.max(...values, 1);
  return <div className={`spark spark-${color}`}>{values.map((v, i) => <i key={i} style={{ height: `${Math.max(8, v / max * 100)}%` }} />)}</div>;
}

export function Dashboard() {
  const [section, setSection] = useState<Section>("overview");
  const [mobileNav, setMobileNav] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [characters, setCharacters] = useState<Dict[]>([]);
  const [vehicles, setVehicles] = useState<Dict[]>([]);
  const [storages, setStorages] = useState<Dict[]>([]);
  const [kills, setKills] = useState<Dict[]>([]);
  const [events, setEvents] = useState<Dict[]>([]);
  const [leaderboard, setLeaderboard] = useState<Dict[]>([]);
  const [weapons, setWeapons] = useState<Dict[]>([]);
  const [timeline, setTimeline] = useState<Dict[]>([]);
  const [stats, setStats] = useState<Dict>({});
  const [sync, setSync] = useState<Dict>({});
  const [wsStatus, setWsStatus] = useState<Dict>({});
  const [liveMap, setLiveMap] = useState<Dict>({ players: [], count: 0, position_poll_interval_seconds: 0.5 });
  const [mapZoom, setMapZoom] = useState(1);
  const [selectedMarker, setSelectedMarker] = useState<Dict | null>(null);
  const [wsToken, setWsToken] = useState("");
  const [wsState, setWsState] = useState<"fallback" | "connecting" | "live" | "error">("fallback");
  const [liveEvents, setLiveEvents] = useState<Dict[]>([]);
  const [action, setAction] = useState("");
  const [actionResult, setActionResult] = useState<Dict | null>(null);
  const [explorerPath, setExplorerPath] = useState(`${API_ROOT}/characters?limit=5`);
  const [explorerResult, setExplorerResult] = useState("");
  const sockets = useRef<WebSocket[]>([]);

  const load = useCallback(async (quiet = false) => {
    quiet ? setRefreshing(true) : setLoading(true);
    setError("");
    try {
      const [chars, vehs, stores, killRows, statRows, leaders, weaponRows, timelineRows, syncRows, eventRows, mapRows, socketRows] = await Promise.all([
        api<Dict[]>(`${API_ROOT}/characters?limit=1000`), api<Dict[]>(`${API_ROOT}/vehicles?limit=1000`), api<Dict[]>(`${API_ROOT}/storages?limit=1000`),
        api<Dict[]>(`${API_ROOT}/kills?limit=1000`), api<Dict>(`${API_ROOT}/kills/statistics`), api<Dict>(`${API_ROOT}/kills/leaderboard?limit=100`),
        api<Dict>(`${API_ROOT}/kills/weapons`), api<Dict>(`${API_ROOT}/kills/timeline?interval=day`), api<Dict>(`${API_ROOT}/sync/status`),
        api<Dict[]>(`${API_ROOT}/events?limit=100`), api<Dict>(`${API_ROOT}/map/live-players`), api<Dict>(`${API_ROOT}/ws/status`),
      ]);
      setCharacters(chars); setVehicles(vehs); setStorages(stores); setKills(killRows); setStats(statRows);
      setLeaderboard(leaders.items || []); setWeapons(weaponRows.items || []); setTimeline(timelineRows.items || []);
      setSync(syncRows); setEvents(eventRows.slice().reverse()); setLiveMap(mapRows); setWsStatus(socketRows);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível carregar os dados.");
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); const timer = setInterval(() => load(true), 30000); return () => clearInterval(timer); }, [load]);
  useEffect(() => {
    const refreshLivePlayers = async () => {
      try { setLiveMap(await api<Dict>(`${API_ROOT}/map/live-players`)); } catch { /* atualização geral exibirá o erro */ }
    };
    refreshLivePlayers();
    const timer = setInterval(refreshLivePlayers, 500);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { const saved = localStorage.getItem("deadside-ws-token"); if (saved) setWsToken(saved); }, []);
  useEffect(() => () => sockets.current.forEach((socket) => socket.close()), []);

  const connectSockets = () => {
    sockets.current.forEach((socket) => socket.close()); sockets.current = [];
    if (!wsToken.trim()) { setWsState("fallback"); return; }
    localStorage.setItem("deadside-ws-token", wsToken.trim()); setWsState("connecting");
    let opened = 0;
    ["kills", "map", "sync", "events"].forEach((channel) => {
      const socket = new WebSocket(`${WS_ROOT}/${channel}?token=${encodeURIComponent(wsToken.trim())}`);
      socket.onopen = () => { opened += 1; if (opened > 0) setWsState("live"); };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data);
          if (event.event === "system.ping") socket.send(JSON.stringify({ event: "system.pong" }));
          else { setLiveEvents((current) => [{ ...event, channel }, ...current].slice(0, 100)); if (!event.event?.startsWith("system.")) load(true); }
        } catch { /* mensagem inválida ignorada */ }
      };
      socket.onerror = () => setWsState("error"); socket.onclose = () => { if (!sockets.current.some((item) => item.readyState === 1)) setWsState("fallback"); };
      sockets.current.push(socket);
    });
  };

  const runAction = async (name: string, suffix: string) => {
    setAction(name); setActionResult(null);
    try { const result = await api<Dict>(`${API_ROOT}/${suffix}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); setActionResult(result); await load(true); }
    catch (err) { setActionResult({ error: err instanceof Error ? err.message : "Falha na operação" }); }
    finally { setAction(""); }
  };

  const visibleCharacters = useMemo(() => characters.filter((item) => `${item.login} ${item.player_id} ${item.map_position?.grid}`.toLowerCase().includes(search.toLowerCase())), [characters, search]);
  const visibleVehicles = useMemo(() => vehicles.filter((item) => `${item.display_name} ${item.vehicle_uid} ${item.map_position?.grid}`.toLowerCase().includes(search.toLowerCase())), [vehicles, search]);
  const visibleStorages = useMemo(() => storages.filter((item) => `${item.player_id} ${item.storage_type} ${item.grid}`.toLowerCase().includes(search.toLowerCase())), [storages, search]);

  const renderOverview = () => <>
    <div className="hero-grid">
      <article className="hero-card">
        <div><span className="eyebrow">SERVIDOR OPERACIONAL</span><h2>Mirny está sendo monitorado</h2><p>Dados do FTP processados e distribuídos em tempo real pela Deadside Data API.</p></div>
        <div className="server-pulse"><i /><strong>{sync.connected ? "FTP conectado" : "FTP desconectado"}</strong><small>Último sucesso {fmtDate(sync.last_success_at)}</small></div>
      </article>
      <article className="mini-map-card" onClick={() => setSection("map")}>
        <img src={`/api/proxy?path=${encodeURIComponent("/api/v1/maps/mirny/image")}`} alt="Mapa Mirny" />
        <div><span>JOGADORES AO VIVO</span><strong>{liveMap.count || 0} sinais ativos agora</strong></div>
      </article>
    </div>
    <div className="metric-grid">
      <Metric label="Personagens" value={characters.length} detail={`${characters.filter(c => c.position_freshness === "fresh").length} posições recentes`} glyph="◎" />
      <Metric label="Veículos" value={vehicles.length} detail={`${vehicles.filter(v => v.active !== false).length} ativos`} glyph="◆" />
      <Metric label="Storages" value={storages.length} detail={`${storages.reduce((n, s) => n + (s.item_count || 0), 0)} itens registrados`} glyph="▣" />
      <Metric label="Kills PvP" value={stats.player_kills ?? kills.length} detail={`Maior distância ${fmtNumber(stats.longest_kill_meters, " m")}`} glyph="✦" />
    </div>
    <div className="overview-grid">
      <article className="panel span-2">
        <PanelHead title="Atividade recente" subtitle="Eventos confirmados no banco" action={<button className="text-btn" onClick={() => setSection("events")}>Ver todos →</button>} />
        <div className="activity-list">{events.slice(0, 7).map((event, index) => <EventRow key={event.sequence || index} event={event} />)}{!events.length && <Empty title="Sem eventos" detail="A próxima sincronização aparecerá aqui." />}</div>
      </article>
      <article className="panel">
        <PanelHead title="Sincronização" subtitle="Estado do coletor FTP" />
        <div className="sync-ring"><div><strong>{sync.files_processed || 0}</strong><span>processados</span></div></div>
        <dl className="facts"><div><dt>Verificados</dt><dd>{sync.files_scanned || 0}</dd></div><div><dt>Falhas</dt><dd className={sync.files_failed ? "danger" : "success"}>{sync.files_failed || 0}</dd></div><div><dt>Ciclo</dt><dd>{fmtNumber((sync.current_cycle_duration_ms || 0) / 1000, " s")}</dd></div></dl>
        <button className="primary wide" disabled={!!action} onClick={() => runAction("sync", "sync/run")}>{action === "sync" ? "Sincronizando…" : "Executar sincronização"}</button>
      </article>
      <article className="panel">
        <PanelHead title="Kill feed" subtitle="Últimos confrontos" />
        <div className="kill-feed">{kills.slice(0, 5).map(kill => <div key={kill.id}><span className="kill-dot">✦</span><p><b>{kill.killer_name || "Desconhecido"}</b> eliminou <b>{kill.victim_name || "Desconhecido"}</b><small>{kill.weapon_name || "arma desconhecida"} · {fmtNumber(kill.distance_meters, " m")}</small></p></div>)}{!kills.length && <Empty title="Sem kills PvP" detail="O deathlog ainda não possui confrontos." />}</div>
      </article>
      <article className="panel span-2">
        <PanelHead title="Tendência de combate" subtitle="Kills agrupadas por dia" />
        <div className="trend"><SparkBars values={timeline.map(x => x.kills)} /><div className="trend-labels"><span>{timeline[0]?.bucket || "Início"}</span><span>{timeline.at(-1)?.bucket || "Agora"}</span></div></div>
      </article>
    </div>
  </>;

  const renderMap = () => {
    const markerRows = (liveMap.players || []).map((item: Dict) => ({ ...item, kind: "character" })).filter((item: Dict) => item.map_position?.inside_map);
    return <div className="map-layout">
      <article className="panel map-panel">
        <PanelHead title="Jogadores ao vivo em Mirny" subtitle="Sessões confirmadas pelos eventos Join/Logout do log do servidor" action={<Badge tone="good">atualiza a cada 0,5 s</Badge>} />
        <div className="map-viewport">
          <div className="map-canvas" style={{ transform: `scale(${mapZoom})` }}>
            <img src={`/api/proxy?path=${encodeURIComponent("/api/v1/maps/mirny/image")}`} alt="Mapa completo de Mirny" />
            {markerRows.map((item: Dict) => <button key={`${item.kind}-${item.id}`} className={`marker marker-${item.kind}`} style={{ left: `${item.map_position.x / 1280 * 100}%`, top: `${Math.abs(item.map_position.y) / 1408 * 100}%` }} title={`${item.kind === "character" ? "Personagem" : "Veículo"} ${item.id}`} onClick={() => setSelectedMarker(item)}><span>{item.kind === "character" ? "●" : "◆"}</span></button>)}
          </div>
          <div className="zoom"><button onClick={() => setMapZoom(z => Math.min(2, z + .2))}>+</button><button onClick={() => setMapZoom(z => Math.max(.7, z - .2))}>−</button><button onClick={() => setMapZoom(1)}>1:1</button></div>
          <div className="map-legend"><span><i className="legend-player" />Jogador ao vivo</span><b>{markerRows.length} online</b></div>
        </div>
      </article>
      <aside className="panel inspector">
        <PanelHead title="Inspetor" subtitle="Selecione um marcador" />
        {selectedMarker ? <><div className="entity-emblem">◎</div><h3>{selectedMarker.login || "Jogador"}</h3><code>{selectedMarker.player_id}</code><dl className="facts stacked"><div><dt>Grid</dt><dd>{selectedMarker.map_position?.grid || "—"}</dd></div><div><dt>Saúde</dt><dd>{fmtNumber(selectedMarker.health, "%")}</dd></div><div><dt>Atualizado há</dt><dd>{fmtNumber(selectedMarker.source_age_seconds, " s")}</dd></div><div><dt>Mapa X</dt><dd>{fmtNumber(selectedMarker.map_position?.x)}</dd></div><div><dt>Mapa Y</dt><dd>{fmtNumber(selectedMarker.map_position?.y)}</dd></div></dl></> : <Empty title="Nenhum jogador selecionado" detail="Clique em um marcador ao vivo para ver nome, saúde e posição." />}
      </aside>
    </div>;
  };

  const renderCharacters = () => <article className="panel table-panel"><PanelHead title="Personagens" subtitle={`${visibleCharacters.length} registros importados`} action={<Search value={search} onChange={setSearch} placeholder="Buscar nome, ID ou grid" />} /><div className="table-wrap"><table><thead><tr><th>Jogador</th><th>Saúde</th><th>Grid</th><th>Posição</th><th>Atualização</th><th>Estado</th></tr></thead><tbody>{visibleCharacters.map(row => <tr key={row.player_id}><td><div className="identity"><i>{(row.login || "?")[0]}</i><span><b>{row.login || "Sem nome"}</b><small>{shorten(row.player_id, 18)}</small></span></div></td><td><div className="health"><span style={{ width: `${Math.min(100, row.health || 0)}%` }} /></div><small>{fmtNumber(row.health, "%")}</small></td><td><strong className="grid-tag">{row.map_position?.grid || "—"}</strong></td><td><small>X {fmtNumber(row.pos_x)}<br />Y {fmtNumber(row.pos_y)}</small></td><td>{fmtDate(row.observed_at)}</td><td><Badge tone={row.position_freshness === "fresh" ? "good" : row.position_freshness === "delayed" ? "warn" : "neutral"}>{row.position_freshness || "sem posição"}</Badge></td></tr>)}</tbody></table>{!visibleCharacters.length && <Empty title="Nenhum personagem" detail="Ajuste a busca ou execute uma sincronização." />}</div></article>;

  const renderVehicles = () => <div><div className="section-tools"><Search value={search} onChange={setSearch} placeholder="Buscar veículo, UID ou grid" /><span>{visibleVehicles.length} veículos</span></div><div className="card-grid">{visibleVehicles.map(row => <article className="entity-card" key={row.vehicle_uid}><div className="entity-top"><span className="vehicle-icon">◆</span><Badge tone={row.active === false ? "neutral" : "good"}>{row.active === false ? "inativo" : "ativo"}</Badge></div><h3>{row.display_name || row.actor_id || "Veículo"}</h3><code>{shorten(row.vehicle_uid, 26)}</code><div className="gauges"><Gauge label="Combustível" value={row.fuel} /><Gauge label="Durabilidade" value={row.durability} /></div><dl className="facts"><div><dt>Grid</dt><dd>{row.map_position?.grid || "—"}</dd></div><div><dt>Inventário</dt><dd>{Array.isArray(row.inventory) ? row.inventory.length : Object.keys(row.inventory || {}).length}</dd></div></dl></article>)}{!visibleVehicles.length && <Empty title="Nenhum veículo" detail="Não há veículos correspondentes ao filtro." />}</div></div>;

  const renderStorages = () => <article className="panel table-panel"><PanelHead title="Storages" subtitle={`${visibleStorages.length} estruturas monitoradas`} action={<Search value={search} onChange={setSearch} placeholder="Buscar proprietário, tipo ou grid" />} /><div className="table-wrap"><table><thead><tr><th>Storage</th><th>Proprietário</th><th>Grid</th><th>Itens</th><th>Última leitura</th></tr></thead><tbody>{visibleStorages.map(row => <tr key={row.storage_id}><td><div className="identity"><i>▣</i><span><b>{row.storage_type || "Storage"}</b><small>{shorten(row.storage_id, 30)}</small></span></div></td><td><code>{shorten(row.player_id, 18)}</code></td><td><strong className="grid-tag">{row.grid || "—"}</strong></td><td><b>{row.item_count || 0}</b></td><td>{fmtDate(row.observed_at)}</td></tr>)}</tbody></table></div></article>;

  const renderCombat = () => <div className="combat-layout">
    <div className="metric-grid combat-metrics"><Metric label="Eventos" value={stats.events || 0} detail="Todos os tipos" glyph="⌁" /><Metric label="Kills PvP" value={stats.player_kills || 0} detail="Jogador contra jogador" glyph="✦" /><Metric label="Distância média" value={fmtNumber(stats.average_kill_distance_meters, " m")} detail="Kills com distância" glyph="↗" /><Metric label="Maior kill" value={fmtNumber(stats.longest_kill_meters, " m")} detail="Recorde atual" glyph="⌖" /></div>
    <div className="overview-grid"><article className="panel span-2"><PanelHead title="Leaderboard" subtitle="Ranking geral por kills" /><div className="leaderboard">{leaderboard.slice(0, 10).map((row, i) => <div key={row.player_id || row.player_name || i}><b className={`rank rank-${i + 1}`}>{String(i + 1).padStart(2, "0")}</b><span><strong>{row.player_name || row.name || shorten(row.player_id)}</strong><small>{row.deaths || 0} mortes · K/D {fmtNumber(row.kd_ratio)}</small></span><em>{row.kills || 0}<small> kills</small></em></div>)}{!leaderboard.length && <Empty title="Ranking vazio" detail="Mais deathlogs são necessários para formar o ranking." />}</div></article><article className="panel"><PanelHead title="Armas" subtitle="Distribuição de eliminações" /><div className="weapon-list">{weapons.map(row => <div key={row.weapon}><span><b>{row.weapon}</b><small>{fmtNumber(row.average_distance_meters, " m")} média</small></span><div><i style={{ width: `${row.percentage}%` }} /></div><strong>{row.kills}</strong></div>)}{!weapons.length && <Empty title="Sem armas" detail="Nenhuma kill com arma identificada." />}</div></article></div>
    <article className="panel table-panel"><PanelHead title="Histórico de confrontos" subtitle={`${kills.length} kills carregadas`} /><div className="table-wrap"><table><thead><tr><th>Data</th><th>Killer</th><th>Vítima</th><th>Arma</th><th>Distância</th><th>Plataformas</th></tr></thead><tbody>{kills.map(row => <tr key={row.id}><td>{fmtDate(row.event_time)}</td><td><b>{row.killer_name || "—"}</b></td><td>{row.victim_name || "—"}</td><td>{row.weapon_name || "—"}</td><td>{fmtNumber(row.distance_meters, " m")}</td><td><small>{row.killer_platform || "?"} → {row.victim_platform || "?"}</small></td></tr>)}</tbody></table></div></article>
  </div>;

  const renderEvents = () => <div className="events-layout"><article className="panel"><PanelHead title="Fluxo de eventos" subtitle={`${liveEvents.length ? "WebSocket + REST" : "Eventos persistidos via REST"}`} action={<Badge tone={wsState === "live" ? "good" : wsState === "error" ? "bad" : "warn"}>{wsState === "live" ? "ao vivo" : "fallback REST"}</Badge>} /><div className="event-stream">{[...liveEvents, ...events].slice(0, 100).map((event, index) => <EventRow key={`${event.sequence || "live"}-${index}`} event={event} detailed />)}{!events.length && !liveEvents.length && <Empty title="Nenhum evento" detail="O stream ainda não publicou mensagens." />}</div></article><aside className="panel ws-config"><PanelHead title="WebSocket" subtitle="Conexão autenticada opcional" /><div className="socket-orbit"><i /><i /><i /><strong>{wsStatus.latest_sequence || 0}</strong><span>última sequência</span></div><label>JWT de acesso<input type="password" value={wsToken} onChange={e => setWsToken(e.target.value)} placeholder="Cole um token HS256 válido" /></label><button className="primary wide" onClick={connectSockets}>{wsState === "connecting" ? "Conectando…" : "Conectar canais"}</button><p className="hint">Sem token, o painel mantém todos os eventos visíveis pelo histórico REST e atualiza automaticamente.</p><dl className="facts stacked"><div><dt>Eventos na última hora</dt><dd>{wsStatus.events_persisted_last_hour || 0}</dd></div><div><dt>Kill channel</dt><dd>{wsStatus.connections?.kills || 0}</dd></div><div><dt>Map channel</dt><dd>{wsStatus.connections?.map || 0}</dd></div></dl></aside></div>;

  const renderApi = () => <div className="api-layout"><article className="panel"><PanelHead title="Operações do servidor" subtitle="Ações controladas sobre FTP e sincronização" /><div className="action-grid"><ActionButton title="Testar FTP" detail="Autentica e lê a raiz" glyph="⌁" busy={action === "ftp-test"} onClick={() => runAction("ftp-test", "ftp/test")} /><ActionButton title="Descobrir arquivos" detail="Mapeia a árvore remota" glyph="⌕" busy={action === "discover"} onClick={() => runAction("discover", "ftp/discover")} /><ActionButton title="Sincronizar agora" detail="Importa alterações" glyph="↻" busy={action === "sync"} onClick={() => runAction("sync", "sync/run")} /><ActionButton title="Iniciar polling" detail="Atualização contínua" glyph="▶" busy={action === "start"} onClick={() => runAction("start", "sync/start")} /><ActionButton title="Parar polling" detail="Suspende novos ciclos" glyph="■" busy={action === "stop"} onClick={() => runAction("stop", "sync/stop")} /></div>{actionResult && <pre className={actionResult.error ? "result error" : "result"}>{JSON.stringify(actionResult, null, 2)}</pre>}</article><article className="panel"><PanelHead title="Explorador REST" subtitle="Consulte qualquer endpoint GET publicado" /><div className="explorer"><span>GET</span><input value={explorerPath} onChange={e => setExplorerPath(e.target.value)} /><button className="primary" onClick={async () => { setExplorerResult("Carregando…"); try { setExplorerResult(JSON.stringify(await api(explorerPath), null, 2)); } catch (e) { setExplorerResult(String(e)); } }}>Executar</button></div><pre className="result explorer-result">{explorerResult || "A resposta aparecerá aqui."}</pre></article><article className="panel endpoint-panel"><PanelHead title="Catálogo de endpoints" subtitle={`${endpointCatalog.length} operações principais`} /><div className="endpoint-list">{endpointCatalog.map(([name, method, path]) => <div key={`${method}-${path}`}><span className={`method method-${method.toLowerCase()}`}>{method}</span><b>{name}</b><code>{path}</code><Badge tone="good">disponível</Badge></div>)}</div></article></div>;

  const content = section === "overview" ? renderOverview() : section === "map" ? renderMap() : section === "characters" ? renderCharacters() : section === "vehicles" ? renderVehicles() : section === "storages" ? renderStorages() : section === "combat" ? renderCombat() : section === "events" ? renderEvents() : renderApi();
  const sectionLabel = nav.find(item => item.id === section)?.label;

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? "open" : ""}`}><div className="brand"><span>DS</span><div><strong>DEADSIDE</strong><small>COMMAND CENTER</small></div></div><div className="server-chip"><i /><div><span>Servidor ativo</span><strong>{SERVER}</strong></div></div><nav>{nav.map(item => <button key={item.id} className={section === item.id ? "active" : ""} onClick={() => { setSection(item.id); setSearch(""); setMobileNav(false); }}><span>{item.glyph}</span>{item.label}{item.id === "events" && <em>{liveEvents.length || ""}</em>}</button>)}</nav><div className="sidebar-bottom"><div><span>API</span><Badge tone="good">online</Badge></div><small>Deadside Data API v0.1.0</small></div></aside>
    <main><header><button className="menu-btn" onClick={() => setMobileNav(!mobileNav)}>☰</button><div><span className="breadcrumb">DEADSIDE / {sectionLabel?.toUpperCase()}</span><h1>{sectionLabel}</h1></div><div className="header-actions"><div className="updated"><span>Última atualização</span><strong>{lastUpdated ? lastUpdated.toLocaleTimeString("pt-BR") : "—"}</strong></div><button className="refresh" disabled={refreshing} onClick={() => load(true)}><span className={refreshing ? "spin" : ""}>↻</span> Atualizar</button><Badge tone={sync.connected ? "good" : "bad"}>{sync.connected ? "conectado" : "offline"}</Badge></div></header>
      {error && <div className="alert"><b>Não foi possível atualizar:</b> {error}<button onClick={() => load()}>Tentar novamente</button></div>}
      <div className="content">{loading ? <div className="loading-grid">{Array.from({ length: 8 }, (_, i) => <i key={i} />)}</div> : content}</div>
    </main>
  </div>;
}

function Metric({ label, value, detail, glyph }: { label: string; value: React.ReactNode; detail: string; glyph: string }) { return <article className="metric"><span>{glyph}</span><div><small>{label}</small><strong>{value}</strong><p>{detail}</p></div></article>; }
function PanelHead({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) { return <div className="panel-head"><div><h2>{title}</h2><p>{subtitle}</p></div>{action}</div>; }
function Search({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) { return <label className="search"><span>⌕</span><input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} /></label>; }
function Gauge({ label, value }: { label: string; value?: number }) { const normalized = Math.min(100, Math.max(0, value || 0)); return <div><span><small>{label}</small><b>{fmtNumber(value, "%")}</b></span><i><em style={{ width: `${normalized}%` }} /></i></div>; }
function EventRow({ event, detailed = false }: { event: Dict; detailed?: boolean }) { const kind = event.event || event.event_name || "event.unknown"; const data = event.data || {}; return <div className={`event-row ${detailed ? "detailed" : ""}`}><span className={`event-icon event-${kind.split(".")[0]}`}>{kind.startsWith("kill") ? "✦" : kind.startsWith("sync") ? "↻" : kind.startsWith("ftp") ? "⌁" : kind.includes("vehicle") ? "◆" : "◎"}</span><div><b>{kind.replaceAll(".", " · ")}</b><p>{data.message || data.player_name || data.display_name || data.remote_path || data.status || `Entidade ${event.entity_id ? shorten(event.entity_id, 24) : "atualizada"}`}</p><small>#{event.sequence || "live"} · {fmtDate(event.occurred_at || event.published_at)}</small></div>{event.channel && <Badge tone="blue">{event.channel}</Badge>}</div>; }
function ActionButton({ title, detail, glyph, busy, onClick }: { title: string; detail: string; glyph: string; busy: boolean; onClick: () => void }) { return <button className="action-button" disabled={busy} onClick={onClick}><span>{busy ? "…" : glyph}</span><div><b>{title}</b><small>{detail}</small></div><em>→</em></button>; }
