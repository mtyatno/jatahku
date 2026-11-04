// Kartu Beranda template "Karyawan" (Plugin R6; 05-desain-buku-usaha.md B4.3, artboard "Karyawan: Beranda di ruang
// usaha"). Data dari POST /dashboard/data, hanya milik karyawan itu sendiri; server menolak kartu lain untuknya.
// Komponen hanya memformat (AGENTS.md "Plugin dan ruang" aturan 6). Tanpa kartu laba, kas, atau saldo amplop.
import { registerCard } from '../CardRegistry';
import { Icon, EnvelopeIcon } from '../../components/Icon';
import { formatCurrency } from '../../lib/utils';
import { labelStatusDraf, ringkasBatasan } from '../../lib/ruangPeran';
import { api } from '../../lib/api';

const TXN = ['jatahku:txn-added'];
const DRAF = ['jatahku:txn-added', 'jatahku:draf-baru'];
const arr = (v) => (Array.isArray(v) ? v : []);

function Kartu({ judul, aksi, children, className = '' }) {
  return (
    <section className={`card !px-4 md:!px-6 !py-5 min-w-0 h-full ${className}`}>
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>{judul}</h2>
        {aksi}
      </div>
      {children}
    </section>
  );
}

function Kosong({ children }) {
  return <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{children}</p>;
}

const jam = (iso) => {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
};

const bukaCatat = (jenis) => window.dispatchEvent(new CustomEvent('jatahku:open-action', {
  detail: jenis === 'penjualan' ? 'income' : 'expense',
}));

// Warna status per tema (kontras ≥ 4,5:1 di terang dan gelap, desain A2 butir 10).
const TONE = {
  menunggu: [{ bg: '#FEF3C7', fg: '#92400E' }, { bg: '#2d1f00', fg: '#fbbf24' }],
  disetujui: [{ bg: '#DCFCE7', fg: '#166534' }, { bg: '#052e16', fg: '#86efac' }],
  ditolak: [{ bg: '#FEE2E2', fg: '#B91C1C' }, { bg: '#450a0a', fg: '#fca5a5' }],
  dibatalkan: [{ bg: '#F1F5F9', fg: '#475569' }, { bg: '#1e293b', fg: '#94a3b8' }],
};
TONE.diproses = TONE.menunggu;

function Status({ status, isDark }) {
  const t = (TONE[status] || TONE.dibatalkan)[isDark ? 1 : 0];
  return (
    <span className="shrink-0 text-[11px] font-semibold rounded-full px-2 py-0.5" style={{ background: t.bg, color: t.fg }}>
      {labelStatusDraf(status)}
    </span>
  );
}

registerCard({
  key: 'core.karyawan.catat',
  Component: function KartuCatat({ entri, ctx }) {
    const jenis = arr(entri.jenis_catatan);
    return (
      <Kartu judul={`Catat di ${ctx.ruangNama || 'ruang ini'}`}>
        {jenis.length === 0 ? (
          <Kosong>Admin belum mengizinkanmu mencatat di ruang ini.</Kosong>
        ) : (
          <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${jenis.length}, minmax(0,1fr))` }}>
            {jenis.map(j => (
              <button key={j} type="button" onClick={() => bukaCatat(j)}
                className="rounded-xl px-4 py-3 text-left transition-opacity hover:opacity-90"
                style={j === 'penjualan'
                  ? { background: 'rgba(29,158,117,0.12)', color: 'var(--text)', border: '1px solid rgba(29,158,117,0.35)' }
                  : { background: 'var(--brand-400)', color: '#0f172a' }}>
                <Icon name={j === 'penjualan' ? 'income' : 'expense'} size={20} />
                <span className="block font-bold mt-1">{j === 'penjualan' ? 'Penjualan' : 'Pengeluaran'}</span>
              </button>
            ))}
          </div>
        )}
        {arr(entri.amplop).length > 0 && (
          <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
            Amplop untukmu: {arr(entri.amplop).map(a => a.nama).join(', ')}
          </p>
        )}
      </Kartu>
    );
  },
});

registerCard({
  key: 'core.karyawan.hari_ini', refreshOn: TXN,
  Component: function KartuHariIni({ entri }) {
    const jenis = arr(entri.jenis_catatan);
    const kotak = [
      ['pengeluaran', 'Pengeluaranku', entri.pengeluaran],
      ['penjualan', 'Penjualanku', entri.penjualan],
    ].filter(([j, , v]) => jenis.includes(j) || (v?.jumlah || 0) > 0);
    return (
      <Kartu judul="Hari ini">
        <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.max(1, kotak.length)}, minmax(0,1fr))` }}>
          {kotak.map(([j, label, v]) => (
            <div key={j} className="rounded-xl px-3 py-3" style={{ background: 'var(--page)', border: '1px solid var(--border)' }}>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</p>
              <p className="font-display font-bold text-xl mt-0.5" style={{ color: 'var(--text)' }}>
                {formatCurrency(v?.total || 0)}
              </p>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{v?.jumlah || 0} catatan</p>
            </div>
          ))}
        </div>
      </Kartu>
    );
  },
});

