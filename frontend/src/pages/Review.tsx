import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getVideo, submitReview } from "../api";
import { StatusBadge } from "../components/Badges";
import Heatmap from "../components/Heatmap";
import ItemCard from "../components/ItemCard";
import { formatDateTime, humanizeSlug, ROLE_LABEL } from "../lib/format";
import {
  buildOverrides,
  buildTemplateEdits,
  nextScenarioId,
  partitionItems,
  unreviewedIds,
  type Decision,
  type Decisions,
} from "../lib/review";
import { desiredRate, formatClock, stateAt } from "../lib/timeline";
import type { ChecklistItem, Modality, ReviewSubmission, Severity, VideoDetail } from "../types";

function readLocal(key: string): string {
  try { return localStorage.getItem(key) ?? ""; } catch { return ""; }
}
function writeLocal(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* diabaikan */ }
}
const errMsg = (e: unknown) => (e instanceof Error ? e.message : "Terjadi kesalahan.");

export default function Review({ videoId }: { videoId: string }) {
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [error, setError] = useState("");
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [origItems, setOrigItems] = useState<ChecklistItem[]>([]);
  const [decisions, setDecisions] = useState<Decisions>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const [auto, setAuto] = useState(true);
  const [fast, setFast] = useState(1.5);
  const [manual, setManual] = useState(1);
  const [reviewer, setReviewer] = useState(() => readLocal("vr_reviewer"));
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [adding, setAdding] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  const load = useCallback(async () => {
    try {
      const d = await getVideo(videoId);
      setDetail(d);
      const tpl = d.template?.items ?? [];
      setItems(tpl);
      setOrigItems(tpl);
      const next: Decisions = {};
      for (const r of d.result.results) {
        const ov = d.review?.overrides.find((o) => o.item_id === r.item_id);
        if (ov) next[r.item_id] = { human: ov.human_verdict, note: ov.note };
        else if (d.review && r.verdict !== "pass") next[r.item_id] = { human: null, note: "" };
      }
      setDecisions(next);
      setError("");
    } catch (e) {
      setError(errMsg(e));
    }
  }, [videoId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const timeline = detail?.result.timeline ?? [];
  const duration = detail?.result.meta.duration_sec ?? 0;

  const applyRate = useCallback((t: number) => {
    const v = videoRef.current;
    if (!v) return;
    const rate = desiredRate(stateAt(timeline, t), { auto, fast, manual });
    if (v.playbackRate !== rate) v.playbackRate = rate;
  }, [timeline, auto, fast, manual]);

  useEffect(() => {
    const v = videoRef.current;
    if (v) applyRate(v.currentTime);
  }, [applyRate, detail]);

  const seekTo = useCallback((sec: number) => {
    const v = videoRef.current;
    if (!v) return;
    const max = Number.isFinite(v.duration) && v.duration > 0 ? v.duration : sec;
    v.currentTime = Math.max(0, Math.min(sec, max));
    setNow(v.currentTime);
    applyRate(v.currentTime);
    void v.play().catch(() => {});
  }, [applyRate]);

  // Pintasan: K putar/jeda, J mundur 5 dtk, L maju 5 dtk (diabaikan saat mengetik).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      const v = videoRef.current;
      if (!v) return;
      const k = e.key.toLowerCase();
      if (k === "k") { if (v.paused) void v.play().catch(() => {}); else v.pause(); }
      if (k === "j") v.currentTime = Math.max(0, v.currentTime - 5);
      if (k === "l") v.currentTime = v.currentTime + 5;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const parts = useMemo(() => partitionItems(detail?.result.results ?? []), [detail]);
  const defOf = (id: string) => items.find((i) => i.id === id);
  const results = detail?.result.results ?? [];
  const summary = detail?.result.summary ?? null;
  const zone = stateAt(timeline, now);
  const addedItems = items.filter((i) => !origItems.some((o) => o.id === i.id));

  async function submit(decision: "approved" | "rejected") {
    if (!detail) return;
    if (!reviewer.trim()) return setToast("Isi nama reviewer terlebih dahulu.");
    const short = items.find((i) => i.description.trim().length < 3);
    if (short) return setToast(`Deskripsi item ${short.id} terlalu pendek.`);
    const open = unreviewedIds(results, decisions);
    if (open.length > 0 &&
        !window.confirm(`Masih ada ${open.length} item gagal atau ragu yang belum Anda tinjau (${open.join(", ")}). Tetap lanjutkan?`)) return;
    setBusy(true);
    try {
      const nowIso = new Date().toISOString();
      const body: ReviewSubmission = {
        video_id: videoId,
        reviewer: reviewer.trim(),
        overrides: buildOverrides(results, decisions, nowIso),
        final_decision: decision,
        decided_at: nowIso,
        template_edits: detail.template
          ? buildTemplateEdits(origItems, items.map((i) => ({ ...i, description: i.description.trim() })))
          : [],
      };
      await submitReview(videoId, body);
      writeLocal("vr_reviewer", reviewer.trim());
      setToast(decision === "approved" ? "Video disetujui." : "Video ditolak.");
      await load();
    } catch (e) {
      setToast(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) {
    return (
      <>
        <a className="btn btn-sm" href="#/">← Daftar</a>
        <div className="banner banner-warn" role="alert" style={{ marginTop: 12 }}>{error}</div>
      </>
    );
  }
  if (!detail) return <div className="empty">Memuat…</div>;

  const { result, review } = detail;
  const status = review ? review.final_decision : result.status;
  const rateNow = desiredRate(zone, { auto, fast, manual });

  const card = (id: string) => {
    const r = results.find((x) => x.item_id === id)!;
    return (
      <ItemCard key={id} result={r} def={defOf(id)} decision={decisions[id]}
        open={openId === id} canEdit={Boolean(detail.template)}
        onToggle={() => setOpenId(openId === id ? null : id)}
        onDecision={(d: Decision | undefined) =>
          setDecisions((prev) => { const n = { ...prev }; if (d) n[id] = d; else delete n[id]; return n; })}
        onSeek={seekTo}
        onEdit={(it) => setItems((prev) => prev.map((x) => (x.id === it.id ? it : x)))}
        onRemove={() => { setItems((prev) => prev.filter((x) => x.id !== id)); setOpenId(null); }} />
    );
  };

  return (
    <>
      <div className="crumbs">
        <a className="btn btn-sm" href="#/">← Daftar</a>
        <StatusBadge status={status} />
      </div>
      <h1 className="page-title">{humanizeSlug(result.scenario_id)}</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        {result.role ? ROLE_LABEL[result.role] : "Peran tidak diketahui"} · diproses {formatDateTime(result.meta.processed_at)} ·
        durasi {formatClock(duration)} · template v{result.template_version}
      </p>

      {summary && summary.needs_attention ? (
        <div className="banner banner-warn" role="status">
          <strong>{summary.failed + summary.uncertain} item perlu dicek</strong> ({summary.failed} gagal, {summary.uncertain} ragu).
          {summary.unlocated_item_ids.length > 0 && (
            <> Item <strong>{summary.unlocated_item_ids.join(", ")}</strong> tidak punya momen waktu sehingga tidak tampak di peta;
              periksa lewat daftar checklist.</>
          )}
        </div>
      ) : (
        <div className="banner" role="status">
          AI tidak menandai masalah. Tetap lirik sekilas bagian hijau: hijau berarti AI tidak menemukan masalah, bukan jaminan tidak ada.
        </div>
      )}

      <div className="review">
        <div className="stack">
          <div className="card">
            <div className="video-box">
              {detail.video_url ? (
                <video
                  ref={videoRef}
                  src={detail.video_url}
                  controls
                  preload="metadata"
                  onTimeUpdate={(e) => { setNow(e.currentTarget.currentTime); applyRate(e.currentTarget.currentTime); }}
                  onLoadedMetadata={(e) => applyRate(e.currentTarget.currentTime)}
                />
              ) : (
                <div className="video-empty">
                  Tautan putar video tidak tersedia untuk hasil ini. Unggah ulang video agar lokasi videonya tersimpan.
                </div>
              )}
            </div>

            <Heatmap timeline={timeline} duration={duration || 1} current={now} onSeek={seekTo} />
            <div className="legend">
              <span><i style={{ background: "var(--ok-bar)" }} />Aman</span>
              <span><i style={{ background: "var(--bad-bar)" }} />Bermasalah</span>
              <span><i style={{ background: "var(--warn-bar)" }} />Ragu</span>
              <span className="num">{formatClock(now)} / {formatClock(duration)}</span>
            </div>

            <div className="controls">
              <div className="seg" role="group" aria-label="Kecepatan di zona hijau">
                {[1, 1.5, 2].map((r) => (
                  <button key={r} aria-pressed={(auto ? fast : manual) === r}
                    onClick={() => (auto ? setFast(r) : setManual(r))}>{r}×</button>
                ))}
              </div>
              <label className="check-row">
                <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
                Otomatis: cepat di zona hijau, 1× di zona merah/kuning
              </label>
            </div>
            <p className="mode muted num" style={{ marginBottom: 0 }} aria-live="polite">
              Sekarang: {zone === "clear" ? "zona hijau" : zone === "flagged" ? "zona merah" : "zona kuning"} · {rateNow}×
              · Pintasan: K putar/jeda, J/L ±5 dtk
            </p>
          </div>

          <div className="card final">
            <div className="section-title">Keputusan akhir</div>
            {review && (
              <p className="muted" style={{ marginTop: 0 }}>
                Tersimpan: <strong>{review.final_decision === "approved" ? "Disetujui" : "Ditolak"}</strong> oleh {review.reviewer},{" "}
                {formatDateTime(review.decided_at)}. Anda bisa mengubahnya.
              </p>
            )}
            <div className="field">
              <label htmlFor="reviewer">Nama reviewer</label>
              <input id="reviewer" type="text" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </div>
            <div className="row">
              <button className="btn btn-ok" disabled={busy} onClick={() => void submit("approved")}>Setujui video</button>
              <button className="btn btn-bad" disabled={busy} onClick={() => void submit("rejected")}>Tolak video</button>
            </div>
          </div>
        </div>

        <aside className="card checklist" aria-label="Checklist">
          <div className="section-title">Perlu dicek ({parts.check.length})</div>
          {parts.check.length === 0 && <p className="muted">Tidak ada item yang perlu dicek.</p>}
          {parts.check.map((r) => card(r.item_id))}

          <details style={{ marginTop: 14 }}>
            <summary>Lolos ({parts.ok.length})</summary>
            {parts.ok.map((r) => card(r.item_id))}
          </details>

          {detail.template && (
            <div style={{ marginTop: 14 }}>
              <div className="section-title">Perubahan checklist</div>
              {addedItems.map((i) => (
                <div key={i.id} className="item is-pass" style={{ padding: 10 }}>
                  <strong>{i.id}</strong> {i.description}{" "}
                  <button className="btn btn-sm btn-ghost" onClick={() => setItems((p) => p.filter((x) => x.id !== i.id))}>Hapus</button>
                </div>
              ))}
              {adding ? (
                <AddItemForm
                  onCancel={() => setAdding(false)}
                  onAdd={(draft) => {
                    setItems((p) => [...p, { ...draft, id: nextScenarioId(p), source: "scenario", enabled: true }]);
                    setAdding(false);
                  }}
                />
              ) : (
                <button className="btn btn-sm" onClick={() => setAdding(true)}>+ Tambah item checklist</button>
              )}
            </div>
          )}
        </aside>
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
}

function AddItemForm({ onAdd, onCancel }: {
  onAdd: (item: Omit<ChecklistItem, "id" | "source" | "enabled">) => void;
  onCancel: () => void;
}) {
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("Skenario");
  const [audio, setAudio] = useState(true);
  const [vision, setVision] = useState(false);
  const [severity, setSeverity] = useState<Severity>("major");
  const modalities: Modality[] = [...(audio ? (["audio"] as const) : []), ...(vision ? (["vision"] as const) : [])];
  const valid = description.trim().length >= 3 && modalities.length > 0;

  return (
    <div className="edit-box">
      <div className="field">
        <label htmlFor="new-desc">Deskripsi item baru</label>
        <textarea id="new-desc" value={description} onChange={(e) => setDescription(e.target.value)}
          placeholder="Satu kalimat perilaku yang bisa dibuktikan dari rekaman" />
      </div>
      <div className="field">
        <label htmlFor="new-cat">Kategori</label>
        <input id="new-cat" type="text" value={category} onChange={(e) => setCategory(e.target.value)} />
      </div>
      <div className="check-row">
        <input id="new-audio" type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} />
        <label htmlFor="new-audio">Dinilai dari ucapan</label>
        <input id="new-vision" type="checkbox" checked={vision} onChange={(e) => setVision(e.target.checked)} />
        <label htmlFor="new-vision">Dinilai dari gambar</label>
      </div>
      <div className="field">
        <label htmlFor="new-sev">Tingkat keparahan</label>
        <select id="new-sev" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
          <option value="minor">Ringan</option>
          <option value="major">Sedang</option>
          <option value="critical">Kritis</option>
        </select>
      </div>
      <div className="actions">
        <button className="btn btn-sm" onClick={onCancel}>Batal</button>
        <button className="btn btn-sm btn-primary" disabled={!valid}
          onClick={() => onAdd({ category: category.trim() || "Skenario", description: description.trim(), modalities, severity })}>
          Tambah
        </button>
      </div>
    </div>
  );
}
