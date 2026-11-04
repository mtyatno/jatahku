// Kartu Fitur Tambahan dari bentuk deklaratif (Plugin H3; 04-kontrak-api.md §4 "Bentuk deklaratif", 01-kajian.md
// "Bentuk data deklaratif"). Data dihitung dan diperiksa server (`titik.rapikan_kartu`: field, batas baris, tautan hanya
// ke `/p/<id>`); komponen ini hanya memformat (AGENTS.md "Plugin dan ruang" aturan 6). Tampilan, mode gelap, dan
// aksesibilitas sama untuk semua plugin. Penanda kecil "ikon puzzle + nama plugin" membedakannya dari kartu bawaan
// (desain A2 butir 3).
import { useNavigate } from 'react-router-dom';
import { Icon } from '../../components/Icon';
import { formatNilai, selTabel } from '../../lib/pluginHost';
import { safeRoute } from '../../lib/advisorAction';

const arr = (v) => (Array.isArray(v) ? v : []);

// Warna nada per tema; teks ≥ 4,5:1 terhadap latar kartu di terang dan gelap.
const NADA = {
  ok: ['#047857', '#34D399'],
  info: ['#4338CA', '#A5B4FC'],
  warn: ['#B45309', '#FBBF24'],
  danger: ['#DC2626', '#F87171'],
};
const warna = (tone, isDark) => (NADA[tone] || [null, null])[isDark ? 1 : 0];
const SERI = [['#0F6E56', '#34D399'], ['#6366F1', '#A5B4FC'], ['#D97706', '#FBBF24']];

const angka = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

function Penanda({ sumber }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium rounded-full px-2 py-0.5 shrink-0"
      style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.14)' }} title={`Dari Fitur Tambahan ${sumber}`}>
      <Icon name="puzzle" size={12} /> {sumber}
    </span>
  );
}

function Aksi({ aksi, kecil = false }) {
  const navigate = useNavigate();
  const ke = aksi?.kind === 'route' ? safeRoute(aksi.payload?.to) : null;
  if (!ke) return null;
  return (
    <button type="button" onClick={() => navigate(ke)}
      className={`inline-flex items-center gap-1 font-semibold ${kecil ? 'text-xs' : 'text-sm'} hover:underline`}
      style={{ color: 'var(--brand-600)' }}>
      {aksi.label || 'Buka'} <Icon name="arrowright" size={kecil ? 12 : 14} />
    </button>
  );
}

function Bingkai({ judul, sumber, children }) {
  return (
    <section className="card !px-4 md:!px-6 !py-5 min-w-0 h-full">
      <div className="flex items-start justify-between gap-3 mb-3">
        <h2 className="font-display font-bold text-lg leading-tight min-w-0" style={{ color: 'var(--text)' }}>{judul}</h2>
        <Penanda sumber={sumber} />
      </div>
      {children}
    </section>
  );
}

function Batang({ rasio, tone, isDark, label }) {
  const pct = rasio == null ? 0 : Math.min(Math.max(rasio, 0), 1) * 100;
  return (
    <div className="h-1.5 rounded-full" style={{ background: isDark ? '#2A3245' : '#E8EBEF' }} role="img" aria-label={label}>
      {pct > 0 && <div className="h-full rounded-full" style={{ width: `${Math.max(pct, 3)}%`, background: warna(tone, isDark) || 'var(--brand-400)' }} />}
    </div>
  );
}

function Kpi({ d, kartu, sumber, isDark }) {
  const nada = warna(d.tone, isDark);
  const bar = angka(d.bar);
  return (
    <div className="card !p-4 sm:!p-5 min-w-0 h-full">
      <div className="flex items-start justify-between gap-2 min-h-[24px]">
        <p className="text-sm truncate" style={{ color: 'var(--text-muted)' }}>{kartu.judul}</p>
        <Penanda sumber={sumber} />
      </div>
      <p className="mt-2 flex items-baseline flex-wrap gap-x-1.5 leading-tight">
        <span className="font-display text-2xl font-bold" style={nada ? { color: nada } : { color: 'var(--text)' }}>
          {formatNilai(d.value, d.unit)}
        </span>
        {d.suffix && <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{d.suffix}</span>}
        {d.chip && (
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{ color: nada || 'var(--text-muted)', background: 'rgba(148,163,184,0.14)' }}>{d.chip}</span>
        )}
      </p>
      {bar != null && <div className="mt-3"><Batang rasio={bar} tone={d.tone} isDark={isDark} label={`${Math.round(bar * 100)}%`} /></div>}
      {d.footer && <p className="mt-2.5 text-xs" style={{ color: 'var(--text-muted)' }}>{d.footer}</p>}
    </div>
  );
}

