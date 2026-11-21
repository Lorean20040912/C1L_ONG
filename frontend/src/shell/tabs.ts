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
  | "manual";

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
