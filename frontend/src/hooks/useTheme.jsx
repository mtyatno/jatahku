import { createContext, useContext, useState } from 'react';

const ThemeContext = createContext(null);

const STORAGE_KEY = 'jatahku_theme';
const VALID_COLORS = ['hijau', 'laut', 'senja'];
const VALID_MODES = ['light', 'dark'];
const DEFAULT = { color: 'hijau', mode: 'light' };

function readStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT;
    const p = JSON.parse(raw);
    return {
      color: VALID_COLORS.includes(p.color) ? p.color : DEFAULT.color,
      mode: VALID_MODES.includes(p.mode) ? p.mode : DEFAULT.mode,
    };
  } catch {
    return DEFAULT;
  }
}

function applyTheme(color, mode) {
  document.documentElement.setAttribute('data-theme', `${color}-${mode}`);
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    const t = readStorage();
    applyTheme(t.color, t.mode);
    return t;
  });

  const setColor = (color) => {
    if (!VALID_COLORS.includes(color)) return;
    const next = { ...theme, color };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch {}
    applyTheme(next.color, next.mode);
    setTheme(next);
  };

  const toggleMode = () => {
    const next = { ...theme, mode: theme.mode === 'light' ? 'dark' : 'light' };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch {}
    applyTheme(next.color, next.mode);
    setTheme(next);
  };

  return (
    <ThemeContext.Provider value={{ ...theme, setColor, toggleMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
