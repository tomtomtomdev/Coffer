import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { RingkasanResponse } from "../api/types";
import { axisMax, axisTicks, householdChartData, memberChartData } from "../lib/chart";
import { fmtIDR, fmtShort } from "../lib/format";

const INK = "#1c1d26";
const CASH = "#17b26a";
const PORT = "#7c5cff";
const GRID = "#eceef6";
const MEMBER_COLORS = [CASH, PORT, "#f59e0b"];

const X_TICK = { fontSize: 11, fill: "#8a8fa3", fontFamily: "IBM Plex Mono" };
const Y_TICK = { fontSize: 10, fill: "#b4b8c9", fontFamily: "IBM Plex Mono" };

function memberColor(index: number): string {
  return MEMBER_COLORS[index % MEMBER_COLORS.length] ?? PORT;
}

interface LegendItem {
  color: string;
  label: string;
}

function ChartLegend({ items }: { items: LegendItem[] }) {
  return (
    <div className="legend">
      {items.map((it) => (
        <div className="legend__item" key={it.label}>
          <span className="legend__chip" style={{ background: it.color }} />
          {it.label}
        </div>
      ))}
    </div>
  );
}

const AXIS_MARGIN = { top: 16, right: 8, left: 8, bottom: 4 };

interface Props {
  data: RingkasanResponse;
  mode: "household" | "member";
}

/** The §3.1 "tide" chart: household stacked-area + net line, or per-member lines. */
export function TideChart({ data, mode }: Props) {
  if (data.household_series.length === 0) {
    return <div className="chart-empty">Belum ada data kekayaan bersih.</div>;
  }

  if (mode === "member") {
    const { data: rows, names } = memberChartData(data.member_series);
    const max = axisMax(rows.flatMap((r) => names.map((n) => Number(r[n] ?? 0))));
    return (
      <div className="chartwrap">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={rows} margin={AXIS_MARGIN}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={X_TICK} />
            <YAxis
              domain={[0, max]}
              ticks={axisTicks(max)}
              tickFormatter={fmtShort}
              tickLine={false}
              axisLine={false}
              width={48}
              tick={Y_TICK}
            />
            <Tooltip formatter={(value) => fmtIDR(Number(value))} />
            {names.map((name, i) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={memberColor(i)}
                strokeWidth={2.5}
                dot={{ r: 3 }}
                activeDot={{ r: 4.5 }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
        <ChartLegend
          items={names.map((name, i) => ({ color: memberColor(i), label: `Bersih — ${name}` }))}
        />
      </div>
    );
  }

  const rows = householdChartData(data.household_series);
  const max = axisMax(rows.map((r) => r.cash + r.portfolio));
  return (
    <div className="chartwrap">
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={AXIS_MARGIN}>
          <defs>
            <linearGradient id="gPort" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={PORT} stopOpacity={0.26} />
              <stop offset="100%" stopColor={PORT} stopOpacity={0.03} />
            </linearGradient>
            <linearGradient id="gCash" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CASH} stopOpacity={0.3} />
              <stop offset="100%" stopColor={CASH} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={X_TICK} />
          <YAxis
            domain={[0, max]}
            ticks={axisTicks(max)}
            tickFormatter={fmtShort}
            tickLine={false}
            axisLine={false}
            width={48}
            tick={Y_TICK}
          />
          <Tooltip formatter={(value) => fmtIDR(Number(value))} />
          <Area
            type="monotone"
            dataKey="portfolio"
            stackId="assets"
            stroke={PORT}
            strokeOpacity={0.5}
            strokeWidth={1.5}
            fill="url(#gPort)"
          />
          <Area
            type="monotone"
            dataKey="cash"
            stackId="assets"
            stroke={CASH}
            strokeOpacity={0.65}
            strokeWidth={1.5}
            fill="url(#gCash)"
          />
          <Line
            type="monotone"
            dataKey="net"
            stroke={INK}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            dot={{ r: 3, fill: INK }}
            activeDot={{ r: 5 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <ChartLegend
        items={[
          { color: CASH, label: "Kas" },
          { color: PORT, label: "Portofolio" },
          { color: INK, label: "Kekayaan bersih" },
        ]}
      />
    </div>
  );
}
