import { useCallback, useEffect, useMemo, useState } from "react";
import { listVideos } from "../api";
import { StatusBadge } from "../components/Badges";
import UploadDialog from "../components/UploadDialog";
import { formatDateTime, humanizeSlug, ROLE_LABEL } from "../lib/format";
import { formatClock } from "../lib/timeline";
import type { VideoRow } from "../types";

type Filter = "all" | "pending" | "approved" | "rejected";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Semua" },
  { key: "pending", label: "Menunggu" },
  { key: "approved", label: "Disetujui" },
  { key: "rejected", label: "Ditolak" },
];

function matches(row: VideoRow, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "pending") return row.status !== "approved" && row.status !== "rejected";
  return row.status === f;
}

export default function VideoList() {
  const [rows, setRows] = useState<VideoRow[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await listVideos();
      setRows(data);
      setError("");
      setPending((p) => p.filter((id) => !data.some((r) => r.video_id === id)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal memuat daftar.");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // Setelah unggah, periksa daftar tiap 8 detik sampai hasil pemrosesan muncul.
  useEffect(() => {
    if (pending.length === 0) return;
    const t = setInterval(() => void refresh(), 8000);
    return () => clearInterval(t);
  }, [pending.length, refresh]);

  const stats = useMemo(() => {
    const all = rows ?? [];
    return {
      waiting: all.filter((r) => r.status === "ai_done").length,
      attention: all.filter((r) => r.status === "ai_done" && r.summary?.needs_attention).length,
      approved: all.filter((r) => r.status === "approved").length,
      rejected: all.filter((r) => r.status === "rejected").length,
    };
  }, [rows]);

  const shown = (rows ?? []).filter(
    (r) =>
      matches(r, filter) &&
      (query.trim() === "" ||
        `${r.video_id} ${r.scenario_id}`.toLowerCase().includes(query.trim().toLowerCase())),
  );

  return (
    <>
      <h1 className="page-title">Video untuk direview</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Pre-screening AI menandai bagian yang perlu dicek. Keputusan akhir tetap di tangan reviewer.
      </p>

      <div className="tiles">
        <div className="card tile"><div className="n num">{stats.waiting}</div><div className="l">Menunggu review</div></div>
        <div className="card tile"><div className="n num">{stats.attention}</div><div className="l">Perlu perhatian</div></div>
        <div className="card tile"><div className="n num">{stats.approved}</div><div className="l">Disetujui</div></div>
        <div className="card tile"><div className="n num">{stats.rejected}</div><div className="l">Ditolak</div></div>
      </div>

      {pending.length > 0 && (
        <div className="banner" role="status">
          Video diunggah dan sedang diproses (sekitar 1 sampai 3 menit). Daftar diperbarui otomatis.
        </div>
      )}
      {error && <div className="banner banner-warn" role="alert">{error}</div>}

      <div className="toolbar">
        <div className="tabs" role="group" aria-label="Filter status">
          {FILTERS.map((f) => (
            <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}</button>
          ))}
        </div>
        <input className="grow" type="text" placeholder="Cari video atau skenario…" value={query}
          aria-label="Cari" onChange={(e) => setQuery(e.target.value)} />
        <button className="btn" onClick={() => void refresh()}>Segarkan</button>
        <button className="btn btn-primary" onClick={() => setUploading(true)}>Unggah video</button>
      </div>

      <div className="card table-wrap">
        {rows === null && !error ? (
          <div className="empty">Memuat…</div>
        ) : shown.length === 0 ? (
          <div className="empty">{rows && rows.length > 0 ? "Tidak ada video yang cocok." : "Belum ada video. Unggah video pertama Anda."}</div>
        ) : (
          <table className="videos">
            <thead>
              <tr>
                <th>Video</th>
                <th className="hide-sm">Peran</th>
                <th>Status</th>
                <th>Hasil AI</th>
                <th className="hide-sm">Diproses</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.video_id} tabIndex={0}
                  onClick={() => { window.location.hash = `#/video/${encodeURIComponent(r.video_id)}`; }}
                  onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `#/video/${encodeURIComponent(r.video_id)}`; }}>
                  <td>
                    <div className="row-title">{humanizeSlug(r.scenario_id)}</div>
                    <div className="muted num" style={{ fontSize: "0.8rem" }}>{r.video_id} · {formatClock(r.duration_sec)}</div>
                  </td>
                  <td className="hide-sm">{r.role ? ROLE_LABEL[r.role] : "-"}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td>
                    {r.summary ? (
                      <span className="counts num">
                        <span className="badge badge-pass" title="Lolos">✓ {r.summary.passed}</span>
                        <span className="badge badge-fail" title="Gagal">✕ {r.summary.failed}</span>
                        <span className="badge badge-uncertain" title="Ragu">? {r.summary.uncertain}</span>
                        {r.status === "ai_done" && r.summary.needs_attention && <span className="badge badge-watch">Perlu perhatian</span>}
                      </span>
                    ) : "-"}
                  </td>
                  <td className="hide-sm muted">{formatDateTime(r.processed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {uploading && (
        <UploadDialog
          onClose={() => setUploading(false)}
          onUploaded={(id) => { setUploading(false); setPending((p) => [...p, id]); }}
        />
      )}
    </>
  );
}
