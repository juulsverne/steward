import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { issueStatus, markerTone } from "../api/labels";
import type { BoardMarker } from "../types";
import { Notice } from "./Notice";

function toneColor(tone: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--status-${tone}-fg`).trim() || "#2B4A7A";
}

// Builds the popup with DOM APIs only (never innerHTML) so a resident-supplied
// label can never inject markup - see the stored-XSS finding on bindPopup.
export function markerPopup(k: BoardMarker): HTMLElement {
  const container = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = k.label;
  container.appendChild(strong);
  container.appendChild(document.createElement("br"));
  container.appendChild(document.createTextNode(`${issueStatus(k.status).label}${k.simulated ? " (simulated dispatch)" : ""}`));
  container.appendChild(document.createElement("br"));
  const link = document.createElement("a");
  link.href = `/issues/${encodeURIComponent(k.issue_id)}`;
  link.textContent = "Open issue";
  container.appendChild(link);
  return container;
}

export function IssueMap({ markers, selectedId, onSelect }: { markers: BoardMarker[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);
  const [tilesFailed, setTilesFailed] = useState(false);

  useEffect(() => {
    if (!box.current || map.current) return;
    const m = L.map(box.current, { zoomControl: false, keyboard: false, attributionControl: false });
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' });
    tiles.on("tileerror", () => setTilesFailed(true));
    tiles.addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.setView([41.88206, -87.62780], 15);
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
      const tooltip = document.createElement("span");
      tooltip.textContent = k.label;
      circle.bindTooltip(tooltip, { permanent: true, direction: "top", offset: [0, -10], className: "issue-map__label" });
      circle.bindPopup(markerPopup(k));
      circle.on("click", () => onSelect(k.issue_id));
      circle.addTo(g);
    }
  }, [markers, selectedId, onSelect]);

  // fitBounds only once, the first time there is at least one located marker -
  // not on every hover-driven selection change or 20s poll, which would fight
  // the operator's own pan/zoom.
  useEffect(() => {
    const m = map.current; if (!m || fitted.current) return;
    const located = markers.filter((k) => k.latitude !== null && k.longitude !== null);
    if (!located.length) return;
    fitted.current = true;
    m.fitBounds(L.latLngBounds(located.map((k) => [k.latitude!, k.longitude!] as [number, number])), { padding: [32, 32], maxZoom: 17 });
  }, [markers]);

  useEffect(() => {
    const m = map.current; const k = markers.find((x) => x.issue_id === selectedId);
    if (m && k && k.latitude !== null && k.longitude !== null) m.panTo([k.latitude!, k.longitude!]);
  }, [selectedId, markers]);

  return (
    <div className="issue-map">
      {tilesFailed && <Notice tone="warning" title="Map tiles are unavailable">The issue list and links still work.</Notice>}
      <div ref={box} className="issue-map__canvas" aria-hidden="true" />
      <p className="small muted issue-map__attribution">Map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors</p>
    </div>
  );
}
