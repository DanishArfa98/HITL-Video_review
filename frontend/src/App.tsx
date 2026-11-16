import { useCallback, useEffect, useState } from "react";
import { clearSession, getSession, setUnauthorizedHandler } from "./api";
import Login from "./pages/Login";
import Review from "./pages/Review";
import VideoList from "./pages/VideoList";

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  const [authed, setAuthed] = useState(() => Boolean(getSession().token));
  const hash = useHash();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      setAuthed(false);
    });
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setAuthed(false);
  }, []);

  if (!authed) return <Login onLoggedIn={() => setAuthed(true)} />;

  const match = /^#\/video\/(.+)$/.exec(hash);
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/">
          Review<span>Video</span>
        </a>
        <button className="btn btn-sm" onClick={logout}>
          Keluar
        </button>
      </header>
      <main className="page">
        {match ? <Review key={match[1]} videoId={decodeURIComponent(match[1])} /> : <VideoList />}
      </main>
    </>
  );
}
