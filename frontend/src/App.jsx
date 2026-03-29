import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import Layout from './components/Layout';
import { OfflineBanner, InstallPrompt } from './components/PWAPrompt';
import Login from './pages/Login';
import TgLogin from './pages/TgLogin';
import Dashboard from './pages/Dashboard';
import Envelopes from './pages/Envelopes';
import Transactions from './pages/Transactions';
import Allocate from './pages/Allocate';
import Langganan from './pages/Langganan';
import Analytics from './pages/Analytics';
import Admin from './pages/Admin';
import Upgrade from './pages/Upgrade';
import Settings from './pages/Settings';

export default function App() {
  return (
    <AuthProvider>
      <OfflineBanner />
      <InstallPrompt />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/auth/tg" element={<TgLogin />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/envelopes" element={<Envelopes />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/allocate" element={<Allocate />} />
            <Route path="/langganan" element={<Langganan />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/upgrade" element={<Upgrade />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