// Nilai `progress` dalam rupiah (sasaran = target); tanpa target hanya nilainya.
function Progress({ d, isDark }) {
  const items = arr(d.items);
  if (!items.length) return <Kosong />;
  return (
    <ul className="flex flex-col gap-3">
      {items.map((it, i) => {
        const v = angka(it.value);
        const t = angka(it.target);
        const rasio = t ? (v ?? 0) / t : null;
        return (
          <li key={`${it.label}-${i}`} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate" style={{ color: 'var(--text)' }}>{it.label}</span>
              <span className="shrink-0 tabular-nums" style={{ color: warna(it.tone, isDark) || 'var(--text-muted)' }}>
                {formatNilai(v, 'rp')}{t != null && <span style={{ color: 'var(--text-muted)' }}> / {formatNilai(t, 'rp')}</span>}
              </span>
            </div>
            <Batang rasio={rasio} tone={it.tone || 'ok'} isDark={isDark}
              label={t ? `${it.label}: ${Math.round((rasio || 0) * 100)}% dari sasaran` : it.label} />
          </li>
        );
      })}
    </ul>
  );
}

function Daftar({ d }) {
  const items = arr(d.items);
  if (!items.length) return <Kosong />;
  return (
    <ul className="flex flex-col">
      {items.map((it, i) => (
        <li key={`${it.judul}-${i}`} className="py-2.5 first:pt-0 last:pb-0 flex items-center gap-3 min-w-0"
          style={i ? { borderTop: '1px solid var(--border)' } : undefined}>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate" style={{ color: 'var(--text)' }}>{it.judul}</p>
            {(it.subjudul || it.status) && (
              <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                {[it.subjudul, it.status].filter(Boolean).join(' · ')}
              </p>
            )}
            {it.aksi && <div className="mt-1"><Aksi aksi={it.aksi} kecil /></div>}
          </div>
          {angka(it.nominal) != null && (
            <span className="shrink-0 text-sm font-semibold tabular-nums" style={{ color: 'var(--text)' }}>
              {formatNilai(it.nominal, 'rp')}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function Tabel({ d }) {
  const cols = arr(d.columns);
  const rows = arr(d.rows);
  if (!rows.length) return <Kosong />;
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm">
        <thead>
          <tr>{cols.map((c, i) => (
            <th key={`${c}-${i}`} scope="col" className={`px-1 pb-2 font-medium ${i ? 'text-right' : 'text-left'}`}
              style={{ color: 'var(--text-muted)' }}>{c}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} style={{ borderTop: '1px solid var(--border)' }}>
              {arr(r).map((c, ci) => (
                <td key={ci} className={`px-1 py-2 ${ci ? 'text-right tabular-nums' : 'text-left'}`} style={{ color: 'var(--text)' }}>
                  {selTabel(c, ci)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Garis sederhana untuk 1–3 seri (maks. 62 titik), plus garis acuan putus-putus. Angka lengkap ada di tabel tersembunyi
// untuk pembaca layar.
function Seri({ d, isDark }) {
  const x = arr(d.x);
  const seri = arr(d.series);
  if (!x.length || !seri.length) return <Kosong />;
  const W = 320;
  const H = 120;
  const semua = seri.flatMap(s => arr(s.values).map(angka)).filter(v => v != null);
  const acuan = angka(d.acuan);
  if (acuan != null) semua.push(acuan);
  const maks = Math.max(1, ...semua);
  const min = Math.min(0, ...semua);
  const sx = (i) => (x.length === 1 ? W / 2 : (i / (x.length - 1)) * W);
  const sy = (v) => H - ((v - min) / (maks - min || 1)) * H;
  const garis = (vals) => {
    let path = '';
    arr(vals).forEach((v, i) => {
      const n = angka(v);
      if (n == null) return;
      path += `${path && angka(vals[i - 1]) != null ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(n).toFixed(1)} `;
    });
    return path.trim();
  };
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-32" preserveAspectRatio="none" aria-hidden="true">
        {acuan != null && (
          <line x1="0" x2={W} y1={sy(acuan)} y2={sy(acuan)} stroke="var(--text-muted)" strokeDasharray="4 4" strokeWidth="1" opacity="0.6" />
        )}
        {seri.map((s, i) => (
          <path key={s.nama} d={garis(s.values)} fill="none" stroke={SERI[i % 3][isDark ? 1 : 0]} strokeWidth="2"
            vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
        ))}
      </svg>
      <div className="flex justify-between text-[11px] mt-1" style={{ color: 'var(--text-muted)' }} aria-hidden="true">
        <span>{x[0]}</span><span>{x[x.length - 1]}</span>
      </div>
      {seri.length > 1 && (
        <div className="flex flex-wrap gap-3 mt-2 text-xs" style={{ color: 'var(--text-muted)' }} aria-hidden="true">
          {seri.map((s, i) => (
            <span key={s.nama} className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: SERI[i % 3][isDark ? 1 : 0] }} /> {s.nama}
            </span>
          ))}
        </div>
      )}
      <table className="sr-only">
        <thead><tr><th scope="col">Label</th>{seri.map(s => <th key={s.nama} scope="col">{s.nama}</th>)}</tr></thead>
        <tbody>{x.map((lbl, i) => (
          <tr key={`${lbl}-${i}`}><th scope="row">{lbl}</th>{seri.map(s => <td key={s.nama}>{formatNilai(arr(s.values)[i])}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

const IKON_NADA = { ok: 'check', info: 'info', warn: 'warning', danger: 'warning' };

function Peringatan({ d, kartu, sumber, isDark }) {
  const nada = warna(d.tone, isDark) || 'var(--text-muted)';
  return (
    <section className="card !px-4 md:!px-6 !py-4 min-w-0 h-full" role="status">
      <div className="flex items-start gap-3">
        <span className="w-9 h-9 rounded-xl shrink-0 inline-flex items-center justify-center"
          style={{ color: nada, background: `color-mix(in srgb, ${nada} 14%, transparent)` }} aria-hidden="true">
          <Icon name={IKON_NADA[d.tone] || 'info'} size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p className="text-xs pt-0.5" style={{ color: 'var(--text-muted)' }}>{kartu.judul}</p>
            <Penanda sumber={sumber} />
          </div>
          <p className="font-semibold" style={{ color: nada }}>{d.judul}</p>
          {d.isi && <p className="text-sm mt-1" style={{ color: 'var(--text)' }}>{d.isi}</p>}
          {d.aksi && <div className="mt-2"><Aksi aksi={d.aksi} /></div>}
        </div>
      </div>
    </section>
  );
}

function Kosong() {
  return <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Belum ada data untuk periode ini.</p>;
}

/** Kartu plugin tanpa komponen kustom. `kartu` = entri `cards` dari GET /plugins/contributions. */
export default function KartuDeklaratif({ entri, ctx, kartu, sumber }) {
  const isDark = !!ctx?.isDark;
  const d = entri || {};
  if (d.shape === 'kpi') return <Kpi d={d} kartu={kartu} sumber={sumber} isDark={isDark} />;
  if (d.shape === 'alert') return <Peringatan d={d} kartu={kartu} sumber={sumber} isDark={isDark} />;
  const isi = {
    progress: <Progress d={d} isDark={isDark} />,
    list: <Daftar d={d} />,
    table: <Tabel d={d} />,
    series: <Seri d={d} isDark={isDark} />,
  }[d.shape];
  return (
    <Bingkai judul={kartu.judul} sumber={sumber}>
      {isi || <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Kartu ini belum bisa ditampilkan di versi aplikasi ini.</p>}
    </Bingkai>
  );
}
