import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatShort, formatShortSigned, titleCase } from '../lib/utils';
import { fundingState } from '../lib/envelopeFunding';
import { Icon } from './Icon';
import FundEnvelopeModal from './FundEnvelopeModal';

// Card "Amplop pengeluaran" di Dashboard: satu daftar ringkas dengan tab
// Semua · Bersama · Pribadi. Baris diketuk → rincian + aksi (tutup minus / isi dana / catat).
// Amplop tabungan & sinking fund tidak masuk card ini.

const TAB_KEY = 'jatahku_dash_env_tab';
const TABS = [
  { key: 'semua', label: 'Semua' },
  { key: 'bersama', label: 'Bersama' },
  { key: 'pribadi', label: 'Pribadi' },
];

const RED = '#E24B4A';    // danger-400
const AMBER = '#BA7517';  // amber-400

function readTab() {
  try {
    const t = localStorage.getItem(TAB_KEY);
    return TABS.some(x => x.key === t) ? t : 'semua';
  } catch { return 'semua'; }
}

function saveTab(t) {
  try { localStorage.setItem(TAB_KEY, t); } catch { /* storage diblokir: abaikan */ }
}

// Keadaan satu amplop untuk warna, catatan, dan aksi di rinciannya.
export function envelopeStatus(env) {
  const allocated = Number(env.allocated || 0);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent || 0);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free ?? env.remaining ?? 0);
  const jatah = allocated + rollover;
  const ratio = Number(env.spent_ratio || 0);
  const pct = Math.round(ratio * 100);
  const fstate = fundingState(env);
  const unfunded = allocated <= 0 && rollover === 0;

  let tone = 'ok';
  let note;
  let action = 'catat';
  let needed = 0;

  if (fstate === 'overspent') {
    tone = 'over';
    needed = -free;
    note = `Minus ${formatShort(-(jatah - spent))}. Tutup dari amplop lain atau pemasukan.`;
    action = 'tutup';
  } else if (fstate === 'reserve_short') {
    tone = 'warn';
    needed = -free;
    note = `Uang tagihan ${formatShort(reserved)} lebih besar dari sisa — kurang ${formatShort(-free)}.`;
    action = 'isi';
  } else if (unfunded) {
    tone = 'empty';
    note = 'Belum ada dana. Pengeluaran tetap bisa dicatat.';
    action = 'isi';
  } else if (free <= 0) {
    tone = 'over';
    note = 'Jatah habis. Pengeluaran tetap bisa dicatat.';
    action = 'isi';
  } else if (ratio >= 0.7) {
    tone = 'warn';
    note = `Hampir habis. Sisa ${formatShort(free)}.`;
  } else {
    note = `Masih aman. Sisa ${formatShort(free)}.`;
  }

  return { allocated, rollover, spent, reserved, free, jatah, pct, tone, note, action, needed, unfunded };
}

function toneColors(tone) {
  if (tone === 'over') return { bar: RED, sisa: RED };
  if (tone === 'warn') return { bar: AMBER, sisa: AMBER };
  if (tone === 'empty') return { bar: 'transparent', sisa: 'var(--text-muted)' };
  return { bar: 'var(--brand-400)', sisa: 'var(--brand-600)' };
}

const ACTION_LABEL = { tutup: 'Tutup minus', isi: 'Isi dana', catat: 'Catat' };

function Bar({ pct, color, track, height }) {
  return (
    <span className="flex-1 rounded-full overflow-hidden" style={{ height, background: track }}>
      <span className="block h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(Math.max(pct, 0), 100)}%`, background: color }} />
    </span>
  );
}

function Meta({ env }) {
  return (
    <span className="text-xs flex items-center gap-1.5 min-w-0" style={{ color: 'var(--text-muted)' }}>
      <span className="truncate">{env.group_name || 'Lainnya'} · {env.is_personal ? 'Pribadi' : 'Bersama'}</span>
      {env.is_personal && <Icon name="lock" size={12} color="var(--text-muted)" />}
      {env.is_locked && <span className="shrink-0">· Dikunci</span>}
    </span>
  );
}

