"use client";

import { useEffect, useRef, useState } from "react";
import type { LayerGroup, Map as LeafletMap } from "leaflet";

type Dict = Record<string, any>;

type LeafletRuntime = {
  map: LeafletMap;
  markers: LayerGroup;
  L: typeof import("leaflet");
};

const TILE_URL = "/api/proxy?path=/api/v1/maps/mirny/tiles/lod_{z}/map_{x}_{y}.png";

export default function FtpLeafletMap({
  markers,
  counts,
  onSelect,
}: {
  markers: Dict[];
  counts: Dict;
  onSelect: (marker: Dict) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const runtimeRef = useRef<LeafletRuntime | null>(null);
  const selectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  selectRef.current = onSelect;

  useEffect(() => {
    let disposed = false;
    let runtime: LeafletRuntime | null = null;

    void import("leaflet").then((L) => {
      if (disposed || !containerRef.current) return;
      const map = L.map(containerRef.current, {
        crs: L.CRS.Simple,
        minZoom: -1,
        maxZoom: 3,
        zoomSnap: 1,
        zoomDelta: 1,
        scrollWheelZoom: true,
        touchZoom: true,
        doubleClickZoom: true,
        dragging: true,
        zoomControl: true,
        attributionControl: false,
        maxBounds: L.latLngBounds(L.latLng(150, -150), L.latLng(-1558, 1430)),
        maxBoundsViscosity: 0.82,
      });

      L.tileLayer(TILE_URL, {
        tileSize: 512,
        continuousWorld: false,
        noWrap: true,
        bounds: L.latLngBounds(L.latLng(0, 0), L.latLng(-1408, 1280)),
        zoomReverse: true,
        minZoom: -1,
        maxZoom: 3,
        minNativeZoom: -1,
        maxNativeZoom: 2,
        keepBuffer: 2,
        updateWhenZooming: false,
      }).addTo(map);

      const grid = L.layerGroup().addTo(map);
      for (let x = 0; x <= 10; x += 1) {
        const mapX = 1280 * x / 10;
        L.polyline([[-1408, mapX], [0, mapX]], { weight: 1, color: "#DADADA33", interactive: false }).addTo(grid);
      }
      for (let y = 0; y <= 11; y += 1) {
        const mapY = -1408 * y / 11;
        L.polyline([[mapY, 0], [mapY, 1280]], { weight: 1, color: "#DADADA33", interactive: false }).addTo(grid);
      }

      const markerLayer = L.layerGroup().addTo(map);
      map.setView([-846, 709], 2);
      runtime = { map, markers: markerLayer, L };
      runtimeRef.current = runtime;
      setReady(true);
      requestAnimationFrame(() => map.invalidateSize());
    });

    return () => {
      disposed = true;
      setReady(false);
      if (runtimeRef.current === runtime) runtimeRef.current = null;
      runtime?.map.remove();
    };
  }, []);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!ready || !runtime) return;
    const { L, markers: markerLayer } = runtime;
    markerLayer.clearLayers();

    markers.forEach((marker) => {
      const position = marker.map_position;
      if (!position?.inside_map) return;
      const icon = marker.kind === "vehicle"
        ? L.icon({
          iconUrl: `/markers/marker-${marker.icon || "car"}.png`,
          iconSize: [25, 41],
          iconAnchor: [12, 41],
          popupAnchor: [0, -41],
        })
        : L.divIcon({
          className: "ftp-player-marker",
          html: "<span></span>",
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        });
      const layer = L.marker([position.y, position.x], { icon, riseOnHover: true, keyboard: true });
      const tooltip = document.createElement("span");
      tooltip.textContent = `${marker.kind === "player" ? "Jogador" : "Veículo"}: ${marker.label || marker.entity_id}`;
      layer.bindTooltip(tooltip, { direction: "top", offset: [0, -12], opacity: 0.92 });
      layer.on("click", () => selectRef.current(marker));
      layer.addTo(markerLayer);
    });
  }, [markers, ready]);

  return <div className="leaflet-map-stage">
    <div ref={containerRef} className="ftp-leaflet-map" aria-label="Mapa interativo de Mirny com entidades do FTP" />
    {!ready && <div className="map-loading">Carregando mapa interativo…</div>}
    <div className="map-gesture-hint">Arraste para mover · roda ou pinça para zoom</div>
    <div className="map-legend">
      <span><i className="legend-player" />Jogadores</span>
      <span><i className="legend-vehicle" />Veículos</span>
      <b>{counts?.players || 0} jogadores · {counts?.vehicles || 0} veículos</b>
    </div>
  </div>;
}
