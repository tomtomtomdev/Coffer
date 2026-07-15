import { useState } from "react";

import { BottomNav } from "./components/BottomNav";
import { Header } from "./components/Header";
import { monthLong } from "./lib/format";
import { useRingkasan } from "./lib/useRingkasan";
import { TABS, type ViewId } from "./nav";
import { Placeholder } from "./views/Placeholder";
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
        {state.status === "loading" && (
          <div className="view">
            <div className="card placeholder">
              <div className="placeholder__sub">Memuat…</div>
            </div>
          </div>
        )}
        {state.status === "error" && (
          <div className="view">
            <div className="card placeholder">
              <div className="placeholder__title">Gagal memuat</div>
              <div className="placeholder__sub">{state.message}</div>
            </div>
          </div>
        )}
        {state.status === "ready" &&
          (view === "overview" ? (
            <Ringkasan data={state.data} onNavigate={select} />
          ) : (
            <Placeholder title={labelOf(view)} />
          ))}
      </main>
      <BottomNav view={view} onSelect={select} />
    </div>
  );
}
