import { FormEvent, useState } from "react";
import { getSession, saveSession, verifySession } from "../api";

export default function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const initial = getSession();
  const [url, setUrl] = useState(initial.url);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!url.trim() && !import.meta.env.VITE_API_URL) {
      setError("Isi alamat API terlebih dahulu.");
      return;
    }
    setBusy(true);
    try {
      await verifySession(url.trim() || (import.meta.env.VITE_API_URL as string), token.trim());
      saveSession(url, token);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal masuk.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>Review Video Training</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Masuk dengan alamat API dan token akses.
        </p>
        <div className="field">
          <label htmlFor="api-url">Alamat API</label>
          <input
            id="api-url"
            type="url"
            value={url}
            placeholder="https://xxxx.lambda-url.ap-southeast-1.on.aws"
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="token">Token</label>
          <input
            id="token"
            type="password"
            value={token}
            autoComplete="current-password"
            onChange={(e) => setToken(e.target.value)}
          />
        </div>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="btn btn-primary" type="submit" disabled={busy || !token.trim()}>
            {busy ? "Memeriksa…" : "Masuk"}
          </button>
        </div>
      </form>
    </div>
  );
}
