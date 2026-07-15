/** Shared loading / error cards for the dashboard views. */
export function LoadingCard() {
  return (
    <div className="view">
      <div className="card placeholder">
        <div className="placeholder__sub">Memuat…</div>
      </div>
    </div>
  );
}

export function ErrorCard({ message }: { message: string }) {
  return (
    <div className="view">
      <div className="card placeholder">
        <div className="placeholder__title">Gagal memuat</div>
        <div className="placeholder__sub">{message}</div>
      </div>
    </div>
  );
}
