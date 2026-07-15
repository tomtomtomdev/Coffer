import { useRef, useState } from "react";

import { recategorizeTransaction } from "../api/client";
import type { BelanjaResponse, CategoryMedian, CategoryOption, ReviewItem } from "../api/types";
import { ErrorCard, LoadingCard } from "../components/Status";
import { fmtDate, fmtIDR, fmtJuta, num } from "../lib/format";
import {
  badgeFor,
  cadenceFillClass,
  cadenceLabel,
  sparklineBars,
  sparklineHeights,
} from "../lib/spend";
import { useBelanja } from "../lib/useRingkasan";

const BROKER_LABELS: Record<string, string> = {
  bca: "BCA",
  cimb: "CIMB",
  ajaib: "Ajaib",
  stockbit: "Stockbit",
};

function instLabel(institution: string): string {
  return BROKER_LABELS[institution] ?? institution.toUpperCase();
}

/** §3.3 spend screen: routine hero + sparkline, per-category medians, anomalies, and the
 *  review queue with Tag/Ubah actions wired to the categorization write path. */
export function Belanja({ householdId }: { householdId: number }) {
  const [reloadKey, setReloadKey] = useState(0);
  const state = useBelanja(householdId, reloadKey);
  const last = useRef<BelanjaResponse | null>(null);
  if (state.status === "ready") last.current = state.data;

  const data = state.status === "ready" ? state.data : last.current;
  if (state.status === "error" && data === null) return <ErrorCard message={state.message} />;
  if (data === null) return <LoadingCard />;

  const reload = () => setReloadKey((k) => k + 1);

  return (
    <div className="view">
      <SpendHero data={data} />
      <CategoryMedians rows={data.category_breakdown} />
      {data.anomalies.length > 0 && <AnomalyCard data={data} />}
      <ReviewQueue data={data} onSaved={reload} />
    </div>
  );
}

function SpendHero({ data }: { data: BelanjaResponse }) {
  const bars = sparklineBars(data.monthly_series, num(data.estimate));
  const heights = sparklineHeights(bars);
  const annual = num(data.annual_amortized_monthly);

  return (
    <div className="card spendhero">
      <div className="section-title">Estimasi Belanja Rutin</div>
      {data.insufficient_data || data.estimate === null ? (
        <>
          <h1 className="spendhero__figure">—</h1>
          <p className="spendhero__explain">
            Belum cukup data (&lt; 3 bulan) untuk estimasi. Terkumpul {data.months_observed} bulan.
          </p>
        </>
      ) : (
        <>
          <h1 className="spendhero__figure">Rp {fmtJuta(num(data.base_median_monthly))}</h1>
          <p className="spendhero__explain">
            median dari total bulanan
            {annual > 0 && (
              <>
                {" · + "}
                <strong>Rp {fmtJuta(annual)}</strong> amortisasi tahunan ={" "}
                <strong>Rp {fmtJuta(num(data.estimate))}</strong>/bln
              </>
            )}
          </p>
          <div className="spark">
            {bars.map((bar, i) => (
              <div className="spark__col" key={bar.label + i}>
                <div
                  className={`spark__bar${bar.high ? " spark__bar--high" : ""}`}
                  style={{ height: `${heights[i]}%` }}
                  title={fmtIDR(bar.value)}
                />
                <span className="spark__label">{bar.label}</span>
              </div>
            ))}
          </div>
        </>
      )}
      <div className="hero__footnote">
        Rincian per-kategori memakai median masing-masing; jumlahnya <em>tidak</em> harus sama
        dengan angka utama (kategori jarang memuncak di bulan yang sama). Cold-start: &lt; 3 bulan
        data ⇒ tidak menampilkan estimasi.
      </div>
    </div>
  );
}

