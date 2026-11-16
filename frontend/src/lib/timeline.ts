import type { ItemResult, TimelineSegment, TimelineState } from "../types";

/** Status heatmap pada detik `t`. Di luar segmen mana pun dianggap aman (clear). */
export function stateAt(timeline: TimelineSegment[], t: number): TimelineState {
  for (const seg of timeline) {
    if (t >= seg.start && t < seg.end) return seg.state;
  }
  return "clear";
}

export interface RateOptions {
  auto: boolean;
  fast: number;   // kecepatan di zona hijau saat auto aktif (mis. 1.5)
  manual: number; // kecepatan pilihan pengguna saat auto mati
}

/** Kecepatan putar: cepat di zona hijau, normal (1x) di zona merah atau kuning. */
export function desiredRate(state: TimelineState, o: RateOptions): number {
  if (!o.auto) return o.manual;
  return state === "clear" ? o.fast : 1;
}

/** "frame_0112.jpg" -> 112 */
export function frameSecond(name: string): number | null {
  const m = /frame_(\d+)\.jpg$/i.exec(name);
  return m ? Number(m[1]) : null;
}

export function formatClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const LEAD_SEC = 2;

/** Detik tujuan saat item diklik: sedikit sebelum momen supaya konteks terlihat. */
export function seekTargetFor(item: ItemResult): number | null {
  if (item.moment_sec != null) return Math.max(0, item.moment_sec - LEAD_SEC);
  if (item.flagged_ranges.length > 0) return item.flagged_ranges[0].start;
  return null;
}
