import { ENTITY_LABELS, type OrganizationBrief } from "../api/types";

export function HomeScreen({ org }: { org: OrganizationBrief | undefined }) {
  const today = new Date().toLocaleDateString("ro-RO", { weekday: "long", day: "numeric", month: "long" });
  return (
    <>
      <h1>Pagina inițială</h1>
      <div className="cols">
        <div>
          <h2>Astăzi: {today}</h2>
          {org && (
            <div className="card">
              <b>{org.name}</b>
              <div className="muted">
                IDNO {org.idno} · {ENTITY_LABELS[org.entity_type]} ·{" "}
                {org.accounting_method === "double_entry" ? "partidă dublă" : "partidă simplă"}
              </div>
            </div>
          )}
          <h2>Calendarul raportărilor</h2>
          <p className="muted">Termenele IPC21, 5-CON și ONG17 apar aici odată cu modulul de rapoarte.</p>
        </div>
        <div>
          <h2>Documente de verificat</h2>
          <p className="muted">Nu sunt documente în așteptare.</p>
        </div>
      </div>
    </>
  );
}
