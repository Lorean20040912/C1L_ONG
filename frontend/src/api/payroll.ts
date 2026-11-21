// Tipurile modulului Salarii + IPC21 (backend: app/payroll, app/individual_payments).

export type ContractType = "cim" | "civil";

export interface Person {
  id: string;
  full_name: string;
  idnp: string;
  idnp_masked: string;
  birth_date: string | null;
  cpas: string | null;
}

export interface Funding {
  grant_id: string;
  budget_line_id: string | null;
  share_percent: string;
  valid_from: string;
  valid_to: string | null;
}

export interface Exemption {
  kind: string;
  dependents_count: number;
  valid_from: string;
  valid_to: string | null;
}

export interface Contract {
  id: string;
  person_id: string;
  person_name: string;
  type: ContractType;
  is_main_job: boolean;
  department_id: string | null;
  special_function_code: string | null;
  number: string | null;
  start_date: string;
  end_date: string | null;
  gross_amount: string;
  funding: Funding[];
  exemptions: Exemption[];
}

export interface PayrollEntry {
  id: string;
  contract_id: string;
  contract_type: ContractType;
  contract_number: string | null;
  person_id: string;
  person_name: string;
  income_code: string;
  period_start: string | null;
  period_end: string | null;
  gross: string;
  cnas_employer: string | null;
  cnam_employee: string | null;
  personal_exemption: string | null;
  dependents_exemption: string | null;
  taxable_income: string | null;
  income_tax: string | null;
  net: string | null;
  calc_details: { funding?: { grant_code: string; share: string; gross: string }[] } | null;
}

export interface PayrollPeriod {
  year: number;
  month: number;
  calculated: boolean;
  is_closed: boolean;
  entries: PayrollEntry[];
  totals: Record<string, string>;
}

export interface GroupedPayment {
  document_id: string;
  doc_number: string | null;
  doc_date: string | null;
  tax_kind: string | null;
  amount: string | null;
  purpose: string | null;
  is_posted: boolean | null;
  lines: { person_id: string | null; person_name: string | null; grant_id: string | null; amount: string }[];
}

export interface IndividualPayment {
  document_id: string;
  doc_number: string | null;
  person_id: string;
  person_name: string;
  payment_kind: string;
  income_code: string;
  accrual_date: string;
  payment_date: string | null;
  gross: string;
  income_tax: string | null;
  net: string | null;
  grant_id: string | null;
  budget_line_id: string | null;
  is_posted: boolean | null;
  version: number | null;
}

export interface PaymentKind {
  kind: string;
  income_code: string;
  rate_code: string;
  title: string;
}

export interface Ipc21Row {
  row: string;
  code: string;
  title: string;
  c4: string;
  c5: string;
  c6: string;
}

export interface Ipc21 {
  year: number;
  month: number;
  table1: Ipc21Row[];
  total: Ipc21Row;
  control_sum: string;
  annex: { no: number; cuatm: string; c3: string; c4: string; c5: string }[];
  nominal: {
    no: number;
    full_name: string;
    idnp_masked: string;
    cpas: string | null;
    period_start: string | null;
    period_end: string | null;
    insured_category: string | null;
    tariff: string;
    base: string;
    contribution: string;
  }[];
  tariffs: { row: string; tariff: string; c9: string; c11: string }[];
  breakdown: { source: string; code: string; person: string; contract: string | null; c4: string; c5: string; c6: string }[];
  errors: string[];
}

export const TAX_KIND_LABELS: Record<string, string> = {
  income_tax: "Impozit pe venit",
  cnas: "CNAS (CAS)",
  cnam: "CNAM (CAM)",
  net_salary: "Salariul net",
};

export const EXEMPTION_LABELS: Record<string, string> = {
  personal: "Scutire personală",
  major_personal: "Scutire personală majoră",
  dependents: "Persoane întreținute",
  disabled_dependents: "Persoane întreținute cu dizabilitate",
};

export function monthPeriod(offset = -1): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
