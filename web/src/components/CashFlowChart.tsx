import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ArusKasResponse } from "../api/types";
import {
  cashFlowChartData,
  incomeAxisMax,
  savingsAxisMax,
  savingsPointLabel,
} from "../lib/cashflow";
import { fmtIDR, fmtPct, fmtShort } from "../lib/format";

const INK = "#1c1d26";
const CASH = "#17b26a";
const LIAB = "#f04766";
const GRID = "#eceef6";

const X_TICK = { fontSize: 11, fill: "#8a8fa3", fontFamily: "IBM Plex Mono" };
const Y_TICK = { fontSize: 10, fill: "#b4b8c9", fontFamily: "IBM Plex Mono" };
const AXIS_MARGIN = { top: 16, right: 8, left: 8, bottom: 4 };

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

/** Tooltip: rupiah for the bars, a percent for the savings line. */
function fmtValue(value: number, name: string): string {
  return name === "Tingkat menabung" ? fmtPct(value, 1) : fmtIDR(value);
}

/** The per-point `%` above each savings dot (MEASUREMENTS §Cash Flow: 10.5px / weight 600
 *  ink, 9px above the dot). Renders nothing at a line gap (a zero-income month). */
function SavingsRateLabel(props: {
  x?: number | string;
  y?: number | string;
  value?: number | string | null;
}) {
  const { x, y, value } = props;
  const text = savingsPointLabel(value == null ? null : Number(value));
  if (text === null || x === undefined || y === undefined) return null;
  return (
    <text
      x={Number(x)}
      y={Number(y) - 9}
      textAnchor="middle"
      fill={INK}
      fontSize={10.5}
      fontWeight={600}
      fontFamily="IBM Plex Mono"
    >
      {text}
    </text>
  );
}

/** The §3.5 income-vs-spend grouped bars with the savings-rate line on a secondary axis. */
export function CashFlowChart({ data }: { data: ArusKasResponse }) {
  const rows = cashFlowChartData(data.months, data.window_months);
  if (rows.length === 0) {
    return <div className="chart-empty">Belum ada data arus kas.</div>;
  }

  return (
    <div className="chartwrap">
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={AXIS_MARGIN} barGap={2} barCategoryGap="28%">
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={X_TICK} />
          <YAxis
            yAxisId="left"
            domain={[0, incomeAxisMax(rows)]}
            tickFormatter={fmtShort}
            tickLine={false}
            axisLine={false}
            width={48}
            tick={Y_TICK}
          />
          <YAxis yAxisId="right" orientation="right" domain={[0, savingsAxisMax(rows)]} hide />
          <Tooltip formatter={(value, name) => fmtValue(Number(value), String(name))} />
          <Bar
            yAxisId="left"
            dataKey="income"
            name="Pendapatan"
            fill={CASH}
            fillOpacity={0.85}
            radius={[4, 4, 0, 0]}
          />
          <Bar
            yAxisId="left"
            dataKey="spend"
            name="Belanja"
            fill={LIAB}
            fillOpacity={0.85}
            radius={[4, 4, 0, 0]}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="savings"
            name="Tingkat menabung"
            stroke={INK}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeDasharray="1 6"
            connectNulls={false}
            dot={{ r: 3.5, fill: "#fff", stroke: INK, strokeWidth: 1.5 }}
            activeDot={{ r: 4.5 }}
          >
            <LabelList dataKey="savings" content={SavingsRateLabel} />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
      <ChartLegend
        items={[
          { color: CASH, label: "Pendapatan" },
          { color: LIAB, label: "Belanja" },
          { color: INK, label: "Tingkat menabung" },
        ]}
      />
    </div>
  );
}
