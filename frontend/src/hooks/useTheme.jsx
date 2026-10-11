import { createContext, useContext, useState } from 'react';
import { DEFAULT, readStorage, STORAGE_KEY, VALID_COLORS, VALID_MODES } from '../lib/theme';

const ThemeContext = createContext(null);

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

export { DEFAULT, readStorage, STORAGE_KEY, VALID_COLORS, VALID_MODES };
