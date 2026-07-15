import { describe, expect, it } from "vitest";

import type { MonthlyRoutinePoint } from "../api/types";
import {
  badgeFor,
  cadenceFillClass,
  cadenceLabel,
  sparklineBars,
  sparklineHeights,
} from "./spend";

const series: MonthlyRoutinePoint[] = [
  { month: "2026-01-01", total: "20000000" },
  { month: "2026-05-01", total: "30000000" },
  { month: "2026-06-01", total: "24000000" },
];

describe("sparklineBars", () => {
  it("labels months and flags totals above the estimate as high", () => {
    const bars = sparklineBars(series, 25_670_000);
    expect(bars.map((b) => b.label)).toEqual(["Jan", "Mei", "Jun"]);
    expect(bars.map((b) => b.high)).toEqual([false, true, false]);
  });

  it("flags nothing when the estimate is zero (cold start)", () => {
    expect(sparklineBars(series, 0).every((b) => !b.high)).toBe(true);
  });
});

describe("sparklineHeights", () => {
  it("scales each bar to a percent of the tallest", () => {
    const bars = sparklineBars(series, 0);
    expect(sparklineHeights(bars)).toEqual([67, 100, 80]);
  });

  it("is all-zero with no data", () => {
    expect(sparklineHeights([])).toEqual([]);
  });
});

describe("badgeFor", () => {
  it("maps each source to its badge, null → needs-tag", () => {
    expect(badgeFor(null)).toEqual({ label: "Perlu tag", cls: "badge--needs" });
    expect(badgeFor("parser").label).toBe("Parser");
    expect(badgeFor("learned_rule").label).toBe("Auto · pelajaran");
    expect(badgeFor("manual").label).toBe("Manual");
  });
});

describe("cadence helpers", () => {
  it("localises cadence labels", () => {
    expect(cadenceLabel("monthly")).toBe("Bulanan");
    expect(cadenceLabel("annual")).toBe("Tahunan");
    expect(cadenceLabel("irregular")).toBe("Tidak Tentu");
  });

  it("colours annual fills orange, others green", () => {
    expect(cadenceFillClass("annual")).toBe("catfill--annual");
    expect(cadenceFillClass("monthly")).toBe("catfill--monthly");
  });
});
