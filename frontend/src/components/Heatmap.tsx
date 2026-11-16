import { useRef, useState } from "react";
import { formatClock } from "../lib/timeline";
import type { TimelineSegment } from "../types";

interface Props {
  timeline: TimelineSegment[];
  duration: number;
  current: number;
  onSeek: (sec: number) => void;
}

const ZONE_LABEL = { clear: "zona hijau", flagged: "zona merah", uncertain: "zona kuning" } as const;

export default function Heatmap({ timeline, duration, current, onSeek }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const pct = (sec: number) => `${Math.min(100, Math.max(0, (sec / duration) * 100))}%`;

  const timeAt = (clientX: number): number => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || box.width === 0) return 0;
    return Math.min(1, Math.max(0, (clientX - box.left) / box.width)) * duration;
  };
  const zoneAt = (t: number) => timeline.find((s) => t >= s.start && t < s.end)?.state ?? "clear";

  return (
    <div
      ref={ref}
      className="heatmap"
      role="slider"
      tabIndex={0}
      aria-label="Peta waktu video: hijau aman, merah bermasalah, kuning ragu"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(current)}
      aria-valuetext={formatClock(current)}
      onClick={(e) => onSeek(timeAt(e.clientX))}
      onMouseMove={(e) => setHover(timeAt(e.clientX))}
      onMouseLeave={() => setHover(null)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") onSeek(Math.min(duration, current + 5));
        if (e.key === "ArrowLeft") onSeek(Math.max(0, current - 5));
      }}
    >
      {timeline.map((s, i) => (
        <div
          key={i}
          className={`hm-seg hm-${s.state}`}
          style={{ left: pct(s.start), width: pct(s.end - s.start) }}
          data-state={s.state}
        />
      ))}
      <div className="hm-playhead" style={{ left: pct(current) }} />
      {hover !== null && (
        <div className="hm-tip" style={{ left: pct(hover) }}>
          {formatClock(hover)} · {ZONE_LABEL[zoneAt(hover)]}
        </div>
      )}
    </div>
  );
}
