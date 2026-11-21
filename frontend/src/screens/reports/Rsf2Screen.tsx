import { useState } from "react";
import { download } from "../../api/client";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** RSF2 — situațiile financiare anuale ale asociației obștești: XML din contabilitate, în formatul fiscului. */
export function Rsf2Screen() {
  const { orgId } = useShell();
  const [year, setYear] = useState(new Date().getFullYear() - 1);
  const { busy, error, info, run } = useAction();

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
        </div>
      </section>
    </>
  );
}
