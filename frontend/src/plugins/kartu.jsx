// Kartu Beranda Fitur Tambahan (Plugin H3). Kartu plugin yang aktif di ruang ini (GET /plugins/contributions `cards`)
// didaftarkan ke CardRegistry: komponen kustom dari `src/plugins/<id>/cards.js` bila ada (lazy), selain itu renderer
// bentuk deklaratif. Daftar diganti utuh setiap kontribusi berubah, jadi kartu plugin yang dijeda, dicopot, atau
// dimatikan server tidak pernah tergambar walau tata letak lama masih menyebutnya.
import { Component, Suspense } from 'react';
import { gantiKartuPlugin } from '../cards/CardRegistry';
import { Kerangka } from '../cards/CardFrame';
import KartuDeklaratif from '../cards/plugin/KartuDeklaratif';
import { namaPlugin } from '../lib/pluginHost';
import { webPlugin } from './index';

// Kartu plugin dimuat ulang setelah pencatatan dan perubahan amplop, seperti kartu inti yang memakai angka ruang.
const REFRESH = ['jatahku:txn-added', 'jatahku:envelope-updated'];

class BatasKustom extends Component {
  constructor(props) {
    super(props);
    this.state = { rusak: false };
  }

  static getDerivedStateFromError() {
    return { rusak: true };
  }

  render() {
    // Potongan kode plugin gagal diunduh (offline, versi lama): bentuk deklaratif dari server tetap tergambar.
    return this.state.rusak ? this.props.cadangan : this.props.children;
  }
}

export function daftarkanKartuPlugin(kontribusi) {
  const defs = (kontribusi?.cards || []).map((c) => {
    const kind = c.shape === 'kpi' ? 'kpi' : 'card';
    const sumber = namaPlugin(kontribusi, c.plugin);
    const Kustom = webPlugin(c.plugin)?.kartu?.[c.key] || null;
    const Deklaratif = (props) => <KartuDeklaratif {...props} kartu={c} sumber={sumber} />;
    const Kartu = Kustom
      ? (props) => (
        <BatasKustom cadangan={<Deklaratif {...props} />}>
          <Suspense fallback={<Kerangka kind={kind} />}><Kustom {...props} kartu={c} /></Suspense>
        </BatasKustom>
      )
      : Deklaratif;
    return { key: c.key, kind, refreshOn: REFRESH, plugin: c.plugin, Component: Kartu };
  });
  gantiKartuPlugin(defs);
}
