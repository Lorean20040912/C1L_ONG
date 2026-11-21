import { createContext, useContext } from "react";
import type { UserRole } from "../api/types";

export type TabKind =
  | "home"
  | "section"
  | "placeholder"
  | "invoice-list"
  | "invoice"
  | "payment-list"
  | "payment"
  | "dtkt"
  | "budget"
  | "month-close"
  | "fixed-assets"
  | "grants"
  | "policy"
  | "rules"
  | "bank-accounts"
  | "bank-import"
  | "payment-export"
  | "exchange-rates"
  | "members"
  | "periods"
  | "accounts"
  | "trial-balance"
  | "manual"
  | "persons"
  | "contracts"
  | "payroll"
  | "individual-payments"
  | "ipc21"
  | "ong17"
  | "con5"
  | "account-card"
  | "account-analysis"
  | "cost-items"
  | "reporting-data"
  | "features"
  | "simple-journal"
  | "donors"
  | "grant-advanced"
  | "stock-distribution"
  | "security"
  | "audit"
  | "tasks";

export interface Tab {
  id: string;
  title: string;
  kind: TabKind;
  fixed?: boolean;
  dirty?: boolean;
  /** cheia de randare, fixată la deschidere: id-ul se poate schimba (document nou salvat),
   * dar ecranul nu trebuie remontat în mijlocul unei operații */
  key?: string;
  /** parametrii ecranului: id-ul documentului, secțiunea etc. */
  params?: Record<string, string>;
}

export interface ShellApi {
  orgId: string;
  /** rolul utilizatorului în organizația curentă (pentru a arăta doar acțiunile permise) */
  role: UserRole | undefined;
  openTab: (tab: Tab) => void;
  closeTab: (id: string, options?: { force?: boolean }) => void;
  updateTab: (id: string, patch: Partial<Tab>) => void;
}

export const ShellContext = createContext<ShellApi | null>(null);

export function useShell(): ShellApi {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell în afara AppShell");
  return ctx;
}

// linkurile din panourile secțiunilor care au deja ecran
export const SCREEN_LINKS: Record<string, TabKind> = {
  "Facturi primite": "invoice-list",
  "Ordine de plată": "payment-list",
  "Execuția bugetului": "budget",
  "Închiderea lunii": "month-close",
  "Fișa mijloacelor fixe": "fixed-assets",
  "Proiecte / granturi": "grants",
  "Linii de buget": "grants",
  "Politica contabilă": "policy",
  "Reguli de înregistrare": "rules",
  "Conturi bancare": "bank-accounts",
  "Import extras bancar": "bank-import",
  "Export ordine de plată": "payment-export",
  "Curs BNM": "exchange-rates",
  "Utilizatori și drepturi": "members",
  "Perioade închise": "periods",
  "Planul de conturi": "accounts",
  "Balanța de verificare (OSV)": "trial-balance",
  "Operațiune manuală": "manual",
  "Persoane fizice": "persons",
  Angajare: "contracts",
  "Contracte civile": "contracts",
  "Cereri de scutire": "contracts",
  "Calcul salariu": "payroll",
  "Stat de plată": "payroll",
  "Fișa de salariu": "payroll",
  "Plată către persoană fizică": "individual-payments",
  "Plăți către persoane fizice": "individual-payments",
  IPC21: "ipc21",
  ONG17: "ong17",
  "5-CON": "con5",
  "Fișa contului": "account-card",
  "Analiza contului": "account-analysis",
  "Articole de cheltuieli": "cost-items",
  "Date pentru rapoarte": "reporting-data",
  Funcționalitate: "features",
  "Registru-jurnal (partidă simplă)": "simple-journal",
  Donatori: "donors",
  "Versiuni și tranșe": "grant-advanced",
  "Distribuirea stocurilor": "stock-distribution",
  "Repartizarea cheltuielilor": "month-close",
  "Securitatea contului": "security",
  "Jurnal de audit": "audit",
  "Sarcini și termene": "tasks",
};

export const ADMIN_ROLES: UserRole[] = ["admin", "chief_accountant"];
export const POSTING_ROLES: UserRole[] = ["admin", "chief_accountant", "accountant"];

export function can(role: UserRole | undefined, roles: UserRole[]): boolean {
  return role !== undefined && roles.includes(role);
}

let counter = 0;
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}:new:${counter}`;
}
