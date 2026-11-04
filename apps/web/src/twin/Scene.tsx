/**
 * Stylised 3D scene: Port of Mombasa container terminal + gate, the trunk road, two weighing stations with WIM and static
 * lanes, a parking/inspection area and a warehouse. Trucks are spawned from live events and coloured by clearance decision.
 */
import { Html, OrbitControls } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import type { Group, Mesh } from 'three';
import type { Decision } from '../api/types';

export interface TwinStation { id: string; code: string; name: string; status: string; queue_len: number; x: number; laneIds: string[] }
export interface TwinTruck { id: string; laneId: string | null; stationIdx: number; decision: Decision | null; plate: string | null; spawnedAt: number; source: string | null }
export interface TwinIncident { id: string; stationIdx: number | null; severity: string; title: string }

const DECISION_HEX: Record<Decision, string> = { GREEN: '#16a34a', AMBER: '#d97706', RED: '#dc2626' };
export const STATION_X = [-8, 18];
const ROAD_Z = 0;
const STATIC_Z = 3.2;
const PARK = { x: 6, z: 10 };
const ROAD_START = -46;
const ROAD_END = 46;
const SPEED = 7;

function Box({ position, size, color, opacity = 1 }: { position: [number, number, number]; size: [number, number, number]; color: string; opacity?: number }) {
  return (
    <mesh position={position} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} transparent={opacity < 1} opacity={opacity} />
    </mesh>
  );
}

function Label({ position, children, small }: { position: [number, number, number]; children: React.ReactNode; small?: boolean }) {
  return (
    <Html position={position} center distanceFactor={small ? 40 : 60} zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
      <div className={`whitespace-nowrap rounded bg-slate-900/80 px-1.5 py-0.5 text-white ${small ? 'text-[10px]' : 'text-xs font-semibold'}`}>{children}</div>
    </Html>
  );
}

function Terminal() {
  const stacks: JSX.Element[] = [];
  const colors = ['#1e40af', '#0f766e', '#7c2d12', '#374151', '#4c1d95'];
  for (let r = 0; r < 4; r++) for (let c = 0; c < 7; c++) {
    const h = 1 + ((r * 7 + c) % 3);
    stacks.push(<Box key={`${r}-${c}`} position={[-42 + c * 2.6, h / 2, -10 - r * 3.2]} size={[2.4, h, 1.2]} color={colors[(r + c) % colors.length]} />);
  }
  return (
    <group>
      <Box position={[-33, -0.02, -14]} size={[22, 0.04, 14]} color="#475569" />
      {stacks}
      {/* quay cranes */}
      {[-40, -32, -24].map((x) => (
        <group key={x} position={[x, 0, -22]}>
          <Box position={[-1.5, 3.5, 0]} size={[0.3, 7, 0.3]} color="#dc8a3a" /><Box position={[1.5, 3.5, 0]} size={[0.3, 7, 0.3]} color="#dc8a3a" /><Box position={[0, 7, 1]} size={[0.3, 0.3, 8]} color="#dc8a3a" />
        </group>
      ))}
      <Box position={[-33, -0.1, -27]} size={[26, 0.02, 6]} color="#1e3a8a" />
      <Label position={[-33, 6, -14]}>Port of Mombasa — container terminal</Label>
    </group>
  );
}

function Gate() {
  return (
    <group position={[-24, 0, ROAD_Z]}>
      <Box position={[0, 1.5, -2.5]} size={[0.6, 3, 0.6]} color="#64748b" /><Box position={[0, 1.5, 2.5]} size={[0.6, 3, 0.6]} color="#64748b" /><Box position={[0, 3.2, 0]} size={[0.6, 0.5, 6]} color="#64748b" />
      <Label position={[0, 4.2, 0]} small>Gate 18</Label>
    </group>
  );
}

