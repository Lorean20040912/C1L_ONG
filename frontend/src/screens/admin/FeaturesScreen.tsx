import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { day, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useProfile } from "../../shell/profile";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "./Messages";

interface FeatureInfo {
  code: string;
  name: string;
}
interface OrgFeature {
  id: string;
  feature_code: string;
  name: string;
  enabled_from: string;
  enabled_to: string | null;
}

// metoda de evidență (dublă / simplă) nu se comută de aici
const FIXED = new Set(["double_entry", "single_entry"]);

/** Administrare → Funcționalitate (ca în 1C): pornirea / oprirea funcționalităților de la o dată. */
export function FeaturesScreen() {
  const { orgId, role } = useShell();
  const profile = useProfile();
  const [catalog, setCatalog] = useState<FeatureInfo[]>([]);
  const [rows, setRows] = useState<OrgFeature[] | null>(null);
  const [date, setDate] = useState(today());
  const { busy, error, info, run } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/features`;

  const load = useCallback(() => api<OrgFeature[]>(base).then(setRows), [base]);
  useEffect(() => {
    api<FeatureInfo[]>("/features").then(setCatalog);
    load();
  }, [load]);

  const open = (code: string) => rows?.find((r) => r.feature_code === code && r.enabled_to === null);
  const after = async (msg: string) => {
    await load();
    profile.refresh();
    return msg;
  };

  const enable = (code: string) =>
    run(async () => {
      await api(base, { method: "POST", body: { feature_code: code, enabled_from: date } });
      return after(`Funcționalitatea e pornită de la ${day(date)}.`);
    });
  const disable = (code: string) =>
    run(async () => {
      await api(`${base}/${code}/disable`, { method: "POST", body: { enabled_to: date } });
      return after(`Funcționalitatea e oprită la ${day(date)}.`);
    });

  return (
    <>
      <h1>Funcționalitate</h1>
      <ReadOnlyNote show={!editable} what="funcționalitățile le schimbă contabilul-șef" />
      <Messages error={error} info={info} />
      {editable && (
        <div className="form">
          <label htmlFor="f-date">Data de la care se aplică</label>
          <input id="f-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      )}
      <table className="grid">
        <thead>
          <tr>
            <th>Funcționalitate</th>
            <th>Stare</th>
            <th>Perioade</th>
            {editable && <th />}
          </tr>
        </thead>
        <tbody>
          {catalog.map((f) => {
            const current = open(f.code);
            const periods = (rows ?? []).filter((r) => r.feature_code === f.code);
            return (
              <tr key={f.code}>
                <td>{f.name}</td>
                <td>{current ? <span className="ok">pornită</span> : <span className="muted">oprită</span>}</td>
                <td>
                  {periods.map((p) => `${day(p.enabled_from)} – ${p.enabled_to ? day(p.enabled_to) : "…"}`).join("; ") || "—"}
                </td>
                {editable && (
                  <td>
                    {!FIXED.has(f.code) &&
                      (current ? (
                        <button className="b" disabled={busy} onClick={() => disable(f.code)}>
                          Oprește
                        </button>
                      ) : (
                        <button className="b primary" disabled={busy} onClick={() => enable(f.code)}>
                          Pornește
                        </button>
                      ))}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
