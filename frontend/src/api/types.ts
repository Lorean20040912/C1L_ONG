export type UserRole = "admin" | "chief_accountant" | "accountant" | "project_manager" | "auditor";

export type EntityType = "srl" | "sa" | "ii" | "gt" | "ngo_association" | "ngo_foundation" | "ngo_other" | "other";

export interface User {
  id: string;
  email: string;
  full_name: string;
}

export interface OrganizationBrief {
  id: string;
  name: string;
  idno: string;
  entity_type: EntityType;
  accounting_method: "double_entry" | "single_entry";
  role: UserRole;
}

export interface Workspace {
  id: string;
  name: string;
  source: string | null;
  created_at: string | null;
  organizations: OrganizationBrief[];
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Administrator",
  chief_accountant: "Contabil-șef",
  accountant: "Contabil",
  project_manager: "Manager de proiect",
  auditor: "Auditor",
};

export const ENTITY_LABELS: Record<EntityType, string> = {
  srl: "SRL",
  sa: "SA",
  ii: "Întreprindere individuală",
  gt: "Gospodărie țărănească",
  ngo_association: "Asociație obștească",
  ngo_foundation: "Fundație",
  ngo_other: "ONG (altă formă)",
  other: "Altă formă",
};

// ───────────── cataloage ─────────────

export interface Account {
  id: string;
  code: string;
  name: string;
  is_group: boolean | null;
}

export interface Counterparty {
  id: string;
  name: string;
  idno: string | null;
}

export interface BudgetLine {
  id: string;
  code: string;
  name: string;
  planned_amount: string;
}

export interface Grant {
  id: string;
  code: string;
  title: string;
  funding_type: string | null;
  budget_lines: BudgetLine[];
}

export interface BankAccount {
  id: string;
  iban: string;
  bank_name: string | null;
  currency: string;
  account_id: string | null;
  grant_id: string | null;
}

// ───────────── documente ─────────────

export type LineKind = "service" | "fixed_asset" | "low_value_item" | "material" | "goods";

export const LINE_KIND_LABELS: Record<LineKind, string> = {
  service: "Servicii",
  fixed_asset: "Mijloc fix",
  low_value_item: "OMVSD",
  material: "Materiale",
  goods: "Mărfuri",
};

export interface InvoiceLine {
  id?: string;
  description: string;
  quantity: string | null;
  unit: string | null;
  unit_price: string | null;
  vat_rate: string | null;
  amount: string;
  line_kind: LineKind;
  account_id: string | null;
  budget_line_id: string | null;
  cost_item_id: string | null;
  put_into_use: boolean;
  fixed_asset_id?: string | null;
}

export interface InvoiceListItem {
  document_id: string;
  doc_number: string | null;
  series: string | null;
  doc_date: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  total_amount: string | null;
  is_posted: boolean | null;
  deletion_mark: boolean | null;
}

export interface Invoice extends InvoiceListItem {
  version: number | null;
  lines: InvoiceLine[];
}

export type PaymentDirection = "outgoing" | "incoming";

export interface PaymentLine {
  grant_id: string | null;
  amount: string;
}

export interface PaymentOrder {
  document_id: string;
  direction: PaymentDirection;
  doc_number: string | null;
  doc_date: string | null;
  amount: string | null;
  currency: string | null;
  exchange_rate: string | null;
  purpose: string | null;
  bank_account_id: string | null;
  counterparty_id: string | null;
  beneficiary_name: string | null;
  beneficiary_idno: string | null;
  invoice_document_id: string | null;
  bank_status: string | null;
  is_posted: boolean | null;
  version: number | null;
  lines: PaymentLine[];
}

export interface PreviewLine {
  entry_date: string;
  debit_account: string;
  credit_account: string;
  amount: string;
  grant_id: string | null;
  budget_line_id: string | null;
  activity_type: string | null;
  source_ref: string;
}

export interface EntryLine {
  id: number;
  line_no: number;
  entry_date: string;
  debit_account_id: string;
  credit_account_id: string;
  amount: string;
  currency: string | null;
  currency_amount: string | null;
  grant_id: string | null;
  budget_line_id: string | null;
  description: string | null;
}