function Station({ s, idx }: { s: TwinStation; idx: number }) {
  const x = STATION_X[idx];
  const col = s.status === 'operational' ? '#0d9488' : s.status === 'degraded' ? '#d97706' : '#dc2626';
  return (
    <group position={[x, 0, 0]}>
      {/* WIM sensor rows embedded in the lane */}
      <Box position={[0, 0.02, ROAD_Z - 0.9]} size={[3, 0.05, 1.6]} color="#0ea5a0" opacity={0.9} />
      <Box position={[0, 0.02, ROAD_Z + 0.9]} size={[3, 0.05, 1.6]} color="#0ea5a0" opacity={0.9} />
      {/* gantry with cameras / RFID */}
      <Box position={[0, 2.5, -3]} size={[0.3, 5, 0.3]} color={col} /><Box position={[0, 2.5, 5.2]} size={[0.3, 5, 0.3]} color={col} /><Box position={[0, 5, 1.1]} size={[0.3, 0.3, 8.5]} color={col} />
      {/* static scale lane + cabin */}
      <Box position={[0, 0.03, STATIC_Z]} size={[5, 0.06, 1.8]} color="#94a3b8" />
      <Box position={[0, 1, STATIC_Z + 2]} size={[2, 2, 1.2]} color="#e2e8f0" />
      <Label position={[0, 6.2, 1]}>{s.code} · {s.status} · queue {s.queue_len}</Label>
      <Label position={[0, 1.2, STATIC_Z + 3.5]} small>static scale</Label>
    </group>
  );
}

function QueueGhosts({ s, idx }: { s: TwinStation; idx: number }) {
  const n = Math.min(s.queue_len, 24);
  const x0 = STATION_X[idx] - 4;
  return (
    <group>
      {Array.from({ length: n }, (_, i) => <Box key={i} position={[x0 - i * 1.4, 0.4, ROAD_Z - 0.9]} size={[1.1, 0.8, 0.7]} color="#94a3b8" opacity={0.55} />)}
      {s.queue_len > 0 && <Label position={[x0 - Math.min(n, 6) * 0.7, 2, ROAD_Z - 2.5]} small>queue {s.queue_len} (observed)</Label>}
    </group>
  );
}

function Parking() {
  return (
    <group position={[PARK.x, 0, PARK.z]}>
      <Box position={[0, -0.01, 0]} size={[14, 0.04, 6]} color="#52525b" />
      <Label position={[0, 1.5, 0]} small>inspection / holding</Label>
    </group>
  );
}

function Warehouse() {
  return (
    <group position={[32, 0, 11]}>
      <Box position={[0, 2, 0]} size={[12, 4, 7]} color="#cbd5e1" /><Box position={[0, 4.3, 0]} size={[12.4, 0.5, 7.4]} color="#64748b" />
      {[-3, 0, 3].map((z) => <Box key={z} position={[-6.1, 1, z]} size={[0.2, 2, 1.6]} color="#334155" />)}
      <Label position={[0, 5.5, 0]}>Warehouse / ICD</Label>
    </group>
  );
}

function Road() {
  return (
    <group>
      <Box position={[0, -0.03, ROAD_Z]} size={[ROAD_END - ROAD_START + 4, 0.02, 4.2]} color="#334155" />
      <Box position={[0, -0.03, STATIC_Z]} size={[60, 0.02, 2.2]} color="#3f3f46" />
      {Array.from({ length: 23 }, (_, i) => <Box key={i} position={[ROAD_START + 2 + i * 4, 0, ROAD_Z]} size={[2, 0.03, 0.12]} color="#e2e8f0" />)}
      <Label position={[ROAD_START + 2, 1.5, -3]} small>from port →</Label>
      <Label position={[ROAD_END - 2, 1.5, -3]} small>→ Northern Corridor</Label>
    </group>
  );
}

