/*
 * Pure transforms from the API payload to Recharts row data. No React, no formatting
 * beyond month labels — kept separate so the chart shaping is unit-testable.
 */
import type { GridPoint, MemberSeries } from "../api/types";
import { monthShort, num } from "./format";

export interface HouseholdDatum {
  label: string;
  cash: number;
  portfolio: number;
  net: number;
}

/** Household tide rows: stacked portfolio + cash areas with the net-worth line. */
export function householdChartData(series: GridPoint[]): HouseholdDatum[] {
  return series.map((p) => ({
    label: monthShort(p.grid_date),
    cash: num(p.cash),
    portfolio: num(p.portfolio),
    net: num(p.net_worth),
  }));
}

export type MemberDatum = { label: string } & Record<string, number | string>;

/** Per-member rows: one numeric column per member (aligned to the shared grid). */
export function memberChartData(members: MemberSeries[]): {
  data: MemberDatum[];
  names: string[];
} {
  const names = members.map((m) => m.member_name);
  const first = members[0];
  if (!first) return { data: [], names };
  const data = first.points.map((p, i) => {
    const row: MemberDatum = { label: monthShort(p.grid_date) };
    for (const m of members) {
      row[m.member_name] = num(m.points[i]?.net_worth ?? "0");
    }
    return row;
  });
  return { data, names };
}

/** Y-axis top = 1.15 × the largest value (SPEC tide-chart headroom). */
export function axisMax(values: number[]): number {
  const max = values.reduce((a, b) => Math.max(a, b), 0);
  return max <= 0 ? 1 : max * 1.15;
}

/** 4 gridlines at 0 / ⅓ / ⅔ / max (MEASUREMENTS.md tide chart). */
export function axisTicks(maxValue: number): number[] {
  return [0, maxValue / 3, (maxValue * 2) / 3, maxValue];
}
