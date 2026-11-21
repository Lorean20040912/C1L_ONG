import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ROLE_LABELS, type OrganizationBrief, type Workspace } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { HomeScreen } from "./HomeScreen";
import { PlaceholderScreen } from "./PlaceholderScreen";
import { SECTIONS } from "./sections";
import { SectionPanel } from "./SectionPanel";

export interface Tab {
  id: string;
  title: string;
  fixed?: boolean;
}

const HOME: Tab = { id: "home", title: "Pagina inițială", fixed: true };

export function AppShell() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [orgs, setOrgs] = useState<OrganizationBrief[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tabs, setTabs] = useState<Tab[]>([HOME]);
  const [active, setActive] = useState(HOME.id);

  useEffect(() => {
    api<Workspace[]>("/workspaces")
      .then((ws) => setOrgs(ws.flatMap((w) => w.organizations)))
      .catch((e: Error) => setError(e.message));
  }, []);

  const org = useMemo(() => orgs.find((o) => o.id === orgId), [orgs, orgId]);

  const openTab = useCallback((id: string, title: string) => {
    setTabs((t) => (t.some((x) => x.id === id) ? t : [...t, { id, title }]));
    setActive(id);
  }, []);

  const closeTab = useCallback(
    (id: string) => {
      const i = tabs.findIndex((x) => x.id === id);
      if (i < 0 || tabs[i].fixed) return;
      const next = tabs.filter((x) => x.id !== id);
      setTabs(next);
      if (active === id) setActive(next[Math.max(0, i - 1)].id);
    },
    [tabs, active],
  );

  // Esc închide fila curentă, Ctrl+Tab trece la următoarea (docs/08 §3)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeTab(active);
      if (e.ctrlKey && e.key === "Tab") {
        e.preventDefault();
        const i = tabs.findIndex((t) => t.id === active);
        setActive(tabs[(i + 1) % tabs.length].id);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active, tabs, closeTab]);

  const activeTab = tabs.find((t) => t.id === active) ?? HOME;
  const section = SECTIONS.find((s) => `section:${s.id}` === activeTab.id);

  return (
    <div className="shell">
      <header className="shell-top">
        <button className="link" onClick={() => navigate("/")} title="Bazele mele" aria-label="Bazele mele">
          ☰
        </button>
        <span className="logo">
          Conta<b>Hub</b>
        </span>
        <select value={orgId} onChange={(e) => navigate(`/org/${e.target.value}`)} aria-label="Organizația curentă">
          {!org && <option value={orgId}>…</option>}
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <div className="search">
          <input placeholder="Căutare (Ctrl+F)" aria-label="Căutare" />
        </div>
        <span className="user" title={user?.email}>
          {user?.full_name}
          {org ? ` · ${ROLE_LABELS[org.role]}` : ""}
        </span>
        <button className="b" onClick={logout}>
          Ieșire
        </button>
      </header>

      <nav className="sections" aria-label="Secțiuni">
        {SECTIONS.map((s) => {
          const id = s.id === "home" ? HOME.id : `section:${s.id}`;
          return (
            <button key={s.id} className={active === id ? "active" : ""} onClick={() => openTab(id, s.title)}>
              <span className="ico">{s.icon}</span>
              <span className="t">{s.title}</span>
            </button>
          );
        })}
      </nav>

      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <div
            key={t.id}
            role="tab"
            tabIndex={0}
            aria-selected={t.id === active}
            className={`tab${t.id === active ? " active" : ""}`}
            onClick={() => setActive(t.id)}
            onKeyDown={(e) => e.key === "Enter" && setActive(t.id)}
          >
            {t.title}
            {!t.fixed && (
              <button
                className="x"
                aria-label={`Închide ${t.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(t.id);
                }}
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>

      <main className="main">
        {error && <div className="error">{error}</div>}
        {activeTab.id === HOME.id && <HomeScreen org={org} />}
        {section && <SectionPanel section={section} onOpen={openTab} />}
        {!section && activeTab.id !== HOME.id && <PlaceholderScreen title={activeTab.title} />}
      </main>
    </div>
  );
}
