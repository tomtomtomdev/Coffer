import { TABS, type ViewId } from "../nav";

interface Props {
  view: ViewId;
  onSelect: (view: ViewId) => void;
  monthLabel: string;
}

/** Sticky top header: avatar stack, wordmark, centred top-nav, month chip (SPEC §5). */
export function Header({ view, onSelect, monthLabel }: Props) {
  return (
    <header className="header">
      <div className="header__row">
        <div className="avatars">
          <div className="avatar avatar--t">T</div>
          <div className="avatar avatar--p">P</div>
        </div>
        <div className="brand">
          <span className="brand__mark">Coffer</span>
          <span className="brand__sub">Tommy &amp; Priskila</span>
        </div>
        <nav className="topnav" aria-label="Navigasi utama">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`topnav__tab${view === tab.id ? " topnav__tab--active" : ""}`}
              aria-current={view === tab.id ? "page" : undefined}
              onClick={() => onSelect(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="monthchip">
          <span className="monthchip__dot" />
          {monthLabel}
        </div>
      </div>
    </header>
  );
}
