import { describe, expect, it } from "vitest";

import type { GridPoint, MemberSeries } from "../api/types";
import { axisMax, axisTicks, householdChartData, memberChartData } from "./chart";

function gp(grid: string, cash: string, portfolio: string, net: string): GridPoint {
  return { grid_date: grid, cash, portfolio, liability: "0", net_worth: net };
}

describe("householdChartData", () => {
  it("maps snapshot rows to stacked-area + net numbers with month labels", () => {
    const data = householdChartData([
      gp("2026-05-31", "140", "300", "420"),
      gp("2026-06-30", "205", "350", "525"),
    ]);
    expect(data).toEqual([
      { label: "Mei", cash: 140, portfolio: 300, net: 420 },
      { label: "Jun", cash: 205, portfolio: 350, net: 525 },
    ]);
  });
});

describe("memberChartData", () => {
  it("pivots per-member points into one numeric column per member", () => {
    const members: MemberSeries[] = [
      {
        member_id: 1,
        member_name: "Tommy",
        points: [
          { grid_date: "2026-05-31", net_worth: "80" },
          { grid_date: "2026-06-30", net_worth: "120" },
        ],
      },
      {
        member_id: 2,
        member_name: "Priskila",
        points: [
          { grid_date: "2026-05-31", net_worth: "40" },
          { grid_date: "2026-06-30", net_worth: "55" },
        ],
      },
    ];
    const { data, names } = memberChartData(members);
    expect(names).toEqual(["Tommy", "Priskila"]);
    expect(data).toEqual([
      { label: "Mei", Tommy: 80, Priskila: 40 },
      { label: "Jun", Tommy: 120, Priskila: 55 },
    ]);
  });

  it("is empty for no members", () => {
    expect(memberChartData([])).toEqual({ data: [], names: [] });
  });
});

describe("axis", () => {
  it("tops out at 1.15× the max value", () => {
    expect(axisMax([100, 420, 200])).toBeCloseTo(483);
  });

  it("falls back to 1 when all values are zero", () => {
    expect(axisMax([0, 0])).toBe(1);
  });

  it("splits into 0 / ⅓ / ⅔ / max gridlines", () => {
    expect(axisTicks(300)).toEqual([0, 100, 200, 300]);
  });
});
