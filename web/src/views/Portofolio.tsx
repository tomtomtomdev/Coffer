import { useState } from "react";

import type { ConsolidatedHolding } from "../api/types";
import { ErrorCard, LoadingCard } from "../components/Status";
import { fmtDate, fmtIDR, fmtPct, num } from "../lib/format";
import { usePortofolio } from "../lib/useRingkasan";

const BROKER_LABELS: Record<string, string> = { ajaib: "Ajaib", stockbit: "Stockbit" };

function brokerLabel(institution: string): string {
  return BROKER_LABELS[institution] ?? institution;
}

function plClass(pl: number): string {
  return pl >= 0 ? "pl--pos" : "pl--neg";
}

function plPct(pl: number, cost: number): string {
  return cost > 0 ? fmtPct(pl / cost, 1) : "—";
}

/** §3.2 consolidated holdings across brokers, with the mixed-as-of-date caveat. */
export function Portofolio({ householdId }: { householdId: number }) {
  const state = usePortofolio(householdId);
  if (state.status === "loading") return <LoadingCard />;
  if (state.status === "error") return <ErrorCard message={state.message} />;

  const data = state.data;
  const totalPl = num(data.total_unrealized_pl);
  const totalCost = num(data.total_cost_basis);

  return (
    <div className="view">
      {data.mixed_as_of && (
        <div className="caveat">
          <span className="caveat__icon">⚠</span>
          <span>
            Tanggal harga campuran ({data.as_of_dates.map(fmtDate).join(" · ")}). P/L gabungan
            bersifat perkiraan — lihat rincian per broker.
          </span>
        </div>
      )}

      <div className="pcards">
        <div className="card pcard">
          <div className="kpi__eyebrow">Nilai Pasar Gabungan</div>
          <div className="pcard__figure">{fmtIDR(data.total_market_value)}</div>
        </div>
        <div className="card pcard">
          <div className="kpi__eyebrow">Unrealized P/L</div>
          <div className={`pcard__figure ${plClass(totalPl)}`}>
            {fmtIDR(data.total_unrealized_pl)}{" "}
            <span className="pcard__pct">({plPct(totalPl, totalCost)})</span>
          </div>
        </div>
      </div>

      <div className="card ptable">
        <div className="ptable__scroll">
          <div className="ptable__head">
            <span>Emiten</span>
            <span>Broker</span>
            <span>Lot</span>
            <span>Avg / Harga</span>
            <span>Nilai / P&amp;L</span>
          </div>
          {data.holdings.length === 0 ? (
            <div className="ptable__empty">Belum ada holding.</div>
          ) : (
            data.holdings.map((h) => <HoldingRow key={h.ticker} holding={h} />)
          )}
        </div>
        {data.holdings.length > 0 && (
          <div className="ptable__total">
            <span>Total Rumah Tangga</span>
            <span className="ptable__totalval">
              {fmtIDR(data.total_market_value)}
              <span className={`ptable__totalpl ${plClass(totalPl)}`}>
                {fmtIDR(data.total_unrealized_pl)} ({plPct(totalPl, totalCost)})
              </span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function HoldingRow({ holding }: { holding: ConsolidatedHolding }) {
  const [open, setOpen] = useState(false);
  const lots = num(holding.lots);
  const shares = lots * 100;
  const pl = num(holding.unrealized_pl);
  const cost = num(holding.cost_basis);
  const price = shares > 0 ? num(holding.market_value) / shares : 0;
  const multi = holding.brokers.length > 1;

  return (
    <>
      <div
        className={`ptable__row${multi ? " ptable__row--clickable" : ""}`}
        onClick={multi ? () => setOpen((o) => !o) : undefined}
      >
        <div className="ptable__emiten">
          <span className="ptable__ticker">{holding.ticker}</span>
          <span className="ptable__name">{holding.name}</span>
        </div>
        <div className="ptable__broker">
          {multi
            ? `${open ? "▾" : "▸"} ${holding.brokers.length} broker`
            : brokerLabel(holding.brokers[0]?.institution ?? "")}
        </div>
        <div className="ptable__lots">
          {lots} lot
          <span className="ptable__shares">{shares.toLocaleString("id-ID")} lbr</span>
        </div>
        <div className="ptable__avg">
          {fmtIDR(holding.avg_price)}
          <span className="ptable__price">{fmtIDR(price)}</span>
        </div>
        <div className="ptable__mv">
          {fmtIDR(holding.market_value)}
          <span className={`ptable__pl ${plClass(pl)}`}>
            {fmtIDR(holding.unrealized_pl)} ({plPct(pl, cost)})
          </span>
        </div>
      </div>
      {open &&
        holding.brokers.map((b) => (
          <div className="ptable__subrow" key={b.institution}>
            <div className="ptable__emiten ptable__sub">↳ {brokerLabel(b.institution)}</div>
            <div />
            <div className="ptable__lots">{num(b.lots)} lot</div>
            <div className="ptable__avg">{fmtIDR(b.avg_price)}</div>
            <div className="ptable__mv">
              {fmtIDR(b.market_value)}
              <span className={`ptable__pl ${plClass(num(b.unrealized_pl))}`}>
                {fmtIDR(b.unrealized_pl)}
              </span>
            </div>
          </div>
        ))}
    </>
  );
}