function CategoryMedians({ rows }: { rows: CategoryMedian[] }) {
  const max = rows.reduce((a, r) => Math.max(a, num(r.median_monthly)), 0);
  return (
    <div className="card rincian">
      <div className="section-title">Rincian per Kategori · Median Bulanan</div>
      {rows.length === 0 ? (
        <div className="ptable__empty">Belum ada kategori rutin.</div>
      ) : (
        rows.map((r) => {
          const pct = max > 0 ? (num(r.median_monthly) / max) * 100 : 0;
          return (
            <div className="catrow" key={r.category_id}>
              <div className="catrow__head">
                <span className="catrow__label">{r.label}</span>
                <span className="cadence-tag">{cadenceLabel(r.cadence)}</span>
                <span className="catrow__median">{fmtIDR(r.median_monthly)}</span>
              </div>
              <div className="cattrack">
                <div
                  className={`catfill ${cadenceFillClass(r.cadence)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

function AnomalyCard({ data }: { data: BelanjaResponse }) {
  return (
    <div className="card anomaly">
      <div className="anomaly__title">Perlu Ditinjau — kemungkinan bukan rutin</div>
      {data.anomalies.map((a) => (
        <div className="anomaly__row" key={a.transaction_id}>
          <div>
            <div className="anomaly__desc">{a.description}</div>
            <div className="anomaly__reason">
              {a.category_label} · median {fmtIDR(a.category_median)}
            </div>
          </div>
          <span className="anomaly__amt">{fmtIDR(a.amount)}</span>
        </div>
      ))}
    </div>
  );
}

function ReviewQueue({ data, onSaved }: { data: BelanjaResponse; onSaved: () => void }) {
  return (
    <div className="card rincian">
      <div className="section-title">Antrian Tinjauan</div>
      {data.review_queue.length === 0 ? (
        <div className="ptable__empty">Tidak ada transaksi untuk ditinjau.</div>
      ) : (
        data.review_queue.map((item) => (
          <ReviewRow
            key={item.transaction_id}
            item={item}
            categories={data.categories}
            onSaved={onSaved}
          />
        ))
      )}
    </div>
  );
}

function ReviewRow({
  item,
  categories,
  onSaved,
}: {
  item: ReviewItem;
  categories: CategoryOption[];
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<number>(item.category_id ?? categories[0]?.id ?? 0);
  const [generalize, setGeneralize] = useState(false);

  const badge = badgeFor(item.category_source);
  const amount = num(item.debit) > 0 ? item.debit : item.credit;
  const uncategorized = item.category_id === null;
  const canGeneralize = item.counterparty_acct !== null;

  const save = async () => {
    if (categoryId <= 0) return;
    setSaving(true);
    setError(null);
    try {
      await recategorizeTransaction(item.transaction_id, {
        category_id: categoryId,
        generalize: generalize && canGeneralize ? "counterparty_acct" : null,
      });
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menyimpan");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`reviewrow${item.is_anomaly ? " reviewrow--flag" : ""}`}>
      <div className="reviewrow__top">
        <div className="reviewrow__main">
          <div className="reviewrow__desc">{item.description}</div>
          <div className="reviewrow__meta">
            <span className={`badge ${badge.cls}`}>{badge.label}</span>
            {item.category_label && <span className="reviewrow__cat">{item.category_label}</span>}
            <span className="reviewrow__acct">
              {instLabel(item.institution)} · {fmtDate(item.date)}
            </span>
          </div>
        </div>
        <div className="reviewrow__right">
          <span className="reviewrow__amt">{fmtIDR(amount)}</span>
          <button
            type="button"
            className={`reviewrow__action ${uncategorized ? "action--tag" : "action--ubah"}`}
            onClick={() => setEditing((e) => !e)}
          >
            {uncategorized ? "Tag →" : "Ubah"}
          </button>
        </div>
      </div>
      {editing && (
        <div className="retag">
          <select
            className="retag__select"
            aria-label="Pilih kategori"
            value={categoryId}
            onChange={(e) => setCategoryId(Number(e.target.value))}
          >
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
          {canGeneralize && (
            <label className="retag__gen">
              <input
                type="checkbox"
                checked={generalize}
                onChange={(e) => setGeneralize(e.target.checked)}
              />
              Terapkan ke transaksi berikutnya ke akun ini
            </label>
          )}
          <div className="retag__actions">
            <button type="button" className="retag__save" onClick={save} disabled={saving}>
              {saving ? "Menyimpan…" : "Simpan"}
            </button>
            <button
              type="button"
              className="retag__cancel"
              onClick={() => setEditing(false)}
              disabled={saving}
            >
              Batal
            </button>
          </div>
          {error && <div className="retag__error">{error}</div>}
        </div>
      )}
    </div>
  );
}
