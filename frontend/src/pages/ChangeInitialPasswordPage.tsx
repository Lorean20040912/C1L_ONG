import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** Prima intrare cu parola inițială dată de administrator: schimbarea ei e obligatorie. */
export function ChangeInitialPasswordPage() {
  const { logout, refreshUser } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError("Parolele noi nu coincid");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      await refreshUser();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-top">
        <span className="logo">
          Conta<b>Hub</b>
        </span>
      </div>
      <form className="panel" onSubmit={submit}>
        <h1>Schimbați parola</h1>
        <p className="muted">Contul a fost creat cu o parolă inițială. Alegeți o parolă proprie (minimum 8 caractere) pentru a continua.</p>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="ip-cur">Parola inițială</label>
          <input id="ip-cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ip-new">Parola nouă</label>
          <input id="ip-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ip-rep">Repetă parola nouă</label>
          <input id="ip-rep" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        </div>
        <button className="b primary" type="submit" disabled={busy || !current || !next}>
          Schimbă parola
        </button>{" "}
        <button className="b" type="button" onClick={logout}>
          Ieșire
        </button>
      </form>
    </div>
  );
}
