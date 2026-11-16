import type { ChecklistItem, ItemResult, Severity } from "../types";
import { effectiveVerdict, LOW_CONFIDENCE, type Decision } from "../lib/review";
import { formatClock, frameSecond, seekTargetFor } from "../lib/timeline";
import { VerdictBadge } from "./Badges";

interface Props {
  result: ItemResult;
  def?: ChecklistItem;
  decision?: Decision;
  open: boolean;
  canEdit: boolean;
  onToggle: () => void;
  onDecision: (d: Decision | undefined) => void;
  onSeek: (sec: number) => void;
  onEdit: (item: ChecklistItem) => void;
  onRemove: () => void;
}

const SEVERITY_LABEL: Record<Severity, string> = { minor: "Ringan", major: "Sedang", critical: "Kritis" };

export default function ItemCard({ result, def, decision, open, canEdit, onToggle, onDecision, onSeek, onEdit, onRemove }: Props) {
  const lowPass = result.verdict === "pass" && result.confidence < LOW_CONFIDENCE;
  const final = effectiveVerdict(result, decision);
  const overridden = Boolean(decision?.human && decision.human !== result.verdict);
  const target = seekTargetFor(result);
  const noMoment = result.verdict !== "pass" && result.moment_sec == null && result.flagged_ranges.length === 0;
  const tone = lowPass ? "watch" : result.verdict;
  const disabled = def ? !def.enabled : false;

  const choose = (human: "pass" | "fail" | null) =>
    onDecision({ human, note: decision?.note ?? "" });

  return (
    <div className={`item is-${tone}`} data-item={result.item_id}>
      <button
        className="item-head"
        aria-expanded={open}
        onClick={() => {
          onToggle();
          if (target !== null) onSeek(target);
        }}
      >
        <span className="item-top">
          <span className="item-id">{result.item_id}</span>
          <VerdictBadge verdict={result.verdict} prefix="AI:" />
          {overridden && <span className="badge badge-muted">Anda: {final === "pass" ? "Lolos" : "Gagal"}</span>}
          {lowPass && <span className="badge badge-watch">Perlu dilirik</span>}
          {noMoment && <span className="badge badge-muted">Tanpa momen waktu</span>}
          {disabled && <span className="badge badge-muted">Nonaktif</span>}
          {result.moment_sec != null && <span className="muted num" style={{ fontSize: "0.8rem" }}>{formatClock(result.moment_sec)}</span>}
        </span>
        <span className={`item-desc ${disabled ? "off" : ""}`}>{def?.description ?? "(deskripsi item tidak tersedia)"}</span>
      </button>

      {open && (
        <div className="item-body">
          <p className="reason">{result.reason || "AI tidak memberi alasan."}</p>
          {lowPass && (
            <p className="muted reason">
              AI meloloskan item ini tetapi kurang yakin. Cek buktinya sebelum menyetujui.
            </p>
          )}

          {result.flagged_ranges.length > 0 && (
            <div className="chips">
              {result.flagged_ranges.map((r, i) => (
                <button key={i} className="chip" onClick={() => onSeek(r.start)}>
                  Periksa {formatClock(r.start)}–{formatClock(r.end)}
                </button>
              ))}
            </div>
          )}

          {result.evidence.transcript.length > 0 && (
            <div>
              <div className="section-title">Bukti ucapan</div>
              <div style={{ display: "grid", gap: 4 }}>
                {result.evidence.transcript.map((s, i) => (
                  <button key={i} className="quote" onClick={() => onSeek(s.start)}>
                    <span className="t">{formatClock(s.start)}</span>
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {result.evidence.frames.length > 0 && (
            <div>
              <div className="section-title">Bukti gambar (detik)</div>
              <div className="chips">
                {result.evidence.frames.map((f) => {
                  const sec = frameSecond(f);
                  return sec === null ? null : (
                    <button key={f} className="chip" onClick={() => onSeek(sec)}>{formatClock(sec)}</button>
                  );
                })}
              </div>
            </div>
          )}

          <div className="decide">
            <div className="section-title">Keputusan Anda</div>
            <div className="seg" role="group" aria-label={`Keputusan untuk ${result.item_id}`}>
              <button aria-pressed={decision !== undefined && decision.human === null} onClick={() => choose(null)}>Setuju AI</button>
              <button aria-pressed={decision?.human === "pass"} onClick={() => choose("pass")}>Lolos</button>
              <button aria-pressed={decision?.human === "fail"} onClick={() => choose("fail")}>Gagal</button>
            </div>
            {overridden && (
              <textarea
                aria-label={`Alasan override ${result.item_id}`}
                placeholder="Alasan override (opsional)"
                value={decision?.note ?? ""}
                onChange={(e) => onDecision({ human: decision!.human, note: e.target.value })}
              />
            )}
            {decision && (
              <div>
                <button className="btn btn-ghost btn-sm" onClick={() => onDecision(undefined)}>Reset keputusan</button>
              </div>
            )}
          </div>

          {canEdit && def && (
            <details className="edit-box">
              <summary>Edit item checklist</summary>
              <div className="field">
                <label htmlFor={`desc-${def.id}`}>Deskripsi</label>
                <textarea id={`desc-${def.id}`} value={def.description}
                  onChange={(e) => onEdit({ ...def, description: e.target.value })} />
              </div>
              <div className="check-row">
                <input id={`en-${def.id}`} type="checkbox" checked={def.enabled}
                  onChange={(e) => onEdit({ ...def, enabled: e.target.checked })} />
                <label htmlFor={`en-${def.id}`}>Aktif untuk video berikutnya</label>
              </div>
              <div className="field">
                <label htmlFor={`sev-${def.id}`}>Tingkat keparahan</label>
                <select id={`sev-${def.id}`} value={def.severity}
                  onChange={(e) => onEdit({ ...def, severity: e.target.value as Severity })}>
                  {(Object.keys(SEVERITY_LABEL) as Severity[]).map((s) => (
                    <option key={s} value={s}>{SEVERITY_LABEL[s]}</option>
                  ))}
                </select>
              </div>
              <p className="hint muted" style={{ margin: 0 }}>
                Perubahan checklist berlaku untuk video berikutnya dengan skenario yang sama,
                bukan untuk hasil video ini. Tersimpan saat Anda menyetujui atau menolak video.
              </p>
              {def.source === "scenario" && (
                <div><button className="btn btn-sm btn-bad" onClick={onRemove}>Hapus item dari checklist</button></div>
              )}
            </details>
          )}
        </div>
      )}
    </div>
  );
}
