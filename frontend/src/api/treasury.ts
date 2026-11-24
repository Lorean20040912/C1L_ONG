// Tipurile documentelor de bancă și casă, decontului de avans, actelor de servicii și ale rapoartelor de achiziții.

export type TreasuryKind = "bank_receipt" | "bank_payment" | "cash_receipt" | "cash_payment" | "advance_report" | "service_act";

export interface TreasuryLine {
  description: string;
  amount: string;
  line_kind: string;
  quantity: string | null;
  account_id: string | null;
  budget_line_id: string | null;
  cost_item_id: string | null;
}

export interface TreasuryDoc {
  document_id: string;
  kind: TreasuryKind;
  kind_label: string;
  operation: string | null;
  operation_label: string | null;
  doc_number: string | null;
  doc_date: string | null;
  amount: string | null;
  currency: string | null;
  exchange_rate: string | null;
  bank_account_id: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  person_id: string | null;
  person_name: string | null;
  account_id: string | null;
  grant_id: string | null;
  purpose: string | null;
  basis: string | null;
  is_posted: boolean | null;
  version: number | null;
  lines: TreasuryLine[];
}

export interface OpMeta {
  code: string;
  label: string;
  needs: string[];
  optional: string[];
  explicit: string | null;
  bank: string | null;
  cash: string | null;
}

export interface KindMeta {
  kind: TreasuryKind;
  label: string;
  operations: OpMeta[];
}

export interface TreasuryPreviewLine {
  entry_date: string;
  debit_account: string;
  credit_account: string;
  amount: string;
  source_ref: string;
}

export interface BudgetWarning {
  label: string;
  planned: string;
  spent: string;
  over: string;
  message: string;
}

export interface TreasuryPostResult {
  warnings: BudgetWarning[];
}

export interface SupplierDebtRow {
  counterparty_id: string | null;
  name: string;
  idno: string | null;
  opening: string;
  debit: string;
  credit: string;
  closing: string;
  age_0_30: string;
  age_31_60: string;
  age_61_90: string;
  age_over_90: string;
}

export interface SupplierDebts {
  date_from: string;
  date_to: string;
  rows: SupplierDebtRow[];
  total_opening: string;
  total_debit: string;
  total_credit: string;
  total_closing: string;
}

export interface DebtMove {
  entry_date: string;
  document_id: string;
  doc_number: string | null;
  doc_type: string | null;
  debit: string;
  credit: string;
  description: string | null;
}

export interface InvoiceJournalRow {
  document_id: string;
  doc_date: string | null;
  series: string | null;
  doc_number: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  idno: string | null;
  vat_code: string | null;
  e_invoice_id: string | null;
  total: string;
  net: string;
  vat: string;
  is_posted: boolean;
}

export interface InvoiceJournal {
  rows: InvoiceJournalRow[];
  total: string;
  net: string;
  vat: string;
  by_rate: { vat_rate: string; base: string; vat: string }[];
}
