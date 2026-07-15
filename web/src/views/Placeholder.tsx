/** Stub for the not-yet-built tabs (Portofolio / Belanja / Arus Kas → S12–S14). */
export function Placeholder({ title }: { title: string }) {
  return (
    <div className="view">
      <div className="card placeholder">
        <div className="placeholder__title">{title}</div>
        <div className="placeholder__sub">Layar ini hadir di slice berikutnya (S12–S14).</div>
      </div>
    </div>
  );
}
