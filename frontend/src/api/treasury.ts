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
  invoices_total: string;
  invoices_paid: string;
  invoices_remaining: string;
  count_unpaid: number;
  count_partial: number;
  count_paid: number;
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
  invoice_paid: string | null;
  invoice_remaining: string | null;
  payment_status: PaymentState | null;
  allocated: string | null;
}

export type PaymentState = "unpaid" | "partial" | "paid";
export const PAYMENT_STATE_LABELS: Record<PaymentState, string> = { unpaid: "neachitată", partial: "parțial", paid: "achitată" };

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
  paid: string;
  remaining: string;
  payment_status: PaymentState;
}

export interface InvoiceJournal {
  rows: InvoiceJournalRow[];
  total: string;
  net: string;
  vat: string;
  paid: string;
  remaining: string;
  by_rate: { vat_rate: string; base: string; vat: string }[];
}

export interface SettleItem {
  invoice_document_id: string;
  amount: string;
}

export interface OpenInvoice {
  document_id: string;
  doc_number: string | null;
  series: string | null;
  doc_date: string | null;
  total: string;
  paid: string;
  remaining: string;
  payment_status: PaymentState;
  is_posted: boolean;
}

export interface SupplierPayment {
  payment_document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  amount: string;
  allocated: string;
  free: string;
  is_posted: boolean;
}

export interface PaymentSettlements {
  payment_document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  amount: string;
  allocated: string;
  free: string;
  is_posted: boolean;
  items: SettleItem[];
  open_invoices: OpenInvoice[];
}

export interface InvoiceSettlements {
  document_id: string;
  doc_number: string | null;
  total: string;
  paid: string;
  remaining: string;
  payment_status: PaymentState;
  payments: { payment_document_id: string; doc_number: string | null; doc_date: string | null; is_posted: boolean; amount: string }[];
}
