import { useState } from "react";

import type { RingkasanResponse } from "../api/types";
import { HeroCard } from "../components/HeroCard";
import { KpiRow } from "../components/KpiRow";
import { RincianAkun } from "../components/RincianAkun";
import type { ViewId } from "../nav";

interface Props {
  data: RingkasanResponse;
  onNavigate: (view: ViewId) => void;
}

/** §3.1 overview: net-worth hero + tide chart, KPI row, Rincian Akun.
 * (A §3.4 bill due-date card will slot in here once placement is confirmed.) */
export function Ringkasan({ data, onNavigate }: Props) {
  const [mode, setMode] = useState<"household" | "member">("household");

  return (
    <div className="view">
      <HeroCard data={data} mode={mode} onMode={setMode} />
      <KpiRow kpis={data.kpis} onNavigate={onNavigate} />
      <RincianAkun accounts={data.accounts} members={data.member_series} />
    </div>
  );
}
