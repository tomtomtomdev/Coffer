import { useState } from "react";

import { BottomNav } from "./components/BottomNav";
import { Header } from "./components/Header";
import { ErrorCard, LoadingCard } from "./components/Status";
import { monthLong } from "./lib/format";
import { useRingkasan } from "./lib/useRingkasan";
import { TABS, type ViewId } from "./nav";
import { Placeholder } from "./views/Placeholder";
import { Portofolio } from "./views/Portofolio";
import { Ringkasan } from "./views/Ringkasan";

// Single shared household (SPEC §5 — one login, two members).
const HOUSEHOLD_ID = 1;

function labelOf(view: ViewId): string {
  return TABS.find((t) => t.id === view)?.label ?? "";
}

export function App() {
  const [view, setView] = useState<ViewId>("overview");
  const state = useRingkasan(HOUSEHOLD_ID);

  const select = (next: ViewId) => {
    setView(next);
    window.scrollTo({ top: 0 });
  };

  const monthLabel =
    state.status === "ready" && state.data.as_of ? monthLong(state.data.as_of) : "—";

  return (
    <div className="app">
      <Header view={view} onSelect={select} monthLabel={monthLabel} />
      <main className="main">
        {view === "overview" &&
          (state.status === "loading" ? (
            <LoadingCard />
          ) : state.status === "error" ? (
            <ErrorCard message={state.message} />
          ) : (
            <Ringkasan data={state.data} onNavigate={select} />
          ))}
        {view === "portfolio" && <Portofolio householdId={HOUSEHOLD_ID} />}
        {(view === "spend" || view === "cashflow") && <Placeholder title={labelOf(view)} />}
      </main>
      <BottomNav view={view} onSelect={select} />
    </div>
  );
}