function Truck({ t, onDone }: { t: TwinTruck; onDone: (id: string) => void }) {
  const g = useRef<Group>(null);
  const state = useRef({ x: ROAD_START, z: ROAD_Z, pauseUntil: 0, parked: false, done: false });
  const stationX = STATION_X[t.stationIdx] ?? STATION_X[0];
  useFrame((_, dt) => {
    const s = state.current; const grp = g.current;
    if (!grp || s.done) return;
    const now = performance.now();
    if (s.parked) { if (now > s.pauseUntil) { s.done = true; onDone(t.id); } return; }
    if (now < s.pauseUntil) return;
    const past = s.x > stationX + 1;
    if (t.decision === 'RED' && past) {
      // drive to parking and hold
      const dx = PARK.x - s.x, dz = PARK.z - s.z; const d = Math.hypot(dx, dz);
      if (d < 0.3) { s.parked = true; s.pauseUntil = now + 8000; } else { s.x += (dx / d) * SPEED * dt; s.z += (dz / d) * SPEED * dt; }
    } else if (t.decision === 'AMBER' && s.x > stationX - 6 && s.x < stationX + 8) {
      // divert to static lane, pause on the scale, rejoin
      const targetZ = STATIC_Z; s.z += (targetZ - s.z) * Math.min(1, dt * 3); s.x += SPEED * 0.6 * dt;
      if (Math.abs(s.x - stationX) < 0.2 && s.pauseUntil < now - 100) { s.pauseUntil = now + 2500; }
    } else {
      s.z += (ROAD_Z - s.z) * Math.min(1, dt * 2); s.x += SPEED * dt;
    }
    if (s.x > ROAD_END) { s.done = true; onDone(t.id); }
    grp.position.set(s.x, 0, s.z);
  });
  const color = t.decision ? DECISION_HEX[t.decision] : '#94a3b8';
  return (
    <group ref={g} position={[ROAD_START, 0, ROAD_Z]}>
      <Box position={[0.9, 0.9, 0]} size={[1.2, 1.4, 1.1]} color={color} />
      <Box position={[-1.1, 1, 0]} size={[2.6, 1.6, 1.2]} color="#1e293b" />
      <Box position={[-1.1, 1.9, 0]} size={[2.6, 0.2, 1.2]} color={color} />
      {[-2, -1.2, 1].map((x) => <mesh key={x} position={[x, 0.3, 0]}><cylinderGeometry args={[0.3, 0.3, 1.3, 10]} /><meshStandardMaterial color="#0f172a" /></mesh>)}
      <Label position={[0, 2.8, 0]} small>{t.plate ?? '…'} {t.decision ?? ''}</Label>
    </group>
  );
}

function IncidentMarker({ idx, severity, title }: { idx: number; severity: string; title: string }) {
  const m = useRef<Mesh>(null);
  useFrame(({ clock }) => { if (m.current) { m.current.position.y = 8 + Math.sin(clock.elapsedTime * 3) * 0.4; m.current.rotation.y += 0.02; } });
  return (
    <group position={[STATION_X[idx], 0, -5]}>
      <mesh ref={m} position={[0, 8, 0]}><coneGeometry args={[0.8, 1.6, 4]} /><meshStandardMaterial color={severity === 'critical' || severity === 'high' ? '#dc2626' : '#d97706'} emissive="#7f1d1d" /></mesh>
      <Label position={[0, 10, 0]} small>⚠ {title}</Label>
    </group>
  );
}

export default function Scene({ stations, trucks, incidents, onTruckDone }: { stations: TwinStation[]; trucks: TwinTruck[]; incidents: TwinIncident[]; onTruckDone: (id: string) => void }) {
  return (
    <Canvas shadows camera={{ position: [0, 28, 42], fov: 45 }} dpr={[1, 1.5]} gl={{ antialias: true, powerPreference: 'low-power' }}>
      <color attach="background" args={['#0b1220']} />
      <fog attach="fog" args={['#0b1220', 70, 140]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[20, 30, 10]} intensity={1.2} castShadow shadow-mapSize={[1024, 1024]} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]} receiveShadow><planeGeometry args={[160, 100]} /><meshStandardMaterial color="#1f2937" /></mesh>
      <Terminal /><Gate /><Road /><Parking /><Warehouse />
      {stations.slice(0, 2).map((s, i) => <group key={s.id}><Station s={s} idx={i} /><QueueGhosts s={s} idx={i} /></group>)}
      {trucks.map((t) => <Truck key={t.id} t={t} onDone={onTruckDone} />)}
      {incidents.filter((i) => i.stationIdx !== null).map((i) => <IncidentMarker key={i.id} idx={i.stationIdx!} severity={i.severity} title={i.title} />)}
      <OrbitControls maxPolarAngle={Math.PI / 2.1} minDistance={15} maxDistance={110} target={[0, 0, 0]} />
    </Canvas>
  );
}
