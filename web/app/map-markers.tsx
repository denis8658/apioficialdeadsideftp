"use client";

import { useEffect, useMemo, useState } from "react";

type MarkerRow = [type: string, name: string | null, x: number, y: number, extra?: unknown];

export type ReferenceMarker = {
  key: string;
  kind: "reference";
  type: string;
  typeLabel: string;
  name: string;
  x: number;
  y: number;
  count: number;
  group: string;
  groupLabel: string;
  icon: string;
};

type GroupId = "locations" | "services" | "missions" | "events" | "animals" | "vehicles" | "foraging" | "loot";

type MarkerGroup = {
  id: GroupId;
  label: string;
  icon: string;
  dense?: boolean;
};

const GROUPS: MarkerGroup[] = [
  { id: "locations", label: "Locais", icon: "/markers/icon-poi.png" },
  { id: "services", label: "Serviços", icon: "/markers/icon-fast-travel.png" },
  { id: "missions", label: "Missões e bunkers", icon: "/markers/icon-mission-easy.png" },
  { id: "events", label: "Eventos", icon: "/markers/icon-airdrop.png", dense: true },
  { id: "animals", label: "Animais", icon: "/markers/icon-deer.png", dense: true },
  { id: "vehicles", label: "Veículos", icon: "/markers/icon-car.png" },
  { id: "foraging", label: "Coleta", icon: "/markers/icon-berry.png", dense: true },
  { id: "loot", label: "Loot", icon: "/markers/icon-gascan.png", dense: true },
];

const DEFAULT_GROUPS: GroupId[] = ["locations", "services", "missions", "events", "vehicles"];

const TYPE_LABELS: Record<string, string> = {
  safeZones: "Zona segura",
  mapLabels: "Localidade",
  mapPois: "Ponto de interesse",
  fastTravels: "Viagem rápida",
  wells: "Poço",
  woodPlaners: "Plaina de madeira",
  metalPlaners: "Plaina de metal",
  missionZones: "Área de missão",
  missionEasy: "Missão fácil",
  missionMedium: "Missão média",
  missionHard: "Missão difícil",
  missionEpic: "Missão épica",
  missionRewards: "Recompensa de missão",
  bunkerBig: "Bunker grande",
  bunkerSmall: "Bunker pequeno",
  airdrops: "Airdrop",
  traders: "Comerciante",
  heliCrashes: "Helicóptero abatido",
  treasures: "Esconderijo",
  convoys: "Comboio",
  ducks: "Patos",
  wolves: "Lobos",
  deer: "Cervos",
  boats: "Barco",
  bikes: "Motocicleta",
  cars: "Carro",
  apple: "Maçã",
  berry: "Frutas silvestres",
  herb: "Folhas medicinais",
  mushroom: "Cogumelo",
  scrap: "Sucata",
  mussel: "Mexilhão",
  brick: "Tijolo",
  gas: "Galão de combustível",
  cement: "Cimento",
};

function groupFor(type: string): GroupId {
  if (type.startsWith("lootable-container-") || type === "gas" || type === "cement") return "loot";
  if (["apple", "berry", "herb", "mushroom", "scrap", "mussel", "brick"].includes(type)) return "foraging";
  if (["boats", "bikes", "cars"].includes(type)) return "vehicles";
  if (["ducks", "wolves", "deer"].includes(type)) return "animals";
  if (["airdrops", "traders", "heliCrashes", "treasures", "convoys"].includes(type)) return "events";
  if (type.startsWith("mission") || type.startsWith("bunker")) return "missions";
  if (["fastTravels", "wells", "woodPlaners", "metalPlaners"].includes(type)) return "services";
  return "locations";
}

