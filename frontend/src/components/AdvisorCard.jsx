import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { chipTones } from './AdvisorChip';
import { openAction } from '../lib/advisorAction';
import { basisLabel } from '../lib/advisorDashboard';
import {
  askAction, askChips, badgeCount, dismissKey, dismissOptions, hiddenList, overflowLabel, primaryAction, visibleItems,
} from '../lib/advisorCard';

// Kartu AI Advisor Beranda (01-desain.md "Kartu AI Advisor", 02-aturan.md §7 & §9), pengganti
// "Perlu perhatian" untuk user di flag advisor_v2_users. Isi `dash.advisor` dari GET
// /advisor/dashboard: urutan, batas 3 item, dan teks sudah dari server; aksi lewat open-action.

const TONE_LABEL = { danger: 'Penting', warn: 'Perlu dicek', info: 'Saran', ok: 'Aman' };

function dismiss(insight, pilihan) {
  const kunci = dismissKey(insight);
  if (kunci) openAction({ kind: 'dismiss', payload: { kunci, pilihan } });
}

function ItemDetail({ insight, stamp }) {
  const more = (insight.aksi || []).slice(1);
  const options = dismissOptions(insight).filter(o => o.pilihan !== 'nanti');
  return (
    <div className="mt-3 rounded-xl p-3 text-[13px]" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
      {insight.fakta?.length > 0 && (
        <dl className="space-y-1.5">
          {insight.fakta.map((f, i) => (
            <div key={i} className="flex justify-between gap-3">
              <dt style={{ color: 'var(--text-muted)' }}>{f.label}</dt>
              <dd className="text-right font-medium tabular-nums" style={{ color: 'var(--text)' }}>{f.nilai}</dd>
            </div>
          ))}
        </dl>
      )}
      {insight.rincian?.length > 0 && (
        <ul className={`space-y-1.5 ${insight.fakta?.length ? 'mt-3 pt-3 border-t' : ''}`} style={{ borderColor: 'var(--border)' }}>
          {insight.rincian.map(r => (
            <li key={r.id}>
              <p className="font-medium" style={{ color: 'var(--text)' }}>{r.judul}</p>
              {r.isi && <p style={{ color: 'var(--text-muted)' }}>{r.isi}</p>}
            </li>
          ))}
        </ul>
      )}
      {more.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {more.map((a, i) => (
            <button key={`${a.kind}-${i}`} type="button" onClick={() => openAction(a)} className="btn-outline !py-1.5 !px-3 text-[13px]">
              {a.label}
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 pt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t text-xs"
        style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
        <span>{[basisLabel(insight.dasar), stamp].filter(Boolean).join(' · ')}</span>
        {options.length > 0 && (
          <span className="flex gap-3">
            {options.map(o => (
              <button key={o.pilihan} type="button" onClick={() => dismiss(insight, o.pilihan)} className="font-medium hover:underline">
                {o.label}
              </button>
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

export default function AdvisorCard({ dash, stamp, isDark }) {
  const advisor = dash?.advisor || {};
  const [hidden, setHidden] = useState([]);
  const [restored, setRestored] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [showHidden, setShowHidden] = useState(false);
  const tones = chipTones(isDark);

  // Disembunyikan / dimunculkan lagi → berubah seketika; muatan ulang Beranda membawa daftar baru.
  useEffect(() => {
    const on = (e) => { const k = e.detail?.kunci; if (k) setHidden(h => [...h, k]); };
    const back = (e) => { const k = e.detail?.kunci; if (k) setRestored(r => [...r, k]); };
    window.addEventListener('jatahku:advisor-dismissed', on);
    window.addEventListener('jatahku:advisor-undismissed', back);
    return () => {
      window.removeEventListener('jatahku:advisor-dismissed', on);
      window.removeEventListener('jatahku:advisor-undismissed', back);
    };
  }, []);
  useEffect(() => { setHidden([]); setRestored([]); }, [dash]);

  const items = visibleItems(advisor, hidden);
  const count = badgeCount(advisor, hidden);
  const overflow = overflowLabel(advisor.sisa);
  const aman = items.length === 0 && advisor.aman && !hidden.includes(dismissKey(advisor.aman)) ? advisor.aman : null;
  const chips = askChips(dash);
  const tersembunyi = hiddenList(advisor, restored);

  return (
    <section aria-labelledby="ai-advisor-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-4 min-w-0 flex flex-col">
      <div className="px-1 pb-2">
        <div className="flex items-center gap-2">
          <Icon name="advisor" size={18} weight="fill" style={{ color: 'var(--brand-600)' }} />
          <h2 id="ai-advisor-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>AI Advisor</h2>
          {count > 0 && (
            <span className="min-w-[24px] h-6 px-1.5 rounded-full text-[13px] font-bold inline-flex items-center justify-center"
              style={{ background: 'var(--brand-600)', color: '#fff' }} aria-label={`${count} saran`}>
              {count}
            </span>
          )}
          {stamp && <span className="ml-auto text-xs" style={{ color: 'var(--text-muted)' }}>{stamp}</span>}
        </div>
        {items.length > 0 && (
          <p className="text-[13px] mt-0.5" style={{ color: 'var(--text-muted)' }}>Tiga langkah paling berdampak untuk sisa periode ini</p>
        )}
      </div>

      {items.length === 0 ? (
        <div className="flex items-start gap-3 px-1 py-4">
          <span className="w-9 h-9 rounded-full inline-flex items-center justify-center shrink-0"
            style={{ background: tones.ok.bg, color: tones.ok.text }}>
            <Icon name="check" size={18} weight="bold" />
          </span>
          <div className="min-w-0">
            <p className="text-[15px] font-semibold" style={{ color: 'var(--text)' }}>Semua aman</p>
            {aman ? (
              <>
                <p className="text-[13px] font-medium mt-0.5" style={{ color: 'var(--text)' }}>{aman.judul}</p>
                {aman.isi && <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>{aman.isi}</p>}
              </>
            ) : (
              <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>Tidak ada langkah yang perlu diambil sekarang.</p>
            )}
          </div>
        </div>
      ) : (
        <ul className="flex flex-col">
          {items.map((it, i) => {
            const tone = tones[it.tone] || tones.info;
            const main = primaryAction(it);
            const open = openId === it.id;
            const canHide = dismissOptions(it).some(o => o.pilihan === 'nanti');
            return (
              <li key={it.id} className="px-1 py-3.5" style={i > 0 ? { borderTop: '1px solid var(--border)' } : undefined}>
                <div className="flex items-start gap-3">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0 mt-[7px]" style={{ background: tone.text }}
                    role="img" aria-label={TONE_LABEL[it.tone] || TONE_LABEL.info} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[15px] font-semibold leading-snug" style={{ color: 'var(--text)' }}>{it.judul}</p>
                    {it.isi && <p className="text-[13px] mt-0.5 leading-relaxed" style={{ color: 'var(--text-muted)' }}>{it.isi}</p>}
                    <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
                      {main && (
                        <button type="button" onClick={() => openAction(main)}
                          className="min-h-[40px] px-4 rounded-xl text-sm font-semibold transition-opacity hover:opacity-90"
                          style={i === 0 && it.tone === 'danger'
                            ? { background: 'var(--text)', color: 'var(--card-bg)' }
                            : { background: isDark ? 'var(--page)' : 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                          {main.label}
                        </button>
                      )}
                      <button type="button" onClick={() => setOpenId(o => (o === it.id ? null : it.id))} aria-expanded={open}
                        className="text-[13px] font-medium inline-flex items-center gap-1 hover:underline" style={{ color: 'var(--text)' }}>
                        Rincian
                        <Icon name="chevron" size={12} weight="bold" style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
                      </button>
                      {canHide && (
                        <button type="button" onClick={() => dismiss(it, 'nanti')}
                          className="text-[13px] font-medium hover:underline" style={{ color: 'var(--text-muted)' }}>
                          Nanti
                        </button>
                      )}
                    </div>
                    {open && <ItemDetail insight={it} stamp={stamp} />}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {overflow && (
        <p className="px-1 py-3 text-[13px]" style={{ color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>{overflow}</p>
      )}

      {tersembunyi.length > 0 && (
        <div className="px-1 py-2.5 text-[13px]" style={{ color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>
          <button type="button" onClick={() => setShowHidden(v => !v)} aria-expanded={showHidden}
            className="inline-flex items-center gap-1 hover:underline">
            {tersembunyi.length} disembunyikan · {showHidden ? 'Tutup' : 'Tampilkan'}
            <Icon name="chevron" size={12} weight="bold" style={{ transform: showHidden ? 'rotate(180deg)' : 'none' }} />
          </button>
          {showHidden && (
            <ul className="mt-2 flex flex-col gap-1.5">
              {tersembunyi.map(d => (
                <li key={d.kunci} className="flex items-center justify-between gap-3">
                  <span className="min-w-0">
                    <span className="font-medium" style={{ color: 'var(--text)' }}>{d.judul}</span>
                    <span> · {d.sampai}</span>
                  </span>
                  <button type="button" onClick={() => openAction({ kind: 'undismiss', payload: { kunci: d.kunci } })}
                    className="font-medium shrink-0 hover:underline" style={{ color: 'var(--brand-600)' }}>
                    Munculkan lagi
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-auto pt-3 px-1" style={{ borderTop: '1px solid var(--border)' }}>
        <p className="text-[13px] font-semibold mb-2" style={{ color: 'var(--text)' }}>Tanya AI Advisor</p>
        <div className="flex flex-wrap gap-2">
          {chips.map(c => (
            <button key={c.text} type="button" onClick={() => openAction(askAction(chips, c))}
              className="px-3 py-1.5 rounded-full text-[13px] hover:border-brand-400 hover:text-brand-600"
              style={{ border: '1px solid var(--border)', color: 'var(--text)' }}>
              {c.label}
            </button>
          ))}
          <button type="button" onClick={() => openAction(askAction(chips, null))}
            className="px-3 py-1.5 rounded-full text-[13px] inline-flex items-center gap-1.5 hover:text-brand-600"
            style={{ color: 'var(--text-muted)' }}>
            <Icon name="chat" size={14} />
            Ketik sendiri…
          </button>
        </div>
      </div>
    </section>
  );
}