registerCard({
  key: 'core.karyawan.menunggu', refreshOn: DRAF,
  Component: function KartuMenunggu({ entri, ctx }) {
    const items = arr(entri.items);
    return (
      <Kartu judul="Menunggu persetujuan"
        aksi={entri.menunggu > 0 ? (
          <span className="shrink-0 min-w-[22px] h-[22px] px-1.5 rounded-full text-xs font-bold inline-flex items-center justify-center"
            style={{ background: '#DC2626', color: '#fff' }} aria-label={`${entri.menunggu} menunggu persetujuan`}>
            {entri.menunggu}
          </span>
        ) : null}>
        {items.length === 0 ? (
          <Kosong>Tidak ada catatan yang menunggu admin. Catatan di atas batasmu akan muncul di sini.</Kosong>
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {items.map(d => (
              <li key={d.id} className="py-2.5 flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>{d.judul}</p>
                  <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                    {d.jenis === 'penjualan' ? 'Penjualan' : 'Pengeluaran'} · {formatCurrency(d.nominal)}
                    {d.status === 'ditolak' && d.subjudul ? ` · ${d.subjudul}` : ''}
                  </p>
                </div>
                <Status status={d.status} isDark={ctx?.isDark} />
              </li>
            ))}
          </ul>
        )}
      </Kartu>
    );
  },
});

function HapusCatatan({ id }) {
  const hapus = async () => {
    if (!window.confirm('Hapus catatan ini?')) return;
    if (await api.deleteTransaction(id)) window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
    else window.alert('Catatan ini tidak bisa dihapus lagi. Minta admin bila perlu.');
  };
  return (
    <button type="button" onClick={hapus} aria-label="Hapus catatan" title="Hapus"
      className="shrink-0 w-8 h-8 rounded-lg inline-flex items-center justify-center hover:bg-black/5"
      style={{ color: 'var(--text-muted)' }}>
      <Icon name="trash" size={16} />
    </button>
  );
}

registerCard({
  key: 'core.karyawan.catatan_hari_ini', refreshOn: TXN,
  Component: function KartuCatatanHariIni({ entri }) {
    const items = arr(entri.items);
    const lebih = (entri.total_item || 0) - items.length;
    return (
      <Kartu judul="Catatanku hari ini">
        {items.length === 0 ? (
          <Kosong>Belum ada catatan hari ini.</Kosong>
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {items.map(c => (
              <li key={`${c.jenis}-${c.id}`} className="py-2.5 flex items-center gap-3">
                <span className="shrink-0 w-8 h-8 rounded-lg inline-flex items-center justify-center"
                  style={{ background: c.jenis === 'penjualan' ? 'rgba(29,158,117,0.12)' : 'var(--page)' }}>
                  {c.jenis === 'penjualan' || !c.emoji
                    ? <Icon name={c.jenis === 'penjualan' ? 'income' : 'expense'} size={16} />
                    : <EnvelopeIcon value={c.emoji} size={16} />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>{c.judul}</p>
                  <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                    {[c.subjudul, jam(c.waktu)].filter(Boolean).join(' · ')}
                  </p>
                </div>
                <span className="shrink-0 font-mono text-sm font-semibold"
                  style={{ color: c.jenis === 'penjualan' ? 'var(--brand-600)' : 'var(--text)' }}>
                  {c.jenis === 'penjualan' ? '+' : ''}{formatCurrency(c.nominal)}
                </span>
                {c.boleh_hapus && <HapusCatatan id={c.id} />}
              </li>
            ))}
          </ul>
        )}
        {lebih > 0 && <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>+{lebih} catatan lain di Transaksi</p>}
      </Kartu>
    );
  },
});

registerCard({
  key: 'core.karyawan.batasan',
  Component: function KartuBatasan({ entri }) {
    const amplop = entri.amplop == null ? null : arr(entri.amplop).map(a => a.nama);
    const baris = ringkasBatasan(entri.batasan, amplop);
    return (
      <Kartu judul="Batasan dari admin">
        <ul className="space-y-1.5">
          {baris.map(b => (
            <li key={b} className="text-sm flex gap-2" style={{ color: 'var(--text)' }}>
              <Icon name="check" size={16} className="shrink-0 mt-0.5" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
        {entri.amplop != null && arr(entri.amplop).length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {arr(entri.amplop).map(a => (
              <span key={a.id} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
                style={{ background: 'var(--page)', border: '1px solid var(--border)', color: 'var(--text)' }}>
                <EnvelopeIcon value={a.emoji} size={14} /> {a.nama}
              </span>
            ))}
          </div>
        )}
      </Kartu>
    );
  },
});

registerCard({
  key: 'core.karyawan.ruang_terpisah',
  Component: function KartuRuangTerpisah({ entri }) {
    return (
      <section className="card !px-4 md:!px-6 !py-4 min-w-0 h-full flex gap-3 items-start"
        style={{ borderColor: 'rgba(29,158,117,0.35)' }}>
        <span className="shrink-0 w-9 h-9 rounded-xl inline-flex items-center justify-center"
          style={{ background: 'rgba(29,158,117,0.12)', color: 'var(--brand-600)' }}>
          <Icon name="home" size={18} />
        </span>
        <div className="min-w-0">
          <h2 className="font-bold text-[15px]" style={{ color: 'var(--text)' }}>{entri.judul}</h2>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>{entri.isi}</p>
        </div>
      </section>
    );
  },
});