function iconFor(type: string): string {
  const direct: Record<string, string> = {
    mapPois: "poi",
    fastTravels: "fast-travel",
    wells: "well",
    woodPlaners: "wood-planer",
    metalPlaners: "metal-planer",
    missionEasy: "mission-easy",
    missionMedium: "mission-medium",
    missionHard: "mission-hard",
    missionEpic: "mission-epic",
    missionRewards: "mission-reward",
    bunkerBig: "bunker",
    bunkerSmall: "bunker",
    airdrops: "airdrop",
    traders: "trader",
    heliCrashes: "heli-crash",
    treasures: "treasure",
    convoys: "convoy",
    ducks: "duck",
    wolves: "wolf",
    deer: "deer",
    boats: "boat",
    bikes: "bike",
    cars: "car",
    apple: "apple",
    berry: "berry",
    herb: "herb",
    mushroom: "mushroom",
    scrap: "scrap",
    mussel: "mussel",
    brick: "brick",
    gas: "gascan",
    cement: "cement",
  };
  if (direct[type]) return `/markers/marker-${direct[type]}.png`;
  if (type.includes("Folder_Military")) return "/markers/marker-folder-military.png";
  if (type.includes("Folder_Industrial")) return "/markers/marker-folder-industrial.png";
  if (type.includes("electricity_meter")) return "/markers/marker-electrical-meter.png";
  if (type.includes("electr") || type.includes("fuse_box")) return "/markers/marker-electrical-box.png";
  if (type.includes("stove")) return "/markers/marker-stove.png";
  if (type.includes("brick_pile")) return "/markers/marker-pile-brick.png";
  if (type.includes("metal_pile")) return "/markers/marker-pile-scrap.png";
  if (type.includes("Trash_pile")) return "/markers/marker-pile-trash.png";
  if (type.includes("_mil")) return "/markers/marker-s-military.png";
  if (type.includes("Constr") || type.includes("cnstr")) return "/markers/marker-s-industrial.png";
  return "/markers/marker-s-residential.png";
}

function labelFor(type: string): string {
  if (TYPE_LABELS[type]) return TYPE_LABELS[type];
  if (type.startsWith("lootable-container-")) {
    return type.replace("lootable-container-LBS_", "").replace(/_C$/, "").replaceAll("_", " ");
  }
  return type;
}

