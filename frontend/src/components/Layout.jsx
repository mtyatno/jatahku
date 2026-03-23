import { useState, useEffect, useRef } from 'react';
import { NavLink, Outlet, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import NotificationBell from './NotificationBell';
import TelegramPrompt from './TelegramPrompt';

const navItems = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/envelopes', label: 'Amplop', icon: '✉️' },
  { to: '/transactions', label: 'Transaksi', icon: '📝' },
  { to: '/allocate', label: 'Alokasi', icon: '💰' },
  { to: '/langganan', label: 'Langganan', icon: '🔄' },
];

const menuItems = [
  { to: '/settings', label: 'Settings', icon: '⚙️' },
];

export default function Layout() {
  const { user, loading, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-brand-600 font-display text-xl font-bold animate-pulse">Jatahku</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" />;

  const initial = user.name ? user.name.charAt(0).toUpperCase() : '?';

  return (
    <div className="min-h-screen bg-page">
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-100 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <NavLink to="/" className="font-display text-xl font-bold text-brand-600">
              Jatah<span className="text-brand-400">ku</span>
            </NavLink>
            <nav className="hidden md:flex items-center gap-1">
              {[...navItems, ...menuItems].map(item => (
                <NavLink key={item.to} to={item.to} end={item.to === '/'}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                      isActive ? 'bg-brand-50 text-brand-600' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
                    }`}>
                  <span className="mr-1.5">{item.icon}</span>{item.label}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Notifications + Profile */}
          <div className="flex items-center gap-1">
          <NotificationBell />
          <div className="relative" ref={menuRef}>
            <button onClick={() => setMenuOpen(!menuOpen)}
              className="flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-gray-50 transition-colors">
              <div className="w-8 h-8 rounded-full bg-brand-50 flex items-center justify-center text-sm font-bold text-brand-600">
                {initial}
              </div>
              <span className="text-sm text-gray-600 hidden sm:block">{user.name}</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-gray-400">
                <path d="M3 5L6 8L9 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-12 w-56 bg-white rounded-xl shadow-lg border border-gray-100 py-2 z-50">
                <div className="px-4 py-2 border-b border-gray-50">
                  <p className="text-sm font-semibold">{user.name}</p>
                  <p className="text-xs text-gray-400">{user.email}</p>
                </div>
                <button onClick={() => { navigate('/settings'); setMenuOpen(false); }}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-3">
                  <span>⚙️</span> Profil & Settings
                </button>

                <div className="border-t border-gray-50 mt-1 pt-1">
                  <button onClick={() => { logout(); setMenuOpen(false); }}
                    className="w-full text-left px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 flex items-center gap-3">
                    <span>🚪</span> Logout
                  </button>
                </div>
              </div>
            )}
          </div>
          </div>
        </div>
      </header>

      {/* Mobile bottom nav — 5 items only, no Settings */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-100 z-50">
        <div className="flex justify-around py-2">
          {navItems.map(item => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 px-2 py-1 text-xs font-medium transition-colors ${
                  isActive ? 'text-brand-600' : 'text-gray-400'
                }`}>
              <span className="text-lg">{item.icon}</span>{item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <TelegramPrompt />
      <main className="max-w-6xl mx-auto px-4 py-6 pb-24 md:pb-6"><Outlet /></main>
    </div>
  );
}
