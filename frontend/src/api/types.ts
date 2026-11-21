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

export type AccountKind = "active" | "passive" | "active_passive";

export interface Account {
  id: string;
  code: string;
  name: string;
  parent_id?: string | null;
  account_kind?: AccountKind;
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

// ───────────── buget, închiderea lunii, mijloace fixe ─────────────

export interface BudgetLineExecution {
  grant_id: string;
  grant_code: string;
  budget_line_id: string;
  code: string;
  name: string;
  planned: string;
  spent: string;
  remaining: string;
  over: string;
}

export interface BudgetWarning {
  budget_line_id: string;
  label: string;
  planned: string;
  spent: string;
  over: string;
  message: string;
}

export interface MonthCloseStep {
  step: string;
  title: string;
  implemented: boolean;
  status: "pending" | "done" | "reverted" | "error";
  entries: number | null;
  total: string | null;
  issues: string[];
}

export interface StepPreview {
  step: string;
  total: string;
  rows: { label: string; amount: string; debit_account: string | null; credit_account: string | null; note: string | null }[];
  errors: string[];
}

export interface MonthClose {
  year: number;
  month: number;
  status: string;
  document_id: string | null;
  steps: MonthCloseStep[];
}

export interface DepreciationRow {
  fixed_asset_id: string;
  inventory_no: string;
  name: string;
  initial_cost: string;
  accumulated_before: string;
  amount: string;
  debit_account: string | null;
  credit_account: string | null;
  grant_id: string | null;
  source_ref: string | null;
  error: string | null;
}

export interface DepreciationPreview {
  year: number;
  month: number;
  entry_date: string;
  total: string;
  rows: DepreciationRow[];
  errors: string[];
}

export interface FixedAsset {
  id: string;
  inventory_no: string;
  name: string;
  initial_cost: string;
  residual_value: string | null;
  useful_life_months: number | null;
  asset_group: string | null;
  status: string | null;
  commissioning_date: string | null;
  depreciation_start: string | null;
  grant_id: string | null;
  budget_line_id: string | null;
  expense_account_id: string | null;
  document_id: string | null;
  accumulated: string;
  book_value: string;
}

// ───────────── administrare ─────────────

export interface GrantDetail {
  id: string;
  code: string;
  title: string;
  funding_type: string | null;
  designation_year: number | null;
  currency: string;
  total_amount: string;
  account_id: string | null;
  start_date: string;
  end_date: string;
  is_closed: boolean | null;
}

export interface BudgetLineDetail {
  id: string;
  grant_id: string;
  code: string;
  name: string;
  planned_amount: string;
  donor_amount: string | null;
  cofinancing_amount: string | null;
  in_use: boolean;
}

export const FUNDING_LABELS: Record<string, string> = {
  grant: "Grant (destinație specială)",
  "donație": "Donație cu destinație",
  "cotizații": "Cotizații (nepredestinate)",
  unrestricted: "Mijloace nepredestinate",
  economic: "Activitate economică",
  percentage_designation: "Desemnare procentuală",
};

export interface AccountingPolicy {
  id: string;
  valid_from: string;
  grant_receivable_account_id: string | null;
  grant_recognition: string | null;
  stock_to_deferred_income: string | null;
  fa_valuation_method: string | null;
  approved_by_name: string | null;
}

export interface PostingRule {
  id: string;
  organization_id: string | null;
  document_type: string;
  operation: string;
  conditions: Record<string, unknown> | null;
  debit_account: string;
  credit_account: string;
  analytics: Record<string, unknown> | null;
  source_ref: string;
  valid_from: string;
  valid_to: string | null;
  version: number | null;
  change_reason: string | null;
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean | null;
  last_login_at: string | null;
}

export interface Period {
  year: number;
  month: number;
  is_closed: boolean;
  closed_at: string | null;
  closed_by_name: string | null;
}

// ───────── bancă ─────────

export interface BankFormat {
  id: string;
  bank_name: string;
  file_type: string;
  direction: "import" | "export";
  encoding: string;
  layout: Record<string, unknown>;
  is_standard: boolean;
}

export interface BankTransaction {
  id: string;
  tx_date: string;
  direction: PaymentDirection;
  amount: string;
  currency: string | null;
  doc_number: string | null;
  counterparty_name: string | null;
  counterparty_iban: string | null;
  purpose: string | null;
  match: string | null;
  document_id: string | null;
  is_posted: boolean;
}

export interface BankImport {
  id: string;
  file_name: string | null;
  rows_total: number | null;
  rows_created: number | null;
  rows_skipped: number | null;
  rows_failed: number | null;
  errors: unknown[];
  imported_at: string | null;
  dry_run: boolean;
  transactions: BankTransaction[];
}

export interface PaymentBatch {
  id: string;
  bank_account_id: string;
  created_at: string | null;
  file_name: string | null;
  orders_count: number | null;
  total_amount: string | null;
}

export interface ExchangeRate {
  currency: string;
  rate_date: string;
  rate: string;
  source: string | null;
}
