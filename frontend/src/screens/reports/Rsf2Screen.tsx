import { useState } from "react";
import { api, download } from "../../api/client";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

interface Preview {
  sections: { id: string; title: string; columns: string[]; rows: { code: string; label: string; values: number[] }[] }[];
  checks: { message: string; ok: boolean; severity: string; expected: number; actual: number }[];
  balanced: boolean;
}

const fmt = (n: number) => n.toLocaleString("ro-RO");

/** RSF2 — situațiile financiare anuale ale asociației obștești: XML din contabilitate, în formatul fiscului. */
export function Rsf2Screen() {
  const { orgId } = useShell();
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const { busy, error, info, run } = useAction();
  const [preview, setPreview] = useState<Preview | null>(null);
  const failed = preview?.checks.filter((c) => !c.ok) ?? [];

  return (
    <>
      <h1>RSF2 — situații financiare anuale</h1>
      <Messages error={error} info={info} />
      <section>
        <p>
          Bilanțul se calculează din soldurile conturilor la 1 ianuarie și 31 decembrie, rezultatul financiar din veniturile și cheltuielile anului.
          Rândurile care nu pot fi calculate rămân 0; verificați fișierul înainte de depunere.
        </p>
        <div className="form">
          <label htmlFor="rsf2-year">Anul</label>
          <input id="rsf2-year" type="number" min={2000} max={2100} value={year} onChange={(e) => setYear(Number(e.target.value))} />
        </div>
        <div className="bar">
          <button
            className="b primary"
            disabled={busy}
            onClick={() => run(() => download(`/organizations/${orgId}/reports/rsf2.xml?year=${year}`, `rsf2_${year}.xml`))}
          >
            Descarcă XML
          </button>
          <button
            className="b"
            disabled={busy}
            onClick={() => run(async () => setPreview(await api<Preview>(`/organizations/${orgId}/reports/rsf2/preview?year=${year}`)))}
          >
            Previzualizează rândurile
          </button>
        </div>
      </section>
      {preview && (
        <>
          {!preview.balanced && (
            <div role="alert" className="msg error">
              Bilanțul nu se închide (activ ≠ pasiv) sau o sumă de control nu se potrivește. Verificați conturile fără corespondență în
              formular înainte de depunere.
            </div>
          )}
          {preview.sections.map((sec) => (
            <section key={sec.id}>
              <h2>{sec.title}</h2>
              <table>
                <thead>
                  <tr>
                    <th>Rând</th>
                    <th>Indicator</th>
                    {sec.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sec.rows.map((r) => (
                    <tr key={r.code}>
                      <td>{r.code}</td>
                      <td>{r.label}</td>
                      {r.values.map((v, i) => (
                        <td key={i} style={{ textAlign: "right" }}>
                          {fmt(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          <section>
            <h2>Sume de control</h2>
            <p>
              {failed.length === 0 ? "Toate sumele de control se potrivesc." : `${failed.length} verificări nu se potrivesc:`}
            </p>
            {failed.length > 0 && (
              <ul>
                {failed.map((c, i) => (
                  <li key={i}>
                    {c.severity === "error" ? "Eroare" : "Atenție"}: {c.message} (așteptat {fmt(c.expected)}, calculat {fmt(c.actual)})
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </>
  );
}
