import { useNavigate } from 'react-router-dom';
import { attentionOverflow } from '../lib/dashboardInsights';
import { tileTones } from './KpiCard';
import { Icon } from './Icon';

// Card "Perlu perhatian" (pengganti AI Advisor di Beranda): hal yang perlu ditindaklanjuti sekarang,
// masing-masing dengan satu tombol aksi. Item disusun di lib/dashboardInsights.js → attentionItems().

const SHOWN = 3;

export default function AttentionCard({ items, isDark, error }) {
  const navigate = useNavigate();
  const tones = tileTones(isDark);
  const dot = { danger: tones.danger.bar, warning: isDark ? '#FBBF24' : '#D97706' };
  const shown = items.slice(0, SHOWN);
  const overflow = attentionOverflow(items, SHOWN);

  const act = (a) => {
    if (a.kind === 'route') navigate(a.value);
    else window.dispatchEvent(new CustomEvent('jatahku:open-action', { detail: a.value }));
  };

  return (
    <section aria-labelledby="perlu-perhatian-title" className="card !px-4 md:!px-6 !pt-5 md:!pt-6 !pb-4 min-w-0">
      <div className="flex items-center gap-2 px-1 pb-2">
        <h2 id="perlu-perhatian-title" className="font-display font-bold text-lg" style={{ color: 'var(--text)' }}>Perlu perhatian</h2>
        {items.length > 0 && (
          <span className="min-w-[24px] h-6 px-1.5 rounded-full text-[13px] font-bold inline-flex items-center justify-center"
            style={{ background: tones.danger.bar, color: '#fff' }} aria-label={`${items.length} hal`}>
            {items.length}
          </span>
        )}
      </div>

      {shown.length === 0 ? (
        <div className="flex items-center gap-3 px-1 py-6">
          <span className="w-9 h-9 rounded-full inline-flex items-center justify-center shrink-0"
            style={{ background: isDark ? 'rgba(74,222,128,0.14)' : 'rgba(34,197,94,0.12)', color: tones.bars.green }}>
            <Icon name="check" size={18} weight="bold" />
          </span>
          <div>
            <p className="text-[15px] font-semibold" style={{ color: 'var(--text)' }}>Semua aman</p>
            <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
              {error ? 'Saran advisor sementara tidak tersedia.' : 'Tidak ada tagihan telat atau amplop habis.'}
            </p>
          </div>
        </div>
      ) : (
        <ul className="flex flex-col">
          {shown.map((it, i) => (
            <li key={it.id} className="flex items-center gap-3 px-1 py-3.5"
              style={i > 0 ? { borderTop: '1px solid var(--border)' } : undefined}>
              <span className="w-2.5 h-2.5 rounded-full shrink-0 self-start mt-[7px]" style={{ background: dot[it.tone] || dot.warning }}
                aria-label={it.tone === 'danger' ? 'Penting' : 'Perlu dicek'} role="img" />
              <div className="flex-1 min-w-0">
                <p className="text-[15px] font-semibold leading-snug" style={{ color: 'var(--text)' }}>{it.title}</p>
                {it.detail && <p className="text-[13px] mt-0.5 truncate" style={{ color: 'var(--text-muted)' }}>{it.detail}</p>}
              </div>
              <button type="button" onClick={() => act(it.action)}
                className="shrink-0 min-h-[44px] px-4 rounded-xl text-sm font-semibold transition-opacity hover:opacity-90"
                style={it.primary
                  ? { background: 'var(--text)', color: 'var(--card-bg)' }
                  : { background: isDark ? 'var(--page)' : 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)' }}>
                {it.action.label}
              </button>
            </li>
          ))}
        </ul>
      )}

      {overflow && (
        <p className="px-1 pt-3 text-[13px]" style={{ color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>{overflow}</p>
      )}
    </section>
  );
}
