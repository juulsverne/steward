import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { markerTone } from "../api/labels";
import type { BoardMarker } from "../types";
import { Notice } from "./Notice";

function toneColor(tone: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--status-${tone}-fg`).trim() || "#2B4A7A";
}

export function IssueMap({ markers, selectedId, onSelect }: { markers: BoardMarker[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);

  useEffect(() => {
    if (!box.current || map.current) return;
    const m = L.map(box.current, { zoomControl: true, keyboard: false, attributionControl: true });
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' });
    tiles.on("tileerror", () => setTilesFailed(true));
    tiles.addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.setView([41.867, -87.625], 15);
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current, g = layer.current; if (!m || !g) return;
    g.clearLayers();
    const located = markers.filter((k) => k.latitude !== null && k.longitude !== null);
    for (const k of located) {
      const color = toneColor(markerTone(k.marker_state));
      const circle = L.circleMarker([k.latitude!, k.longitude!], { radius: k.issue_id === selectedId ? 11 : 8, color, fillColor: color, fillOpacity: 0.85, weight: 2 });
      circle.bindTooltip(k.label, { permanent: true, direction: "top", offset: [0, -10], className: "issue-map__label" });
      circle.bindPopup(`<strong>${k.label}</strong><br>${k.status}${k.simulated ? " (simulated dispatch)" : ""}<br><a href="/issues/${k.issue_id}">Open issue</a>`);
      circle.on("click", () => onSelect(k.issue_id));
      circle.addTo(g);
    }
    if (located.length) m.fitBounds(L.latLngBounds(located.map((k) => [k.latitude!, k.longitude!] as [number, number])), { padding: [32, 32], maxZoom: 17 });
  }, [markers, selectedId, onSelect]);

  useEffect(() => {
    const m = map.current; const k = markers.find((x) => x.issue_id === selectedId);
    if (m && k && k.latitude !== null && k.longitude !== null) m.panTo([k.latitude!, k.longitude!]);
  }, [selectedId, markers]);

  return (
    <div className="issue-map">
      {tilesFailed && <Notice tone="warning" title="Map tiles are unavailable">The issue list and links still work.</Notice>}
      <div ref={box} className="issue-map__canvas" aria-hidden="true" />
    </div>
  );
}
