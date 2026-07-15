/*
 * Pure presentation helpers for the Belanja (§3.3) view — sparkline shaping, source-badge
 * and cadence labels. No React, no money math beyond parsing the wire strings; kept
 * separate so it is unit-testable. Bahasa copy lives here (at the UI edge, per CLAUDE.md).
 */
import type { CategorySource, MonthlyRoutinePoint } from "../api/types";
import { monthShort, num } from "./format";

export interface SparkBar {
  label: string;
  value: number;
  /** A "high" month — total above the routine estimate — rendered in the liability colour
   *  (mirrors the frozen design's tall rose bar). Green otherwise. */
  high: boolean;
}

/** Sparkline bars for the routine-spend hero. `estimate` is the headline (base + annual);
 *  a month whose total exceeds it reads as an above-typical month. */
export function sparklineBars(series: MonthlyRoutinePoint[], estimate: number): SparkBar[] {
  return series.map((p) => {
    const value = num(p.total);
    return { label: monthShort(p.month), value, high: estimate > 0 && value > estimate };
  });
}

/** Bar heights as 0–100% of the tallest bar (flex-end aligned), for the CSS height. */
export function sparklineHeights(bars: SparkBar[]): number[] {
  const max = bars.reduce((a, b) => Math.max(a, b.value), 0);
  return bars.map((b) => (max > 0 ? Math.round((b.value / max) * 100) : 0));
}

export interface Badge {
  label: string;
  cls: string;
}

const SOURCE_BADGE: Record<CategorySource, Badge> = {
  parser: { label: "Parser", cls: "badge--parser" },
  learned_rule: { label: "Auto · pelajaran", cls: "badge--learned" },
  manual: { label: "Manual", cls: "badge--manual" },
  onboarding: { label: "Onboarding", cls: "badge--manual" },
};

/** The review-queue source badge; `null` source ⇒ uncategorized ("Perlu tag"). */
export function badgeFor(source: CategorySource | null): Badge {
  return source == null ? { label: "Perlu tag", cls: "badge--needs" } : SOURCE_BADGE[source];
}

const CADENCE_LABEL: Record<string, string> = {
  monthly: "Bulanan",
  annual: "Tahunan",
  irregular: "Tidak Tentu",
};

export function cadenceLabel(cadence: string): string {
  return CADENCE_LABEL[cadence] ?? cadence;
}

/** The progress-fill colour class for a per-category median bar. */
export function cadenceFillClass(cadence: string): string {
  return cadence === "annual" ? "catfill--annual" : "catfill--monthly";
}
