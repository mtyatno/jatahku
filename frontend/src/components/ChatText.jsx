import { Fragment } from 'react';
import { barLevel, chatSegments } from '../lib/chatIcons';
import { EnvelopeIcon, Icon } from './Icon';

// Teks balasan bot dengan emoji/simbol diganti elemen visual aplikasi:
// ikon Phosphor, titik status, bar pemakaian, dan garis pemisah.
// Pemetaannya di lib/chatIcons.js; teks lain apa adanya.

const TONE = {
  brand: 'text-brand-600',
  ok: 'text-brand-600',
  muted: 'text-gray-400',
  warn: '',
  bad: '',
  fire: '',
};
const TONE_STYLE = {
  warn: { color: '#E59A1A' },
  bad: { color: '#E24B4A' },
  fire: { color: '#F2711C' },
};
const DOT = {
  ok: 'bg-[#1D9E75]',
  warn: 'bg-[#EF9F27]',
  bad: 'bg-[#E24B4A]',
  info: 'bg-[#2563EB]',
  none: 'border-[1.5px] border-gray-300',
};
const BAR = { ok: 'bg-brand-400', warn: 'bg-[#EF9F27]', bad: 'bg-[#E24B4A]' };

export default function ChatText({ text, size = 16 }) {
  return chatSegments(text).map((s, i) => {
    switch (s.t) {
      case 'text':
        return <Fragment key={i}>{s.v}</Fragment>;
      case 'icon':
        return (
          <span key={i} className={`inline-flex align-[-0.2em] ${TONE[s.tone] || ''}`} style={TONE_STYLE[s.tone]}
            role="img" aria-label={s.v}>
            <Icon name={s.icon} size={size} weight="duotone" color="currentColor" />
          </span>
        );
      case 'emoji':
        return (
          <span key={i} className="inline-flex align-[-0.2em] text-brand-600" role="img" aria-label={s.v}>
            <EnvelopeIcon value={s.v} size={size} color="currentColor" />
          </span>
        );
      case 'dot':
        return (
          <span key={i} className={`inline-block w-2.5 h-2.5 rounded-full align-middle mx-0.5 ${DOT[s.level]}`}
            role="img" aria-label={s.v} />
        );
      case 'bar': {
        const pct = Math.round(Math.min(s.ratio, 1) * 100);
        return (
          <span key={i} className="inline-block align-middle w-14 h-1.5 rounded-full overflow-hidden"
            style={{ background: 'var(--border)' }} role="img" aria-label={`${pct}%`}>
            <span className={`block h-full rounded-full ${BAR[barLevel(s.ratio)]}`} style={{ width: `${Math.max(pct, s.ratio > 0 ? 6 : 0)}%` }} />
          </span>
        );
      }
      case 'rule':
        return <span key={i} className="inline-block w-full h-px align-middle" style={{ background: 'var(--border)' }} aria-hidden="true" />;
      default:
        return null;
    }
  });
}
