// Rute `/p/<id>/*` (Plugin H3; 01-kajian.md "Katalog titik ekstensi" `pages`). Halaman plugin hanya digambar bila
// plugin itu aktif di ruang ini untuk user ini (GET /plugins/contributions); komponennya dimuat lazy dari
// `src/plugins/<id>`. Data halaman tetap diperiksa server di setiap permintaan, jadi pemeriksaan di sini hanya tampilan.
import { Component, Suspense } from 'react';
import { Link, useOutletContext, useParams } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { RUTE_FITUR, pluginAktif } from '../lib/pluginHost';
import { webPlugin } from './index';

class Batas extends Component {
  constructor(props) {
    super(props);
    this.state = { rusak: false };
  }

  static getDerivedStateFromError() {
    return { rusak: true };
  }

  componentDidCatch(error) {
    console.error('Halaman Fitur Tambahan gagal digambar', this.props.pluginId, error);
  }

  render() {
    if (this.state.rusak) {
      return <Pesan judul="Halaman ini belum bisa dibuka" isi="Periksa koneksi, lalu muat ulang Jatahku." />;
    }
    return this.props.children;
  }
}

function Pesan({ judul, isi, tautan }) {
  return (
    <section className="card !px-5 !py-8 max-w-xl mx-auto text-center" role="status">
      <span className="inline-flex w-12 h-12 rounded-2xl items-center justify-center mb-3"
        style={{ background: 'rgba(148,163,184,0.14)', color: 'var(--text-muted)' }}>
        <Icon name="puzzle" size={24} />
      </span>
      <h1 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>{judul}</h1>
      <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>{isi}</p>
      {tautan && (
        <Link to={tautan.to} className="btn-outline inline-flex mt-5">{tautan.label}</Link>
      )}
    </section>
  );
}

export default function PluginPage() {
  const { pluginId, '*': subpath = '' } = useParams();
  const { plugin, akses } = useOutletContext() || {};
  if (!plugin?.siap) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const aktif = pluginAktif(plugin.kontribusi, pluginId);
  if (!aktif) {
    return (
      <Pesan judul="Fitur Tambahan ini tidak aktif di ruang ini"
        isi="Mungkin sedang dijeda, sudah dicopot, atau dipasang di ruang lain. Pilih ruang yang benar, atau pasang dari halaman Fitur Tambahan."
        tautan={plugin.katalogAda && !akses?.karyawan ? { to: RUTE_FITUR, label: 'Buka Fitur Tambahan' } : { to: '/', label: 'Ke Beranda' }} />
    );
  }
  const Halaman = webPlugin(pluginId)?.halaman;
  if (!Halaman) {
    return (
      <Pesan judul={aktif.nama} isi="Halaman ini belum ada di versi aplikasi yang kamu pakai. Perbarui Jatahku, lalu buka lagi."
        tautan={{ to: '/', label: 'Ke Beranda' }} />
    );
  }
  return (
    <Batas pluginId={pluginId}>
      <Suspense fallback={<div className="text-center py-12 text-gray-400">Loading...</div>}>
        <Halaman subpath={subpath} plugin={aktif} />
      </Suspense>
    </Batas>
  );
}
