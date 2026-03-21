import { NavLink, Outlet, Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

const navItems = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/envelopes', label: 'Amplop', icon: '✉️' },
  { to: '/transactions', label: 'Transaksi', icon: '📝' },
  { to: '/allocate', label: 'Alokasi', icon: '💰' },
  { to: '/langganan', label: 'Langganan', icon: '🔄' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
];

export default function Layout() {
  const { user, loading, logout } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-brand-600 font-display text-xl font-bold animate-pulse">Jatahku</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" />;
  return (
    <div className="min-h-screen bg-page">
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-100 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <NavLink to="/" className="font-display text-xl font-bold text-brand-600">
              Jatah<span className="text-brand-400">ku</span>
            </NavLink>
            <nav className="hidden md:flex items-center gap-1">
              {navItems.map(item => (
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
          <span className="text-sm text-gray-500 hidden sm:block">{user.name}</span>
        </div>
      </header>
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
      <main className="max-w-6xl mx-auto px-4 py-6 pb-24 md:pb-6"><Outlet /></main>
    </div>
  );
}
