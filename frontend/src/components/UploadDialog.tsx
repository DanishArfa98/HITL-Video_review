import { FormEvent, useState } from "react";
import { uploadVideo } from "../api";
import { ROLE_LABEL } from "../lib/format";
import type { Role } from "../types";

interface Props {
  onClose: () => void;
  onUploaded: (videoId: string) => void;
}

const MAX_BYTES = 500 * 1024 * 1024;

export default function UploadDialog({ onClose, onUploaded }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!file) return setError("Pilih file video (.mp4).");
    if (!file.name.toLowerCase().endsWith(".mp4")) return setError("Hanya file .mp4 yang didukung.");
    if (file.size > MAX_BYTES) return setError("Ukuran video melebihi 500 MB.");
    if (title.trim().length < 5) return setError("Judul skenario terlalu pendek.");
    if (!role) return setError("Pilih peran petugas yang tampil di video.");
    setBusy(true);
    try {
      const id = await uploadVideo(file, title.trim(), role, setProgress);
      onUploaded(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unggah gagal.");
      setBusy(false);
    }
  }

  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <form className="card dialog" role="dialog" aria-modal="true" aria-labelledby="up-heading" onSubmit={submit}>
        <h2 id="up-heading">Unggah video</h2>
        <div className="field">
          <label htmlFor="up-file">Video (.mp4)</label>
          <input id="up-file" type="file" accept="video/mp4,.mp4" disabled={busy}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="field">
          <label htmlFor="up-title">Judul skenario</label>
          <input id="up-title" type="text" value={title} disabled={busy}
            placeholder="mis. Satpam mengarahkan nasabah setor tunai ke teller"
            onChange={(e) => setTitle(e.target.value)} />
          <span className="hint">
            Checklist dibuat dari judul ini, jadi tulis sesuai isi video. Judul yang tidak cocok
            membuat item skenario dinilai gagal.
          </span>
        </div>
        <div className="field">
          <label htmlFor="up-role">Peran petugas</label>
          <select id="up-role" value={role} disabled={busy} onChange={(e) => setRole(e.target.value as Role | "")}>
            <option value="">Pilih peran…</option>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
              <option key={r} value={r}>{ROLE_LABEL[r]}</option>
            ))}
          </select>
        </div>
        {busy && (
          <div className="field" aria-live="polite">
            <div className="progress"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            <span className="hint num">Mengunggah {Math.round(progress * 100)}%</span>
          </div>
        )}
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Batal</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Mengunggah…" : "Unggah"}
          </button>
        </div>
      </form>
    </div>
  );
}
