import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import Layout from './components/Layout';
import { OfflineBanner, InstallPrompt } from './components/PWAPrompt';
import Login from './pages/Login';
import TgLogin from './pages/TgLogin';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import HapusAkun from './pages/HapusAkun';
import Dashboard from './pages/Dashboard';
import Envelopes from './pages/Envelopes';
import Transactions from './pages/Transactions';
import Allocate from './pages/Allocate';
import Langganan from './pages/Langganan';
import Analytics from './pages/Analytics';
import Admin from './pages/Admin';
import Upgrade from './pages/Upgrade';
import Settings from './pages/Settings';
import Laporan from './pages/Laporan';
import LaporanDetail from './pages/LaporanDetail';
import Bagikan from './pages/Bagikan';
import RuangKelola from './pages/RuangKelola';

// Fitur Tambahan (Plugin H3): potongan bundle sendiri, hanya diunduh saat halamannya dibuka.
const FiturTambahan = lazy(() => import('./pages/FiturTambahan'));
const PluginPage = lazy(() => import('./plugins/PluginPage'));
const memuat = <div className="text-center py-12 text-gray-400">Loading...</div>;

export default function App() {
  return (
    <AuthProvider>
      <OfflineBanner />
      <InstallPrompt />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/auth/tg" element={<TgLogin />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/hapus-akun" element={<HapusAkun />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/envelopes" element={<Envelopes />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/allocate" element={<Allocate />} />
            <Route path="/langganan" element={<Langganan />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/laporan" element={<Laporan />} />
            <Route path="/laporan/:id" element={<LaporanDetail />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/upgrade" element={<Upgrade />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/bagikan" element={<Bagikan />} />
            <Route path="/ruang" element={<RuangKelola />} />
            <Route path="/fitur-tambahan" element={<Suspense fallback={memuat}><FiturTambahan /></Suspense>} />
            <Route path="/p/:pluginId/*" element={<Suspense fallback={memuat}><PluginPage /></Suspense>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
