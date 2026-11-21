import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ROLE_LABELS, type OrganizationBrief, type Workspace } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { FeaturesScreen } from "../screens/admin/FeaturesScreen";
import { SimpleJournal } from "../screens/SimpleJournal";
import { AccountsScreen } from "../screens/admin/AccountsScreen";
import { BankImportScreen } from "../screens/bank/BankImportScreen";
import { ExchangeRatesScreen } from "../screens/bank/ExchangeRatesScreen";
import { PaymentExportScreen } from "../screens/bank/PaymentExportScreen";
import { BankAccountsScreen } from "../screens/admin/BankAccountsScreen";
import { GrantsScreen } from "../screens/admin/GrantsScreen";
import { AuditScreen } from "../screens/admin/AuditScreen";
import { MembersScreen } from "../screens/admin/MembersScreen";
import { SecurityScreen } from "../screens/admin/SecurityScreen";
import { TasksScreen } from "../screens/admin/TasksScreen";
import { PeriodsScreen } from "../screens/admin/PeriodsScreen";
import { PolicyScreen } from "../screens/admin/PolicyScreen";
import { RulesScreen } from "../screens/admin/RulesScreen";
import { DonorsScreen } from "../screens/grants/DonorsScreen";
import { GrantAdvancedScreen } from "../screens/grants/GrantAdvancedScreen";
import { StockDistributionScreen } from "../screens/grants/StockDistributionScreen";
import { BudgetExecution } from "../screens/BudgetExecution";
import { ManualOperation } from "../screens/ManualOperation";
import { TrialBalance } from "../screens/TrialBalance";
import { FixedAssets } from "../screens/FixedAssets";
import { InvoiceForm } from "../screens/InvoiceForm";
import { InvoiceList } from "../screens/InvoiceList";
import { MonthCloseScreen } from "../screens/MonthCloseScreen";
import { PaymentForm } from "../screens/PaymentForm";
import { PaymentList } from "../screens/PaymentList";
import { PostingView } from "../screens/PostingView";
import { ContractsScreen } from "../screens/payroll/ContractsScreen";
import { IndividualPayments } from "../screens/payroll/IndividualPayments";
import { Ipc21Screen } from "../screens/payroll/Ipc21Screen";
import { PayrollScreen } from "../screens/payroll/PayrollScreen";
import { PersonsScreen } from "../screens/payroll/PersonsScreen";
import { AccountReports } from "../screens/reports/AccountReports";
import { CostItemsScreen } from "../screens/reports/CostItemsScreen";
import { RegulatedReport } from "../screens/reports/RegulatedReport";
import { ReportingDataScreen } from "../screens/reports/ReportingDataScreen";
import { EfacturaScreen } from "../screens/import/EfacturaScreen";
import { OnecImportScreen } from "../screens/import/OnecImportScreen";
import { HomeScreen } from "./HomeScreen";
import { PlaceholderScreen } from "./PlaceholderScreen";
import { ProfileContext, useProfileLoader } from "./profile";
import { SECTIONS } from "./sections";
import { SectionPanel } from "./SectionPanel";
import { ShellContext, type ShellApi, type Tab } from "./tabs";

const HOME: Tab = { id: "home", title: "Pagina inițială", kind: "home", fixed: true };

