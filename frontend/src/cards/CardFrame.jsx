// Bingkai satu kartu Beranda (Plugin B2): error boundary, kerangka saat memuat, dan pesan galat
// dari server (`{"error": {"kode", "detail"}}` di POST /dashboard/data). Satu kartu yang rusak tidak
// merusak Beranda.
import { Component } from 'react';

class Batas extends Component {
  constructor(props) {
    super(props);
    this.state = { rusak: false };
  }

  static getDerivedStateFromError() {
    return { rusak: true };
  }

  componentDidCatch(error) {
    console.error('Kartu Beranda gagal digambar', this.props.cardKey, error);
  }

  render() {
    if (this.state.rusak) return <Pesan teks="Kartu ini belum bisa ditampilkan." />;
    return this.props.children;
  }
}

function Pesan({ teks, judul }) {
  return (
    <section className="card !px-4 md:!px-6 !py-5 min-w-0" role="status">
      {judul && <h2 className="font-display font-bold text-lg mb-1" style={{ color: 'var(--text)' }}>{judul}</h2>}
      <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{teks}</p>
    </section>
  );
}

export function Kerangka({ kind }) {
  return (
    <div aria-hidden="true" className="card animate-pulse min-w-0"
      style={{ minHeight: kind === 'kpi' ? 112 : kind === 'link' ? 24 : 220, opacity: 0.6 }} />
  );
}

export default function CardFrame({ def, entri, judul, children }) {
  if (entri === undefined) return <Kerangka kind={def.kind} />;
  if (entri?.error) return def.kind === 'link' ? null : <Pesan judul={judul} teks={entri.error.detail} />;
  return <Batas cardKey={def.key}>{children}</Batas>;
}
