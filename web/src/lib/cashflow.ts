/*
 * Pure transforms for the Arus Kas (§3.5) view — Recharts row shaping + spend-type
 * labels. No React, no money math beyond parsing the wire strings; kept separate so it is
 * unit-testable. Bahasa copy lives here (at the UI edge, per CLAUDE.md).
 */
import type { MonthlyCashFlow } from "../api/types";
import { monthShort, num } from "./format";

export interface CashFlowDatum {
  label: string; // month short, e.g. "Jun"
  income: number; // rupiah
  spend: number; // rupiah
  savings: number | null; // fraction 0–1 (null ⇒ line gap: the month had no income)
}

/** The grouped income/spend bars + savings-rate line rows, limited to the last
 *  `windowMonths` (the design shows 6). A month with zero income yields `savings: null`
 *  so the Recharts line breaks rather than plotting a bogus 0%. */
export function cashFlowChartData(
  months: MonthlyCashFlow[],
  windowMonths: number,
): CashFlowDatum[] {
  const window = windowMonths > 0 ? months.slice(-windowMonths) : months;
  return window.map((m) => ({
    label: monthShort(m.month),
    income: num(m.income),
    spend: num(m.spend),
    savings: m.savings_rate === null ? null : num(m.savings_rate),
  }));
}

/** Primary (rupiah) axis top = 1.22 × the largest bar across income/spend (MEASUREMENTS
 *  §Cash Flow). */
export function incomeAxisMax(rows: CashFlowDatum[]): number {
  const max = rows.reduce((a, r) => Math.max(a, r.income, r.spend), 0);
  return max <= 0 ? 1 : max * 1.22;
}

/** Secondary (savings-rate) axis top — headroom above the largest rate, capped at 100%
 *  and floored so a tiny-rate chart still has a sane scale. */
export function savingsAxisMax(rows: CashFlowDatum[]): number {
  const max = rows.reduce((a, r) => Math.max(a, r.savings ?? 0), 0);
  if (max <= 0) return 0.1;
  return Math.min(1, max * 1.25);
}

const SPEND_TYPE_LABEL: Record<string, string> = {
  routine: "Rutin",
  discretionary: "Discretionary",
  one_off: "One-off",
};

/** The Bahasa label for a spend `CategoryType` in the "Belanja per Tipe" list — matches
 *  the frozen design copy. */
export function spendTypeLabel(type: string): string {
  return SPEND_TYPE_LABEL[type] ?? type;
}
