/** MapLibre GL map (OSM raster tiles) of stations and vehicle last positions. Loaded lazily by the pages that use it. */
import maplibregl, { type Map as MLMap, Marker, Popup } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef } from 'react';
import type { StationOut, VehicleOut } from '../api/types';
import { fmtAgo } from '../lib/format';

const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster', tileSize: 256, maxzoom: 19,
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

export default function StationMap({ stations = [], vehicles = [], height = 360, focus }: { stations?: StationOut[]; vehicles?: VehicleOut[]; height?: number; focus?: { lat: number; lon: number } | null }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const markers = useRef<Marker[]>([]);

  useEffect(() => {
    if (!el.current || map.current) return;
    map.current = new maplibregl.Map({ container: el.current, style: STYLE, center: [38.5, -2.6], zoom: 5.6, attributionControl: false });
    map.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.current.addControl(new maplibregl.AttributionControl({ compact: true }));
    return () => { map.current?.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    markers.current.forEach((mk) => mk.remove());
    markers.current = [];
    const bounds = new maplibregl.LngLatBounds();
    let n = 0;
    for (const s of stations) {
      const d = document.createElement('button');
      d.type = 'button';
      d.setAttribute('aria-label', `${s.name} (${s.status})`);
      const color = s.status === 'operational' ? '#0d9488' : s.status === 'degraded' ? '#d97706' : '#dc2626';
      d.className = 'rounded-md border-2 border-white px-1.5 py-0.5 text-[10px] font-bold text-white shadow focus:outline-none focus:ring-2 focus:ring-white';
      d.style.background = color;
      d.textContent = `${s.code} · q${s.queue_len}`;
      const popup = new Popup({ offset: 12 }).setHTML(`<strong>${s.name}</strong><br/>${s.status} · queue ${s.queue_len} · wait ${Math.round(s.avg_wait_s / 60)} min<br/>last hour: G${s.decisions_last_hour.GREEN} A${s.decisions_last_hour.AMBER} R${s.decisions_last_hour.RED}`);
      markers.current.push(new Marker({ element: d }).setLngLat([s.lon, s.lat]).setPopup(popup).addTo(m));
      bounds.extend([s.lon, s.lat]); n++;
    }
    for (const v of vehicles) {
      if (v.last_lat === null || v.last_lon === null) continue;
      const d = document.createElement('button');
      d.type = 'button';
      d.setAttribute('aria-label', `Vehicle ${v.plate}`);
      d.className = 'h-3 w-3 rounded-full border-2 border-white bg-slate-700 shadow dark:bg-slate-200 dark:border-slate-900';
      const popup = new Popup({ offset: 8 }).setHTML(`<strong>${v.plate}</strong><br/>${v.body_type} · ${v.axle_config}<br/>seen ${fmtAgo(v.last_seen_at)}${v.watchlisted ? '<br/><b>WATCH-LISTED</b>' : ''}`);
      markers.current.push(new Marker({ element: d }).setLngLat([v.last_lon, v.last_lat]).setPopup(popup).addTo(m));
      bounds.extend([v.last_lon, v.last_lat]); n++;
    }
    if (focus) { m.easeTo({ center: [focus.lon, focus.lat], zoom: 11 }); }
    else if (n > 1) m.fitBounds(bounds, { padding: 40, maxZoom: 10, duration: 0 });
    else if (n === 1) m.jumpTo({ center: bounds.getCenter(), zoom: 9 });
  }, [stations, vehicles, focus]);

  return <div ref={el} style={{ height }} className="w-full overflow-hidden rounded-lg" role="region" aria-label="Map of stations and vehicles" />;
}
