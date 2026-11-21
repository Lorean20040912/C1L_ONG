import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAction } from "../../lib/useAction";
import { Messages } from "./Messages";

interface TwoFAStatus {
  enabled: boolean;
  backup_codes_left: number;
}
interface Setup {
  secret: string;
  otpauth_uri: string;
}

/** Securitatea contului curent: schimbarea parolei și autentificarea în doi pași (TOTP). */
export function SecurityScreen() {
  const [status, setStatus] = useState<TwoFAStatus | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const twofa = useAction();
  const pwd = useAction();

  const load = useCallback(() => api<TwoFAStatus>("/auth/2fa").then(setStatus), []);
  useEffect(() => {
    load();
  }, [load]);

  const start = () =>
    twofa.run(async () => {
      setSetup(await api<Setup>("/auth/2fa/setup", { method: "POST" }));
      setBackupCodes(null);
    });

  const enable = () =>
    twofa.run(async () => {
      const res = await api<{ backup_codes: string[] }>("/auth/2fa/enable", { method: "POST", body: { code } });
      setBackupCodes(res.backup_codes);
      setSetup(null);
      setCode("");
      await load();
      return "Autentificarea în doi pași este activă. Păstrați codurile de rezervă într-un loc sigur.";
    });

  const disable = () =>
    twofa.run(async () => {
      await api("/auth/2fa/disable", { method: "POST", body: { password, code } });
      setPassword("");
      setCode("");
      setBackupCodes(null);
      await load();
      return "Autentificarea în doi pași a fost dezactivată.";
    });

  const regenerate = () =>
    twofa.run(async () => {
      const res = await api<{ backup_codes: string[] }>("/auth/2fa/backup-codes", { method: "POST", body: { password, code } });
      setBackupCodes(res.backup_codes);
      setPassword("");
      setCode("");
      await load();
      return "Codurile de rezervă anterioare nu mai sunt valabile.";
    });

  const changePassword = () =>
    pwd.run(async () => {
      if (next !== repeat) throw new Error("Parolele noi nu coincid");
      await api("/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      setRepeat("");
      return "Parola a fost schimbată.";
    });

  return (
    <>
      <h1>Securitatea contului</h1>

      <h2>Autentificare în doi pași (2FA)</h2>
      <Messages error={twofa.error} info={twofa.info} />
      {status && !status.enabled && !setup && (
        <>
          <div className="hint">Contul se protejează cu un cod din aplicația de autentificare (Google Authenticator, Aegis etc.).</div>
          <div className="bar">
            <button className="b primary" onClick={start} disabled={twofa.busy}>
              Activează 2FA
            </button>
          </div>
        </>
      )}
      {setup && (
        <div className="panel">
          <p>Adăugați în aplicație contul cu cheia de mai jos, apoi introduceți codul afișat de ea.</p>
          <div className="field">
            <label>Cheia secretă</label>
            <input readOnly value={setup.secret} onFocus={(e) => e.target.select()} />
          </div>
          <div className="field">
            <label>Adresa otpauth (pentru aplicațiile care o acceptă)</label>
            <input readOnly value={setup.otpauth_uri} onFocus={(e) => e.target.select()} />
          </div>
          <div className="field">
            <label htmlFor="sec-code">Cod din aplicație</label>
            <input id="sec-code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          </div>
          <div className="bar">
            <button className="b primary" onClick={enable} disabled={twofa.busy || code.trim().length < 6}>
              Confirmă și activează
            </button>
            <button className="b" onClick={() => setSetup(null)}>
              Renunță
            </button>
          </div>
        </div>
      )}
      {status?.enabled && (
        <div className="panel">
          <p>
            2FA este <b className="ok">activ</b>. Coduri de rezervă rămase: {status.backup_codes_left}.
          </p>
          <div className="field">
            <label htmlFor="sec-pw2">Parola curentă</label>
            <input id="sec-pw2" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="sec-code2">Cod din aplicație (sau cod de rezervă)</label>
            <input id="sec-code2" value={code} onChange={(e) => setCode(e.target.value)} />
          </div>
          <div className="bar">
            <button className="b" onClick={regenerate} disabled={twofa.busy || !password || !code}>
              Coduri de rezervă noi
            </button>
            <button className="b" onClick={disable} disabled={twofa.busy || !password || !code}>
              Dezactivează 2FA
            </button>
          </div>
        </div>
      )}
      {backupCodes && (
        <div className="panel">
          <b>Coduri de rezervă (se afișează o singură dată; fiecare se poate folosi o dată):</b>
          <pre>{backupCodes.join("\n")}</pre>
        </div>
      )}

      <h2>Schimbarea parolei</h2>
      <Messages error={pwd.error} info={pwd.info} />
      <div className="panel">
        <div className="field">
          <label htmlFor="pw-cur">Parola curentă</label>
          <input id="pw-cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pw-new">Parola nouă (minimum 8 caractere)</label>
          <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pw-rep">Repetați parola nouă</label>
          <input id="pw-rep" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        </div>
        <div className="bar">
          <button className="b primary" onClick={changePassword} disabled={pwd.busy || !current || !next}>
            Schimbă parola
          </button>
        </div>
      </div>
    </>
  );
}
