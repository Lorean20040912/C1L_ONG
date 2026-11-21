import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { user, login, login2fa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const target = (location.state as { from?: string } | null)?.from ?? "/";
  if (user) return <Navigate to={target} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (challenge) {
        await login2fa(challenge, code);
      } else {
        const next = await login(email, password);
        if (next) {
          setChallenge(next);
          return;
        }
      }
      navigate(target, { replace: true });
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
        <h1>Intrare în program</h1>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {challenge ? (
          <div className="field">
            <label htmlFor="code">Cod de autentificare (sau cod de rezervă)</label>
            <input
              id="code"
              inputMode="text"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              autoFocus
            />
          </div>
        ) : (
          <>
        <div className="field">
          <label htmlFor="email">E-mail</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="password">Parola</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
          </>
        )}
        <div className="bar">
          <button className="b primary" type="submit" disabled={busy}>
            {busy ? "Se verifică…" : "Intră"}
          </button>
        </div>
      </form>
    </div>
  );
}
