import type { RingkasanResponse } from "../api/types";
import { fmtDate, fmtIDR, fmtPct, fmtShort, num } from "../lib/format";
import { TideChart } from "./TideChart";

type Mode = "household" | "member";

interface Props {
  data: RingkasanResponse;
  mode: Mode;
  onMode: (mode: Mode) => void;
}

/** The net-worth hero: eyebrow, big figure, delta pill, mode toggle, tide chart, footnote. */
export function HeroCard({ data, mode, onMode }: Props) {
  const delta = data.delta;
  const amount = delta ? num(delta.amount) : 0;
  const up = amount >= 0;

  return (
    <section className="card hero">
      <div className="hero__top">
        <div>
          <div className="eyebrow" style={{ fontSize: 11, letterSpacing: "0.14em" }}>
            Kekayaan Bersih Rumah Tangga
          </div>
          <h1 className="hero__figure">{fmtIDR(data.net_worth)}</h1>
          {delta && (
            <div className="hero__deltarow">
              <span className={`pill ${up ? "pill--up" : "pill--down"}`}>
                {up ? "↑" : "↓"} Rp {fmtShort(Math.abs(amount))}
                {delta.pct != null ? ` (${fmtPct(delta.pct, 1)})` : ""}
              </span>
              <span className="hero__deltasub">
                vs. bulan lalu{data.as_of ? ` · per ${fmtDate(data.as_of)}` : ""}
              </span>
            </div>
          )}
        </div>
        <div className="segmented" role="group" aria-label="Mode kekayaan bersih">
          <button
            type="button"
            className={`segmented__btn${mode === "household" ? " segmented__btn--active" : ""}`}
            aria-pressed={mode === "household"}
            onClick={() => onMode("household")}
          >
            Gabungan
          </button>
          <button
            type="button"
            className={`segmented__btn${mode === "member" ? " segmented__btn--active" : ""}`}
            aria-pressed={mode === "member"}
            onClick={() => onMode("member")}
          >
            Per Anggota
          </button>
        </div>
      </div>
      <TideChart data={data} mode={mode} />
      <p className="hero__footnote">
        Nilai tiap akhir bulan memakai saldo laporan terakhir yang ≤ tanggal tersebut
        (carry-forward), sehingga laporan tabungan, kartu kredit, dan broker yang tiba pada
        tanggal berbeda tetap selaras.
      </p>
    </section>
  );
}
