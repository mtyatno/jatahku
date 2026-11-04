import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { formatCurrency } from '../../lib/utils';
import { labelStatus, angkaUtama, trenTeks } from '../../lib/laporanView';
import UnduhPdfButton from './UnduhPdfButton';
import { periodeTeks, tanggalTeks, hariTeks, hariAngka } from '../../lib/laporanFormat';

const LANGKAH_MUTASI = 50;
const STRIP = '—';
const uang = (v) => (v === null || v === undefined || v === '' ? STRIP : formatCurrency(v));

function Bagian({ judul, children }) {
  return (
    <section className="card">
      <h3 className="font-semibold text-sm mb-4">{judul}</h3>
      {children}
    </section>
  );
}

function Kosong({ children }) {
  return <p className="text-sm text-gray-400">{children}</p>;
}

const TH = 'text-xs font-medium text-gray-400 py-2 px-2 whitespace-nowrap';
const TD = 'py-2.5 px-2 text-sm';

function Tabel({ kepala, children }) {
  return (
    <div className="overflow-x-auto -mx-2">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-100">
            {kepala.map(([teks, kanan], i) => (
              <th key={i} className={`${TH} ${kanan ? 'text-right' : 'text-left'}`}>{teks}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function TooltipHarian({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
      <p className="text-xs text-gray-400 mb-1">{tanggalTeks(label)}</p>
      <p className="text-sm font-semibold text-brand-600">{formatCurrency(payload[0].value)}</p>
    </div>
  );
}

// Laporan lengkap (desktop): delapan bagian, hanya memformat `laporan.data`.
export default function LaporanLengkap({ laporan }) {
  const data = laporan.data || {};
  const [tampil, setTampil] = useState(LANGKAH_MUTASI);
  const r = data.ringkasan || {};
  const banding = data.banding || {};
  const langganan = data.langganan || {};
  const sorotan = data.sorotan || {};
  const mutasi = data.mutasi || [];
  const amplop = data.amplop || [];
  const namaAmplop = Object.fromEntries(amplop.map((a) => [a.id, a]));
  const harian = (data.harian || []).map((h) => ({ tanggal: h.tanggal, total: Number(h.terpakai) }));
  const tren = trenTeks(banding.persen_perubahan);
  const [, , , persenTerpakai] = angkaUtama(data);

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">{laporan.judul}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {periodeTeks(laporan.periode_mulai, laporan.periode_akhir)}
            {data.angka_per && <> · Angka per {tanggalTeks(data.angka_per)}</>}
          </p>
        </div>
        <UnduhPdfButton laporan={laporan} className="shrink-0" />
      </div>

      <Bagian judul="Ringkasan">
        <div className="grid grid-cols-3 gap-4">
          {[
            ['Pemasukan', uang(r.pemasukan)],
            ['Dialokasikan', uang(r.dialokasikan)],
            ['Terpakai', uang(r.terpakai)],
            ['Sisa', uang(r.sisa)],
            ['Dibawa ke periode berikut', uang(r.dibawa)],
            [persenTerpakai.label, persenTerpakai.nilai],
          ].map(([label, nilai]) => (
            <div key={label}>
              <p className="text-xs text-gray-400">{label}</p>
              <p className="text-xl font-bold font-display">{nilai}</p>
            </div>
          ))}
        </div>
      </Bagian>

      <Bagian judul="Amplop">
        {amplop.length === 0 ? <Kosong>Tidak ada amplop.</Kosong> : (
          <Tabel kepala={[['Amplop'], ['Saldo awal', 1], ['Dialokasikan', 1], ['Terpakai', 1], ['Sisa', 1], ['Dibawa', 1], ['Status']]}>
            {amplop.map((a) => {
              const st = labelStatus(a.status);
              return (
                <tr key={a.id} className="border-b border-gray-50 last:border-0">
                  <td className={TD}>
                    <span className="mr-1.5">{a.emoji}</span>{a.nama}
                    {a.jenis === 'pribadi' && <span className="ml-2 text-xs text-gray-400">pribadi</span>}
                    {a.ditutup && <span className="ml-2 text-xs text-gray-400">ditutup</span>}
                  </td>
                  <td className={`${TD} text-right`}>{uang(a.awal)}</td>
                  <td className={`${TD} text-right`}>{uang(a.alokasi)}</td>
                  <td className={`${TD} text-right`}>{uang(a.terpakai)}</td>
                  <td className={`${TD} text-right font-semibold`}>{uang(a.akhir)}</td>
                  <td className={`${TD} text-right`}>{uang(a.rollover)}</td>
                  <td className={TD}>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold whitespace-nowrap ${st.kelas}`}>{st.label}</span>
                    {a.pernah_lewat_batas && a.status !== 'lewat_batas' && (
                      <span className="ml-1.5 text-xs text-amber-600">pernah lewat batas</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </Tabel>
        )}
      </Bagian>

      <Bagian judul="Dibanding periode lalu">
        <div className="grid grid-cols-3 gap-4 mb-1">
          <div>
            <p className="text-xs text-gray-400">Terpakai periode lalu</p>
            <p className="text-xl font-bold font-display">{uang(banding.terpakai_lalu)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">Rata-rata 3 periode</p>
            <p className="text-xl font-bold font-display">{uang(banding.terpakai_rata3)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">Periode ini</p>
            <p className="text-xl font-bold font-display">{uang(r.terpakai)}</p>
          </div>
        </div>
        {tren && <p className="text-sm text-gray-600 mt-2">{tren}</p>}
        {(banding.amplop || []).length > 0 && (
          <div className="mt-4">
            <Tabel kepala={[['Amplop'], ['Periode ini', 1], ['Periode lalu', 1], ['Rata-rata 3 periode', 1]]}>
              {banding.amplop.map((b) => {
                const a = namaAmplop[b.id];
                return (
                  <tr key={b.id} className="border-b border-gray-50 last:border-0">
                    <td className={TD}><span className="mr-1.5">{a?.emoji}</span>{a?.nama ?? STRIP}</td>
                    <td className={`${TD} text-right`}>{uang(a?.terpakai)}</td>
                    <td className={`${TD} text-right`}>{uang(b.terpakai_lalu)}</td>
                    <td className={`${TD} text-right`}>{uang(b.terpakai_rata3)}</td>
                  </tr>
                );
              })}
            </Tabel>
          </div>
        )}
      </Bagian>

      <Bagian judul="Pola harian">
        {harian.length === 0 ? <Kosong>Belum ada data.</Kosong> : (
          <>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={harian}>
                <XAxis dataKey="tanggal" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={hariTeks} interval={0} />
                <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false}
                  tickFormatter={(v) => v >= 1000000 ? `${(v / 1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v / 1000)}k` : v} />
                <Tooltip content={<TooltipHarian />} />
                <Bar dataKey="total" name="Pengeluaran" fill="#0F6E56" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            {data.hari_terboros && (
              <p className="text-sm text-gray-600 mt-2">
                Hari terboros: {tanggalTeks(data.hari_terboros.tanggal)} ({uang(data.hari_terboros.terpakai)})
              </p>
            )}
          </>
        )}
      </Bagian>

      <Bagian judul="5 pengeluaran terbesar">
        {(data.terbesar || []).length === 0 ? <Kosong>Belum ada pengeluaran.</Kosong> : (
          <Tabel kepala={[['Tanggal'], ['Keterangan'], ['Amplop'], ['Dicatat oleh'], ['Jumlah', 1]]}>
            {data.terbesar.map((t, i) => (
              <tr key={i} className="border-b border-gray-50 last:border-0">
                <td className={`${TD} whitespace-nowrap`}>{tanggalTeks(t.tanggal)}</td>
                <td className={TD}>{t.keterangan}</td>
                <td className={TD}>{t.amplop}</td>
                <td className={TD}>{t.pencatat}</td>
                <td className={`${TD} text-right font-semibold`}>{uang(t.jumlah)}</td>
              </tr>
            ))}
          </Tabel>
        )}
      </Bagian>

      <Bagian judul="Langganan">
        <p className="text-xs font-medium text-gray-400 mb-1">Terbayar periode ini</p>
        {(langganan.terbayar || []).length === 0 ? <Kosong>Tidak ada langganan terbayar.</Kosong> : (
          <Tabel kepala={[['Tanggal'], ['Langganan'], ['Amplop'], ['Jumlah', 1]]}>
            {langganan.terbayar.map((t, i) => (
              <tr key={i} className="border-b border-gray-50 last:border-0">
                <td className={`${TD} whitespace-nowrap`}>{tanggalTeks(t.tanggal)}</td>
                <td className={TD}>{t.nama}</td>
                <td className={TD}>{t.amplop}</td>
                <td className={`${TD} text-right`}>{uang(t.jumlah)}</td>
              </tr>
            ))}
          </Tabel>
        )}
        <p className="text-xs font-medium text-gray-400 mt-5 mb-1">Jatuh tempo periode berikutnya</p>
        {(langganan.jatuh_tempo || []).length === 0 ? <Kosong>Tidak ada tagihan berikutnya.</Kosong> : (
          <Tabel kepala={[['Tanggal'], ['Langganan'], ['Amplop'], ['Jumlah', 1]]}>
            {langganan.jatuh_tempo.map((t, i) => (
              <tr key={i} className="border-b border-gray-50 last:border-0">
                <td className={`${TD} whitespace-nowrap`}>{tanggalTeks(t.tanggal)}</td>
                <td className={TD}>{t.nama}</td>
                <td className={TD}>{t.amplop ?? STRIP}</td>
                <td className={`${TD} text-right`}>{uang(t.jumlah)}</td>
              </tr>
            ))}
          </Tabel>
        )}
      </Bagian>

      <Bagian judul="Sorotan">
        {data.email?.sorotan && <p className="text-sm text-brand-800 bg-brand-50 rounded-xl px-4 py-3 mb-4">{data.email.sorotan}</p>}
        <div className="grid grid-cols-3 gap-4">
          {[
            ['Hari mencatat', sorotan.hari_mencatat],
            ['Catat beruntun terpanjang', sorotan.beruntun_terpanjang],
            ['Streak saat terbit', sorotan.streak_saat_ini],
          ].map(([label, nilai]) => (
            <div key={label}>
              <p className="text-xs text-gray-400">{label}</p>
              <p className="text-xl font-bold font-display">{hariAngka(nilai)}</p>
            </div>
          ))}
        </div>
        <div className="mt-4">
          <p className="text-xs text-gray-400 mb-1.5">Amplop yang tidak pernah lewat batas</p>
          {(sorotan.amplop_aman || []).length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {sorotan.amplop_aman.map((n) => (
                <span key={n} className="px-2.5 py-1 rounded-full text-xs font-semibold text-brand-600 bg-brand-50">{n}</span>
              ))}
            </div>
          ) : <p className="text-sm">{STRIP}</p>}
        </div>
        <div className="mt-4 space-y-3">
          <p className="text-xs text-gray-400">Target tabungan</p>
          {(sorotan.target || []).length === 0 ? <Kosong>Belum ada target tabungan.</Kosong> : sorotan.target.map((g, i) => (
            <div key={i}>
              <div className="flex justify-between text-sm">
                <span>{g.nama}</span>
                <span className="text-gray-500">{uang(g.terkumpul)} / {uang(g.target)}{g.persen !== null && g.persen !== undefined ? ` (${g.persen}%)` : ''}</span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 mt-1.5 overflow-hidden">
                <div className="h-full bg-brand-600" style={{ width: `${Math.max(0, Math.min(100, g.persen ?? 0))}%` }} />
              </div>
            </div>
          ))}
        </div>
      </Bagian>

      <Bagian judul="Lampiran: mutasi">
        {mutasi.length === 0 ? <Kosong>Tidak ada mutasi.</Kosong> : (
          <>
            <Tabel kepala={[['Tanggal'], ['Keterangan'], ['Amplop'], ['Dicatat oleh'], ['Jumlah', 1]]}>
              {mutasi.slice(0, tampil).map((m, i) => (
                <tr key={i} className="border-b border-gray-50 last:border-0">
                  <td className={`${TD} whitespace-nowrap`}>{tanggalTeks(m.tanggal)}</td>
                  <td className={TD}>
                    {m.keterangan}
                    {m.penyesuaian && <span className="ml-2 text-xs text-gray-400">penyesuaian</span>}
                  </td>
                  <td className={TD}>{m.amplop ?? STRIP}</td>
                  <td className={TD}>{m.pencatat}</td>
                  <td className={`${TD} text-right font-semibold whitespace-nowrap ${m.arah === 'masuk' ? 'text-brand-600' : ''}`}>
                    {m.arah === 'masuk' ? '+' : '−'}{uang(m.jumlah)}
                  </td>
                </tr>
              ))}
            </Tabel>
            {mutasi.length > tampil && (
              <button type="button" onClick={() => setTampil((n) => n + LANGKAH_MUTASI)} className="btn-outline text-sm py-2 mt-4">
                Tampilkan lebih banyak
              </button>
            )}
          </>
        )}
      </Bagian>
    </div>
  );
}