function useReferenceMarkerData(zoom: number) {
  const [rows, setRows] = useState<MarkerRow[]>([]);
  const [enabled, setEnabled] = useState<Set<GroupId>>(() => new Set(DEFAULT_GROUPS));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch("/map-markers.json")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload) => { if (active) setRows(payload.markers || []); })
      .catch(() => { if (active) setRows([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const counts = useMemo(() => {
    const result = Object.fromEntries(GROUPS.map((group) => [group.id, 0])) as Record<GroupId, number>;
    rows.forEach((row) => { result[groupFor(row[0])] += 1; });
    return result;
  }, [rows]);

  const visible = useMemo(() => {
    const labels: MarkerRow[] = [];
    const circles: MarkerRow[] = [];
    const routes: MarkerRow[] = [];
    const buckets = new Map<string, { rows: MarkerRow[]; x: number; y: number; group: MarkerGroup }>();
    const cellSize = Math.max(18, 42 / zoom);

    rows.forEach((row) => {
      const groupId = groupFor(row[0]);
      if (!enabled.has(groupId)) return;
      if (row[0] === "mapLabels") { labels.push(row); return; }
      if (row[0] === "safeZones" || row[0] === "missionZones") { circles.push(row); return; }
      if (row[0] === "convoys" && Array.isArray(row[4])) routes.push(row);
      const group = GROUPS.find((entry) => entry.id === groupId)!;
      const key = `${groupId}:${Math.floor(row[2] / cellSize)}:${Math.floor(Math.abs(row[3]) / cellSize)}`;
      const bucket = buckets.get(key) || { rows: [], x: 0, y: 0, group };
      bucket.rows.push(row);
      bucket.x += row[2];
      bucket.y += Math.abs(row[3]);
      buckets.set(key, bucket);
    });

    const markers: ReferenceMarker[] = Array.from(buckets.entries()).map(([key, bucket]) => {
      const first = bucket.rows[0];
      const count = bucket.rows.length;
      return {
        key,
        kind: "reference",
        type: first[0],
        typeLabel: count > 1 ? `${bucket.group.label} agrupados` : labelFor(first[0]),
        name: count > 1 ? `${count.toLocaleString("pt-BR")} marcações` : (first[1] || labelFor(first[0])),
        x: bucket.x / count,
        y: bucket.y / count,
        count,
        group: bucket.group.id,
        groupLabel: bucket.group.label,
        icon: count > 1 ? bucket.group.icon : iconFor(first[0]),
      };
    });
    return { markers, labels, circles, routes };
  }, [enabled, rows, zoom]);

  const toggle = (id: GroupId) => setEnabled((current) => {
    const next = new Set(current);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  return { counts, enabled, loading, toggle, ...visible };
}

export function ReferenceMarkerControls({ data }: { data: ReturnType<typeof useReferenceMarkerData> }) {
  const activeCount = GROUPS.reduce((total, group) => total + (data.enabled.has(group.id) ? data.counts[group.id] : 0), 0);
  return <div className="marker-controls" aria-label="Filtros das marcações do mapa">
    <div className="marker-controls-head">
      <span><b>Marcações de Mirny</b><small>{data.loading ? "carregando…" : `${activeCount.toLocaleString("pt-BR")} pontos ativos`}</small></span>
      <em>DS Info</em>
    </div>
    <div className="marker-filter-list">
      {GROUPS.map((group) => <button
        key={group.id}
        className={data.enabled.has(group.id) ? "active" : ""}
        onClick={() => data.toggle(group.id)}
        title={group.dense ? "Camada densa: os pontos serão agrupados automaticamente" : group.label}
        aria-pressed={data.enabled.has(group.id)}
      >
        <img src={group.icon} alt="" /><span>{group.label}<small>{data.counts[group.id].toLocaleString("pt-BR")}</small></span>
      </button>)}
    </div>
    <p>Camadas densas são agrupadas conforme o zoom para manter o mapa rápido.</p>
  </div>;
}

export function ReferenceMarkerLayer({
  data,
  onSelect,
  onCluster,
}: {
  data: ReturnType<typeof useReferenceMarkerData>;
  onSelect: (marker: ReferenceMarker) => void;
  onCluster: () => void;
}) {
  return <>
    <svg className="map-reference-zones" viewBox="0 0 1280 1408" aria-hidden="true">
      {data.routes.map((row, index) => <polyline
        key={`route-${index}`}
        className="convoy-route"
        points={(row[4] as { X: number; Y: number }[]).map((point) => `${point.X},${Math.abs(point.Y)}`).join(" ")}
      />)}
      {data.circles.map((row, index) => {
        const radius = Number(row[4] || 0) / 781.25;
        return <circle key={`zone-${index}`} className={row[0] === "safeZones" ? "safe-zone" : "mission-zone"} cx={row[2]} cy={Math.abs(row[3])} r={radius} />;
      })}
    </svg>
    <div className="map-place-labels" aria-hidden="true">
      {data.labels.map((row, index) => <span key={`${row[1]}-${index}`} style={{ left: `${row[2] / 12.8}%`, top: `${Math.abs(row[3]) / 14.08}%` }}>{String(row[4] || row[1] || "")}</span>)}
    </div>
    <div className="map-reference-markers">
      {data.markers.map((marker) => <button
        key={marker.key}
        className={`reference-marker reference-marker-${marker.group} ${marker.count > 1 ? "clustered" : ""}`}
        style={{ left: `${marker.x / 12.8}%`, top: `${marker.y / 14.08}%` }}
        title={`${marker.name} · ${marker.groupLabel}`}
        onClick={() => marker.count > 1 ? onCluster() : onSelect(marker)}
      >
        <img src={marker.icon} alt="" />
        {marker.count > 1 && <strong>{marker.count > 999 ? `${Math.round(marker.count / 100) / 10}k` : marker.count}</strong>}
      </button>)}
    </div>
  </>;
}

export function useReferenceMarkers(zoom: number) {
  return useReferenceMarkerData(zoom);
}
