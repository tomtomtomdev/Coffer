import { describe, expect, it } from "vitest";

import type { MonthlyCashFlow } from "../api/types";
import { cashFlowChartData, incomeAxisMax, savingsAxisMax, spendTypeLabel } from "./cashflow";

function month(m: string, income: string, spend: string, savings: string | null): MonthlyCashFlow {
  return {
    month: m,
    income,
    spend,
    cash_flow: String(Number(income) - Number(spend)),
    savings_rate: savings,
  };
}

const SERIES: MonthlyCashFlow[] = [
  month("2026-01-01", "58000000", "34000000", "0.4137931"),
  month("2026-02-01", "61000000", "33000000", "0.4590163"),
  month("2026-03-01", "60000000", "36000000", "0.4"),
  month("2026-04-01", "63000000", "32000000", "0.4920634"),
  month("2026-05-01", "62000000", "39000000", "0.3709677"),
  month("2026-06-01", "66000000", "34000000", "0.4848484"),
  month("2026-07-01", "70000000", "40000000", "0.4285714"),
];

describe("cashFlowChartData", () => {
  it("limits to the last `windowMonths` and shapes rows", () => {
    const rows = cashFlowChartData(SERIES, 6);
    expect(rows).toHaveLength(6);
    expect(rows[0]?.label).toBe("Feb"); // Jan dropped by the 6-month window
    expect(rows[5]).toEqual({ label: "Jul", income: 70000000, spend: 40000000, savings: 0.4285714 });
  });

  it("maps a null savings rate (zero-income month) to a line gap", () => {
    const rows = cashFlowChartData([month("2026-06-01", "0", "500000", null)], 6);
    expect(rows[0]?.savings).toBeNull();
    expect(rows[0]?.income).toBe(0);
  });
});

describe("axis maxima", () => {
  it("income axis is 1.22 × the largest bar (income or spend)", () => {
    const rows = cashFlowChartData(SERIES, 6);
    // window is Feb–Jul (Jan dropped); the largest income in-window is Jul's 70M.
    expect(incomeAxisMax(rows)).toBeCloseTo(70000000 * 1.22);
  });

  it("savings axis has headroom, capped at 100% and floored when empty", () => {
    const rows = cashFlowChartData(SERIES, 6);
    expect(savingsAxisMax(rows)).toBeCloseTo(0.4920634 * 1.25);
    expect(savingsAxisMax([])).toBe(0.1);
    // a very high rate is clamped to 1 (100%).
    const hot = cashFlowChartData([month("2026-06-01", "100", "5", "0.95")], 6);
    expect(savingsAxisMax(hot)).toBe(1);
  });
});

describe("spendTypeLabel", () => {
  it("maps spend types to the frozen design copy", () => {
    expect(spendTypeLabel("routine")).toBe("Rutin");
    expect(spendTypeLabel("discretionary")).toBe("Discretionary");
    expect(spendTypeLabel("one_off")).toBe("One-off");
    expect(spendTypeLabel("mystery")).toBe("mystery");
  });
});
