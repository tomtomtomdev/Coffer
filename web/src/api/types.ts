/*
 * Wire types for the dashboard read API. Money arrives as **strings** (exact Decimal
 * from the backend — never floats). Parse to a number only at the render/chart edge.
 * Mirrors coffer/api/dashboard_schemas.py.
 */

export type Bucket = "cash" | "liability" | "portfolio";

export interface GridPoint {
  grid_date: string; // ISO date
  cash: string;
  portfolio: string;
  liability: string;
  net_worth: string;
}

export interface MemberPoint {
  grid_date: string;
  net_worth: string;
}

export interface MemberSeries {
  member_id: number;
  member_name: string;
  points: MemberPoint[];
}

export interface AccountBalance {
  account_id: number;
  member_id: number;
  institution: string;
  account_type: string;
  account_number_masked: string;
  bucket: Bucket;
  balance: string;
  as_of: string | null;
}

export interface Delta {
  amount: string;
  pct: string | null;
}

export interface Kpis {
  routine_spend_monthly: string | null;
  routine_annual_amortized: string;
  savings_rate: string | null;
  monthly_cash_flow: string | null;
}

export interface RingkasanResponse {
  as_of: string | null;
  net_worth: string;
  delta: Delta | null;
  household_series: GridPoint[];
  member_series: MemberSeries[];
  accounts: AccountBalance[];
  kpis: Kpis;
}

// ── §3.2 Portofolio ──────────────────────────────────────────────────────────────────
export interface BrokerHolding {
  institution: string;
  account_id: number;
  lots: string;
  avg_price: string;
  market_price: string;
  market_value: string;
  unrealized_pl: string;
  as_of: string;
}

export interface ConsolidatedHolding {
  ticker: string;
  name: string;
  lots: string;
  avg_price: string;
  market_value: string;
  unrealized_pl: string;
  cost_basis: string;
  brokers: BrokerHolding[];
}

export interface PortofolioResponse {
  total_market_value: string;
  total_unrealized_pl: string;
  total_cost_basis: string;
  holdings: ConsolidatedHolding[];
  as_of_dates: string[];
  mixed_as_of: boolean;
}

// ── §3.3 Belanja ─────────────────────────────────────────────────────────────────────
export type CategorySource = "parser" | "learned_rule" | "manual" | "onboarding";

export interface MonthlyRoutinePoint {
  month: string; // ISO date (month-first)
  total: string;
}

export interface CategoryMedian {
  category_id: number;
  label: string;
  median_monthly: string;
  observation_count: number;
  cadence: string; // "monthly" | "annual" | "irregular"
}

export interface SpendAnomaly {
  transaction_id: number;
  category_id: number;
  category_label: string;
  description: string;
  amount: string;
  category_median: string;
  reason: string;
}

export interface ReviewItem {
  transaction_id: number;
  date: string;
  description: string;
  debit: string;
  credit: string;
  counterparty_name: string | null;
  counterparty_acct: string | null;
  account_id: number;
  institution: string;
  account_number_masked: string;
  category_id: number | null;
  category_label: string | null;
  category_source: CategorySource | null; // null ⇒ uncategorized ("Perlu tag")
  is_anomaly: boolean;
}

export interface CategoryOption {
  id: number;
  label: string;
  type: string; // CategoryType value
  cadence: string; // Cadence value
}

export interface BelanjaResponse {
  estimate: string | null; // null on cold start (<3 months)
  insufficient_data: boolean;
  months_observed: number;
  window_months: number;
  base_median_monthly: string;
  annual_amortized_monthly: string;
  monthly_series: MonthlyRoutinePoint[];
  category_breakdown: CategoryMedian[];
  anomalies: SpendAnomaly[];
  review_queue: ReviewItem[];
  categories: CategoryOption[];
}

// ── §3.5 Arus Kas ────────────────────────────────────────────────────────────────────
export interface MonthlyCashFlow {
  month: string; // ISO date (month-first)
  income: string;
  spend: string;
  cash_flow: string;
  savings_rate: string | null; // null when the month's income was zero
}

export interface IncomeSource {
  category_id: number;
  label: string;
  amount: string;
}

export interface SpendType {
  type: string; // CategoryType value: "routine" | "discretionary" | "one_off"
  amount: string;
}

export interface ArusKasResponse {
  months: MonthlyCashFlow[];
  headline_savings_rate: string | null; // null when the window's income was zero
  window_months: number;
  latest_month: string | null;
  latest_cash_flow: string | null;
  income_sources: IncomeSource[];
  spend_by_type: SpendType[];
}

// The Tag/Ubah write — the only mutation in the dashboard so far.
export interface RecategorizeRequest {
  category_id: number;
  member_id?: number | null;
  generalize?: "counterparty_acct" | "amount" | null;
  confirm_amount_only?: boolean;
  amount_tolerance?: string | null;
}

export interface RecategorizeResponse {
  transaction_id: number;
  category_id: number;
  category_source: string; // always "manual"
  deactivated_rule_id: number | null;
  created_rule_id: number | null;
}
