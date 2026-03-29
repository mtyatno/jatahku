import { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (api.token) {
      api.getMe().then(u => {
        setUser(u);
        setLoading(false);
      }).catch(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (email, password) => {
    const result = await api.login(email, password);
    if (result.ok) {
      const u = await api.getMe();
      setUser(u);
    }
    return result;
  };

  const register = async (email, password, name, promoCode) => {
    const result = await api.register(email, password, name, promoCode);
    if (result.ok) {
      const u = await api.getMe();
      setUser(u);
    }
    return result;
  };

  const loginWithTgToken = async (token) => {
    const result = await api.loginWithTgToken(token);
    if (result.ok) {
      const u = await api.getMe();
      setUser(u);
    }
    return result;
  };

  const logout = () => {
    api.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, loginWithTgToken }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
