import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Envelopes from './pages/Envelopes';
import Transactions from './pages/Transactions';
import Allocate from './pages/Allocate';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/envelopes" element={<Envelopes />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/allocate" element={<Allocate />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