export function AppShell() {
  const { orgId = "" } = useParams();
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

  // altă organizație = alt set de file (documentele deschise erau ale celeilalte)
  useEffect(() => {
    setTabs([HOME]);
    setActive(HOME.id);
  }, [orgId]);

  const profile = useProfileLoader(orgId);
  const org = useMemo(() => orgs.find((o) => o.id === orgId), [orgs, orgId]);

  const openTab = useCallback((tab: Tab) => {
    setTabs((t) => (t.some((x) => x.id === tab.id) ? t : [...t, { ...tab, key: tab.key ?? tab.id }]));
    setActive(tab.id);
  }, []);

  // filele curente pentru închidere: un formular poate închide fila imediat după ce
  // i s-a schimbat id-ul (document nou salvat), înainte de următoarea randare
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;

  const closeTab = useCallback((id: string, options?: { force?: boolean }) => {
    const current = tabsRef.current;
    const i = current.findIndex((x) => x.id === id);
    if (i < 0 || current[i].fixed) return;
    if (!options?.force && current[i].dirty && !window.confirm(`„${current[i].title}” are modificări nesalvate. Închideți fără salvare?`))
      return;
    const next = current.filter((x) => x.id !== id);
    tabsRef.current = next;
    setTabs(next);
    setActive((a) => (a === id ? next[Math.max(0, i - 1)].id : a));
  }, []);

  const updateTab = useCallback((id: string, patch: Partial<Tab>) => {
    const t = tabsRef.current;
    const i = t.findIndex((x) => x.id === id);
    if (i < 0) return;
    const next = [...t.slice(0, i), { ...t[i], ...patch }, ...t.slice(i + 1)];
    tabsRef.current = next;
    setTabs(next);
    // un document nou salvat primește id-ul lui real; fila activă îl urmează
    if (patch.id && patch.id !== id) setActive((a) => (a === id ? patch.id! : a));
  }, []);

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

  const shell: ShellApi = useMemo(
    () => ({ orgId, role: org?.role, openTab, closeTab, updateTab }),
    [orgId, org?.role, openTab, closeTab, updateTab],
  );

  return (
    <ShellContext.Provider value={shell}>
      <ProfileContext.Provider value={profile}>
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
          {SECTIONS.filter((s) => profile.sectionVisible(s.id)).map((s) => {
            const id = s.id === "home" ? HOME.id : `section:${s.id}`;
            return (
              <button
                key={s.id}
                className={active === id ? "active" : ""}
                onClick={() => (s.id === "home" ? setActive(HOME.id) : openTab({ id, title: s.title, kind: "section", params: { section: s.id } }))}
              >
                <span className="ico">{s.icon}</span>
                <span className="t">{s.title}</span>
              </button>
            );
          })}
        </nav>

        <div className="tabs" role="tablist">
          {tabs.map((t) => (
            <div
              key={t.key ?? t.id}
              role="tab"
              tabIndex={0}
              aria-selected={t.id === active}
              className={`tab${t.id === active ? " active" : ""}`}
              onClick={() => setActive(t.id)}
              onKeyDown={(e) => e.key === "Enter" && setActive(t.id)}
            >
              {t.title}
              {t.dirty ? " *" : ""}
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
          {/* filele rămân montate (ascunse), ca un formular început să nu se piardă la comutare */}
          {tabs.map((t) => (
            <div key={t.key ?? t.id} hidden={t.id !== active}>
              <Screen tab={t} org={org} />
            </div>
          ))}
        </main>
      </div>
      </ProfileContext.Provider>
    </ShellContext.Provider>
  );
}

function Screen({ tab, org }: { tab: Tab; org: OrganizationBrief | undefined }) {
  const p = tab.params ?? {};
  switch (tab.kind) {
    case "home":
      return <HomeScreen org={org} />;
    case "section": {
      const section = SECTIONS.find((s) => s.id === p.section);
      return section ? <SectionPanel section={section} /> : null;
    }
    case "invoice-list":
      return <InvoiceList />;
    case "invoice":
      return <InvoiceForm tabId={tab.id} documentId={p.documentId} />;
    case "payment-list":
      return <PaymentList />;
    case "payment":
      return <PaymentForm tabId={tab.id} documentId={p.documentId} invoiceId={p.invoiceId} />;
    case "budget":
      return <BudgetExecution />;
    case "month-close":
      return <MonthCloseScreen />;
    case "fixed-assets":
      return <FixedAssets />;
    case "grants":
      return <GrantsScreen />;
    case "policy":
      return <PolicyScreen />;
    case "rules":
      return <RulesScreen />;
    case "bank-accounts":
      return <BankAccountsScreen />;
    case "bank-import":
      return <BankImportScreen />;
    case "payment-export":
      return <PaymentExportScreen />;
    case "exchange-rates":
      return <ExchangeRatesScreen />;
    case "members":
      return <MembersScreen />;
    case "security":
      return <SecurityScreen />;
    case "audit":
      return <AuditScreen />;
    case "tasks":
      return <TasksScreen />;
    case "periods":
      return <PeriodsScreen />;
    case "accounts":
      return <AccountsScreen />;
    case "trial-balance":
      return <TrialBalance />;
    case "manual":
      return <ManualOperation tabId={tab.id} />;
    case "onec-import":
      return <OnecImportScreen />;
    case "efactura":
      return <EfacturaScreen />;
    case "persons":
      return <PersonsScreen />;
    case "contracts":
      return <ContractsScreen />;
    case "payroll":
      return <PayrollScreen />;
    case "individual-payments":
      return <IndividualPayments />;
    case "ipc21":
      return <Ipc21Screen />;
    case "ong17":
      return <RegulatedReport code="ONG17" periodFrom={p.periodFrom} />;
    case "con5":
      return <RegulatedReport code="5-CON" periodFrom={p.periodFrom} />;
    case "account-card":
      return <AccountReports mode="card" accountId={p.accountId} />;
    case "account-analysis":
      return <AccountReports mode="analysis" accountId={p.accountId} />;
    case "cost-items":
      return <CostItemsScreen />;
    case "features":
      return <FeaturesScreen />;
    case "simple-journal":
      return <SimpleJournal />;
    case "reporting-data":
      return <ReportingDataScreen />;
    case "donors":
      return <DonorsScreen />;
    case "grant-advanced":
      return <GrantAdvancedScreen />;
    case "stock-distribution":
      return <StockDistributionScreen />;
    case "dtkt":
      return <PostingView route={p.route} documentId={p.documentId} title={tab.title} />;
    default:
      return <PlaceholderScreen title={tab.title} />;
  }
}
