import { createContext, useContext } from "react";

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
  | "fixed-assets";

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
};

let counter = 0;
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}:new:${counter}`;
}
