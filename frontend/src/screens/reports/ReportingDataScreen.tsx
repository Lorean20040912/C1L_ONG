import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client";
import { day } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

type Profile = Record<(typeof FIELDS)[number][0], string | null>;

const FIELDS = [
  ["ngo_category", "Categoria ONG17 (A–G)"],
  ["caem", "Cod CAEM"],
  ["sfs_office", "Subdiviziunea SFS"],
  ["cuiio", "Cod CUIIO (5-CON)"],
  ["cfoj", "CFOJ"],
  ["cfp", "CFP"],
  ["cuatm", "CUATM"],
  ["director_name", "Conducătorul"],
  ["chief_accountant_name", "Contabilul-șef (executor)"],
] as const;

const CATEGORIES: Record<string, string> = {
  A: "A — Asociație obștească",
  B: "B — Fundație",
  C: "C — Organizație filantropică",
  D: "D — Culte religioase",
  E: "E — Partide politice",
  F: "F — Publicații periodice / agenții de presă",
  G: "G — Alte ONG",
};

interface Stats {
  id: string;
  period_end: string;
  members_count: number | null;
  volunteers_count: number | null;
}

/** Datele pentru antetul rapoartelor (ONG17, 5-CON) și statistica ONG (membri, voluntari). */
export function ReportingDataScreen() {
  const { orgId, role } = useShell();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [stats, setStats] = useState<Stats[]>([]);
  const [periodEnd, setPeriodEnd] = useState("");
  const [members, setMembers] = useState("");
  const [volunteers, setVolunteers] = useState("");
  const { busy, error, info, run } = useAction();
  const base = `/organizations/${orgId}`;

  const loadStats = () => api<Stats[]>(`${base}/organization-stats`).then(setStats);
  useEffect(() => {
    api<Profile>(`${base}/reporting-profile`).then(setProfile).catch(() => setProfile(null));
    loadStats().catch(() => setStats([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  const saveProfile = () =>
    profile &&
    run(async () => {
      setProfile(await api<Profile>(`${base}/reporting-profile`, { method: "PUT", body: profile }));
      return "Datele au fost salvate.";
    });

  const saveStats = () =>
    run(async () => {
      if (!periodEnd) throw new Error("Alegeți data (ultima zi a trimestrului)");
      const num = (v: string) => (v.trim() === "" ? null : Number(v));
      await api(`${base}/organization-stats`, {
        method: "PUT",
        body: { period_end: periodEnd, members_count: num(members), volunteers_count: num(volunteers) },
      });
      await loadStats();
      setMembers("");
      setVolunteers("");
      return "Statistica a fost salvată.";
    });

  const editProfile = can(role, ADMIN_ROLES);

  return (
    <>
      <h1>Date pentru rapoarte</h1>
      <Messages error={error} info={info} />
      {profile && (
        <section>
          <h2>Antetul rapoartelor</h2>
          <div className="form">
            {FIELDS.map(([key, label]) => (
              <Fragment key={key}>
                <label htmlFor={`rp-${key}`}>
                  {label}
                </label>
                {key === "ngo_category" ? (
                  <select id={`rp-${key}`} value={profile[key] ?? ""} disabled={!editProfile} onChange={(e) => setProfile({ ...profile, [key]: e.target.value || null })}>
                    <option value="">—</option>
                    {Object.entries(CATEGORIES).map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input id={`rp-${key}`} value={profile[key] ?? ""} disabled={!editProfile} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />
                )}
              </Fragment>
            ))}
          </div>
          {editProfile && (
            <div className="bar">
              <button className="b primary" onClick={saveProfile} disabled={busy}>
                Salvează
              </button>
            </div>
          )}
        </section>
      )}
      <section>
        <h2>Statistica ONG (5-CON, rândurile 300 și 320)</h2>
        <table className="grid">
          <thead>
            <tr>
              <th>La data</th>
              <th className="num">Membri</th>
              <th className="num">Voluntari</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((s) => (
              <tr key={s.id}>
                <td>{day(s.period_end)}</td>
                <td className="num">{s.members_count ?? ""}</td>
                <td className="num">{s.volunteers_count ?? ""}</td>
              </tr>
            ))}
            {stats.length === 0 && (
              <tr>
                <td colSpan={3} className="muted">
                  Nu sunt date.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {can(role, POSTING_ROLES) && (
          <div className="bar">
            <input className="b" type="date" aria-label="La data" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
            <input className="b" aria-label="Membri" placeholder="membri" value={members} onChange={(e) => setMembers(e.target.value)} style={{ width: 90 }} />
            <input className="b" aria-label="Voluntari" placeholder="voluntari" value={volunteers} onChange={(e) => setVolunteers(e.target.value)} style={{ width: 90 }} />
            <button className="b" onClick={saveStats} disabled={busy}>
              Salvează statistica
            </button>
          </div>
        )}
      </section>
    </>
  );
}
