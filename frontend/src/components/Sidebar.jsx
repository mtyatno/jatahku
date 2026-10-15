import { NavLink } from 'react-router-dom';
import { Icon } from './Icon';

// Menu kiri untuk layar lebar (lg+): tetap di tempat (fixed) saat konten di-scroll.
// HP & tablet tetap memakai header atas + bottom nav di Layout.
// Tidak pernah di-scroll: tinggi pill & jarak mengecil mengikuti tinggi layar (clamp + vh),
// dan Papan disiplin disembunyikan bila layar terlalu pendek.

export const SIDEBAR_WIDTH = 264;

// Tinggi pill menu: 48px di layar tinggi, turun sampai 34px di layar pendek / zoom besar.
const ITEM_HEIGHT = 'clamp(34px, 5.2vh, 48px)';

const AVATAR_COLORS = ['var(--brand-400)', '#A5A8F7', '#F5B84A', '#F59AAE', '#7DD3FC'];

function NavItem({ to, icon, label, badge, end }) {
  return (
    <NavLink to={to} end={end}
      className={({ isActive }) =>
        `group flex items-center gap-3 px-4 rounded-xl text-[15px] transition-colors ${isActive ? 'font-bold' : 'font-medium'}`}
      style={({ isActive }) => ({
        height: ITEM_HEIGHT,
        background: isActive ? 'var(--sidebar-active, rgba(148,163,184,0.12))' : 'transparent',
        color: isActive ? 'var(--text)' : 'var(--text-muted)',
      })}>
      <Icon name={icon} size={20} weight="regular" />
      <span className="flex-1">{label}</span>
      {badge > 0 && (
        <span className="min-w-[22px] h-[22px] px-1.5 rounded-full text-xs font-bold inline-flex items-center justify-center"
          style={{ background: '#E24B4A', color: '#fff' }}
          aria-label={`${badge} perlu dibayar`}>
          {badge}
        </span>
      )}
    </NavLink>
  );
}

function Leaderboard({ members }) {
  return (
    <div className="rounded-2xl px-4 py-3 flex flex-col gap-2 [@media(max-height:540px)]:hidden" style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
      <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>Papan disiplin</p>
      <ul className="flex flex-col gap-2">
        {members.map((m, i) => (
          <li key={m.user_id} className="flex items-center gap-3"
            title={`Rekor ${m.longest_streak} hari · total ${m.total_logged_days} hari tercatat${m.logged_today ? ' · sudah catat hari ini' : ''}`}>
            <span className="w-7 h-7 rounded-full shrink-0 inline-flex items-center justify-center text-[13px] font-bold"
              style={{ background: AVATAR_COLORS[i % AVATAR_COLORS.length], color: '#0f172a' }} aria-hidden="true">
              {(m.name || '?').charAt(0).toUpperCase()}
            </span>
            <span className="flex-1 min-w-0 truncate text-[15px]" style={{ color: 'var(--text)', fontWeight: m.is_me ? 600 : 500 }}>
              {(m.name || '').split(' ')[0]}
            </span>
            <span className="shrink-0 text-sm tabular-nums" style={{ color: m.current_streak > 0 ? 'var(--text)' : 'var(--text-muted)', fontWeight: m.current_streak > 0 ? 700 : 400 }}>
              {m.current_streak > 0 ? `${m.current_streak} hari` : '—'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Sidebar({ items, langgananBadge, leaderboard, isAdmin, mode, onToggleMode }) {
  return (
    <aside className="hidden lg:flex fixed inset-y-0 left-0 z-30 flex-col px-4 overflow-hidden"
      style={{
        width: SIDEBAR_WIDTH, background: 'var(--page)', borderRight: '1px solid var(--border)',
        paddingTop: 'clamp(14px, 2.6vh, 28px)', paddingBottom: 'clamp(10px, 2vh, 20px)',
      }}>
      <NavLink to="/" className="px-3 font-display text-[26px] leading-none font-bold tracking-tight" style={{ color: 'var(--text)', marginBottom: 'clamp(14px, 3.4vh, 32px)' }} aria-label="Jatahku — Beranda">
        jatahku<span style={{ color: 'var(--brand-400)' }}>.</span>
      </NavLink>

      <div role="navigation" aria-label="Menu utama" className="flex flex-col gap-0.5">
        {items.map(item => (
          <NavItem key={item.to} {...item} end={item.to === '/'}
            badge={item.to === '/langganan' ? langgananBadge : 0} />
        ))}
        {isAdmin && <NavItem to="/admin" icon="admin" label="Admin" />}
      </div>

      <div className="flex-1 min-h-3" />

      {leaderboard.length > 0 && <Leaderboard members={leaderboard} />}

      <div className="flex items-center gap-1" style={{ borderTop: '1px solid var(--border)', marginTop: 'clamp(8px, 2vh, 20px)', paddingTop: 'clamp(6px, 1.6vh, 16px)' }}>
        <div className="flex-1 min-w-0">
          <NavItem to="/settings" icon="settings" label="Pengaturan" />
        </div>
        <button type="button" onClick={onToggleMode}
          className="w-10 h-10 shrink-0 rounded-xl inline-flex items-center justify-center transition-colors hover:bg-black/5"
          style={{ color: 'var(--text-muted)' }}
          aria-label={mode === 'light' ? 'Ganti ke mode gelap' : 'Ganti ke mode terang'}
          title={mode === 'light' ? 'Mode gelap' : 'Mode terang'}>
          <Icon name={mode === 'light' ? 'moon' : 'sun'} size={20} weight="regular" />
        </button>
      </div>
    </aside>
  );
}