function Row({ env, open, onToggle, onAction, actionable, track, inset }) {
  const s = envelopeStatus(env);
  const c = toneColors(s.tone);
  const pctLabel = s.unfunded ? '—' : `${s.pct}%`;
  const sisaLabel = formatShortSigned(s.free);
  const detailId = `env-detail-${env.id}`;

  return (
    <li style={{ borderTop: '1px solid var(--border)' }} className={env.is_locked ? 'opacity-70' : ''}>
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls={detailId}
        className="w-full text-left rounded-xl px-1 md:px-3 py-3.5 md:py-4 md:min-h-[72px]
                   flex flex-col gap-2 md:grid md:grid-cols-[minmax(0,1.05fr)_minmax(0,1.35fr)_130px_28px] md:gap-6 md:items-center">
        {/* Kolom 1: nama (+ sisa di HP) dan meta */}
        <span className="flex flex-col gap-1 min-w-0">
          <span className="flex items-baseline justify-between gap-3">
            <span className="text-[15px] font-semibold truncate min-w-0" style={{ color: 'var(--text)' }}>{titleCase(env.name)}</span>
            <span className="md:hidden shrink-0 text-[15px] font-bold tabular-nums" style={{ color: c.sisa }}>{sisaLabel}</span>
          </span>
          <span className="hidden md:flex"><Meta env={env} /></span>
        </span>
        {/* Kolom 2: bar terpakai */}
        <span className="flex items-center gap-2.5 md:gap-3.5 min-w-0">
          <Bar pct={s.pct} color={c.bar} track={track} height={7} />
          <span className="w-10 text-right text-xs md:text-[13px] tabular-nums" style={{ color: 'var(--text-muted)' }}>{pctLabel}</span>
        </span>
        <span className="md:hidden"><Meta env={env} /></span>
        {/* Kolom 3–4 (desktop): sisa dan panah */}
        <span className="hidden md:block text-right text-[15px] font-bold tabular-nums" style={{ color: c.sisa }}>{sisaLabel}</span>
        <span className="hidden md:flex justify-center transition-transform" style={{ transform: open ? 'rotate(180deg)' : 'none' }}>
          <Icon name="chevron" size={16} color="var(--text-muted)" />
        </span>
      </button>

      {open && (
        <div id={detailId}
          className="mt-1.5 md:mt-2 mb-4 mx-1 md:mx-3 rounded-xl px-3 md:px-4 py-3 md:py-3.5 flex flex-col md:flex-row md:items-center md:justify-between gap-3"
          style={{ background: inset, border: '1px solid var(--border)' }}>
          <div className="flex flex-col gap-1 min-w-0 text-[13px]">
            <span style={{ color: 'var(--text)' }}>
              Terpakai <b className="font-semibold">{formatShort(s.spent)}</b> dari jatah {formatShort(s.jatah)}
            </span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Dana {formatShort(s.allocated)}
              {s.rollover !== 0 && <> · {s.rollover > 0 ? `+${formatShort(s.rollover)} rollover` : `−${formatShort(-s.rollover)} dari periode lalu`}</>}
              {s.reserved > 0 && <> · Tagihan disimpan {formatShort(s.reserved)}</>}
              {Number(env.daily_limit) > 0 && <> · Limit {formatShort(env.daily_limit)}/hari</>}
            </span>
            <span className="text-xs" style={{ color: s.tone === 'ok' || s.tone === 'empty' ? 'var(--text-muted)' : c.sisa }}>{s.note}</span>
          </div>
          <div className="grid grid-cols-2 md:flex gap-2 shrink-0">
            <Link to={`/transactions?envelope=${env.id}`}
              className="inline-flex items-center justify-center min-h-[44px] md:min-h-[40px] px-3.5 rounded-xl text-sm md:text-[13px] font-semibold"
              style={{ border: '1px solid var(--border)', color: 'var(--text)' }}>
              Riwayat
            </Link>
            {actionable && (
              <button type="button" onClick={() => onAction(env, s)}
                className="inline-flex items-center justify-center min-h-[44px] md:min-h-[40px] px-4 rounded-xl text-sm md:text-[13px] font-semibold text-white bg-brand-600 hover:opacity-90">
                {ACTION_LABEL[s.action]}
              </button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export default function SpendingEnvelopes({ envelopes, allEnvelopes, isDark, track, actionable, onChanged }) {
  const [tab, setTab] = useState(readTab);
  const [openId, setOpenId] = useState(null);
  const [fund, setFund] = useState(null); // { env, needed }

  const counts = {
    semua: envelopes.length,
    bersama: envelopes.filter(e => !e.is_personal).length,
    pribadi: envelopes.filter(e => e.is_personal).length,
  };
  const list = envelopes.filter(e => tab === 'semua' || (tab === 'pribadi') === !!e.is_personal);
  const totalSisa = list.reduce((sum, e) => sum + Number(e.free ?? e.remaining ?? 0), 0);
  const habis = list.filter(e => {
    const s = envelopeStatus(e);
    return !s.unfunded && s.free <= 0;
  }).length;

  const inset = isDark ? 'var(--page)' : 'var(--surface)';

  const pick = (key) => { setTab(key); setOpenId(null); saveTab(key); };
  const onAction = (env, s) => {
    if (s.action === 'catat') {
      window.dispatchEvent(new CustomEvent('jatahku:open-action', { detail: 'expense' }));
    } else {
      setFund({ env, needed: Math.max(s.needed, 0) });
    }
  };

  const emptyText = tab === 'pribadi'
    ? { title: 'Belum ada amplop pribadi', body: 'Amplop pribadi hanya terlihat olehmu, tidak oleh anggota rumah tangga.', cta: '+ Buat amplop pribadi' }
    : { title: 'Belum ada amplop bersama', body: 'Amplop bersama dipakai semua anggota rumah tangga.', cta: '+ Buat amplop' };

  return (
    <section aria-labelledby="amplop-pengeluaran-title" className="card !px-3.5 md:!px-7 !pt-5 md:!pt-6 !pb-4">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3.5 md:gap-4 md:pb-4 px-1 md:px-0">
        <div className="flex items-baseline md:flex-col md:items-start justify-between gap-1.5">
          <h2 id="amplop-pengeluaran-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Amplop pengeluaran</h2>
          <p className="hidden md:block text-[13px]" style={{ color: 'var(--text-muted)' }}>
            Sisa <b className="font-semibold" style={{ color: 'var(--text)' }}>{formatShortSigned(totalSisa)}</b>
            {habis > 0 && <> · <span className="font-semibold" style={{ color: RED }}>{habis} amplop habis</span></>}
          </p>
          <Link to="/envelopes" className="md:hidden text-[13px] font-semibold text-brand-600">Kelola</Link>
        </div>

        <div role="tablist" aria-label="Filter amplop"
          className="grid grid-cols-3 md:flex gap-0.5 p-1 rounded-xl"
          style={{ background: inset, border: '1px solid var(--border)' }}>
          {TABS.map(t => {
            const sel = t.key === tab;
            return (
              <button key={t.key} type="button" role="tab" aria-selected={sel} onClick={() => pick(t.key)}
                className="flex items-center justify-center gap-1.5 md:gap-2 min-h-[44px] md:min-h-[40px] px-1.5 md:px-3.5 rounded-[9px] text-sm transition-colors"
                style={{
                  fontWeight: sel ? 700 : 500,
                  color: sel ? 'var(--text)' : 'var(--text-muted)',
                  background: sel ? (isDark ? 'var(--border)' : 'var(--card-bg)') : 'transparent',
                  boxShadow: sel && !isDark ? '0 1px 2px rgba(15,23,42,0.08)' : 'none',
                }}>
                {t.label}
                <span className="text-[11px] font-semibold min-w-[20px] h-5 px-1.5 rounded-full inline-flex items-center justify-center"
                  style={sel
                    ? { background: 'var(--brand-50)', color: 'var(--brand-600)' }
                    : { background: isDark ? 'var(--card-bg)' : 'var(--card-bg)', color: 'var(--text-muted)' }}>
                  {counts[t.key]}
                </span>
              </button>
            );
          })}
        </div>

        <p className="md:hidden text-[13px] px-0.5" style={{ color: 'var(--text-muted)' }}>
          Sisa <b className="font-semibold" style={{ color: 'var(--text)' }}>{formatShortSigned(totalSisa)}</b>
          {habis > 0 && <> · <span className="font-semibold" style={{ color: RED }}>{habis} amplop habis</span></>}
        </p>
      </div>

      <div className="hidden md:grid grid-cols-[minmax(0,1.05fr)_minmax(0,1.35fr)_130px_28px] gap-6 px-3 pb-3 text-xs font-medium"
        style={{ color: 'var(--text-muted)' }}>
        <span>Amplop</span>
        <span>Terpakai</span>
        <span className="text-right">Sisa</span>
        <span />
      </div>

      {list.length === 0 ? (
        <div className="flex flex-col items-center gap-2 text-center py-10 px-4" style={{ borderTop: '1px solid var(--border)' }}>
          <p className="text-[15px] font-semibold" style={{ color: 'var(--text)' }}>{emptyText.title}</p>
          <p className="text-[13px] max-w-sm" style={{ color: 'var(--text-muted)' }}>{emptyText.body}</p>
          <Link to="/envelopes" className="mt-1 text-sm font-semibold text-brand-600">{emptyText.cta}</Link>
        </div>
      ) : (
        <ul className="flex flex-col" role="tabpanel" aria-labelledby="amplop-pengeluaran-title">
          {list.map(env => (
            <Row key={env.id} env={env} open={openId === env.id}
              onToggle={() => setOpenId(openId === env.id ? null : env.id)}
              onAction={onAction} actionable={actionable} track={track} inset={inset} />
          ))}
        </ul>
      )}

      <div className="hidden md:flex items-center justify-between px-3 pt-4" style={{ borderTop: '1px solid var(--border)' }}>
        <Link to="/envelopes" className="text-sm font-semibold text-brand-600 hover:underline">Kelola amplop</Link>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Urut: paling kritis dulu</span>
      </div>

      {fund && (
        <FundEnvelopeModal
          advisor
          isOpen
          onClose={() => setFund(null)}
          targetEnvelope={fund.env}
          neededAmount={fund.needed}
          envelopes={allEnvelopes}
          onSuccess={() => { setFund(null); onChanged?.(); }}
        />
      )}
    </section>
  );
}
