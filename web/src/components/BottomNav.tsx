import { TABS, type ViewId } from "../nav";

interface Props {
  view: ViewId;
  onSelect: (view: ViewId) => void;
}

/** Fixed bottom nav shown ≤860px (mirrors the four tabs with a colored top-mark). */
export function BottomNav({ view, onSelect }: Props) {
  return (
    <nav className="botnav" aria-label="Navigasi bawah">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`botnav__item${view === tab.id ? " botnav__item--active" : ""}`}
          aria-current={view === tab.id ? "page" : undefined}
          onClick={() => onSelect(tab.id)}
        >
          <span className="botnav__mark" />
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
