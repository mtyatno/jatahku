# Theme Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambahkan 6 kombinasi tema (3 warna × light/dark) ke Jatahku — pilih warna di Settings, toggle gelap/terang di nav header.

**Architecture:** ThemeContext (React Context) menyimpan `{ color, mode }`, persist ke localStorage, dan set `data-theme` attribute pada `<html>`. CSS Custom Properties per tema mengisi nilai warna yang direferensikan Tailwind via `var()`. Dark mode di-handle lewat CSS selector `[data-theme*="-dark"]` yang override komponen bersama.

**Tech Stack:** React Context API, CSS Custom Properties, Tailwind CSS v3 dengan `var()` reference.

---

## File Map

| File | Status | Tanggung jawab |
|------|--------|----------------|
| `frontend/src/hooks/useTheme.jsx` | **Baru** | ThemeContext, ThemeProvider, useTheme hook |
| `frontend/src/index.css` | Modifikasi | 6 blok CSS vars + dark structural overrides |
| `frontend/tailwind.config.js` | Modifikasi | brand/surface/page → CSS vars |
| `frontend/src/main.jsx` | Modifikasi | Wrap App dengan ThemeProvider |
| `frontend/src/components/Layout.jsx` | Modifikasi | Toggle ☀️/🌙 di header |
| `frontend/src/pages/Settings.jsx` | Modifikasi | Color picker section |

---

## Task 1: useTheme — ThemeContext + ThemeProvider + hook

**Files:**
- Create: `frontend/src/hooks/useTheme.jsx`

- [ ] **Step 1: Buat file hook**

```jsx
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
```

- [ ] **Step 2: Verifikasi file tersimpan, tidak ada syntax error**

Jalankan di terminal frontend:
```bash
cd frontend && node --input-type=module <<'EOF'
import('./src/hooks/useTheme.jsx').then(() => console.log('OK')).catch(e => console.error(e))
EOF
```

Kalau environment tidak support ESM langsung, cukup pastikan file ada dan tidak ada merah di editor.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useTheme.jsx
git commit -m "feat: add ThemeContext with localStorage persistence"
```

---

## Task 2: CSS Variables — 6 tema + dark structural overrides

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Tambahkan 6 blok tema di AWAL `index.css` (sebelum `@tailwind base`)**

```css
/* ── TEMA: Hijau (default) ── */
[data-theme="hijau-light"] {
  --brand-50: #E1F5EE; --brand-100: #9FE1CB; --brand-200: #5DCAA5;
  --brand-400: #1D9E75; --brand-600: #0F6E56;
  --brand-800: #085041; --brand-900: #04342C;
  --surface: #F1EFE8; --page: #FAFAF8;
  --card-bg: #ffffff; --border: #e5e7eb;
  --text: #2C2C2A; --text-muted: #6b7280;
}
[data-theme="hijau-dark"] {
  --brand-50: #1e3a2f; --brand-100: #14532d; --brand-200: #166534;
  --brand-400: #34d399; --brand-600: #10b981;
  --brand-800: #6ee7b7; --brand-900: #a7f3d0;
  --surface: #1e293b; --page: #0f172a;
  --card-bg: #1e293b; --border: #334155;
  --text: #e2e8f0; --text-muted: #94a3b8;
}

/* ── TEMA: Laut ── */
[data-theme="laut-light"] {
  --brand-50: #eff6ff; --brand-100: #dbeafe; --brand-200: #bfdbfe;
  --brand-400: #3b82f6; --brand-600: #2563eb;
  --brand-800: #1e40af; --brand-900: #1e3a8a;
  --surface: #f0f7ff; --page: #f8faff;
  --card-bg: #ffffff; --border: #dbeafe;
  --text: #1e293b; --text-muted: #64748b;
}
[data-theme="laut-dark"] {
  --brand-50: #1e3a5f; --brand-100: #1e40af; --brand-200: #1d4ed8;
  --brand-400: #60a5fa; --brand-600: #3b82f6;
  --brand-800: #93c5fd; --brand-900: #bfdbfe;
  --surface: #1e293b; --page: #0f172a;
  --card-bg: #1e293b; --border: #1e3a4f;
  --text: #e2e8f0; --text-muted: #94a3b8;
}

/* ── TEMA: Senja ── */
[data-theme="senja-light"] {
  --brand-50: #fffbeb; --brand-100: #fef3c7; --brand-200: #fde68a;
  --brand-400: #f59e0b; --brand-600: #d97706;
  --brand-800: #92400e; --brand-900: #78350f;
  --surface: #fdf8f3; --page: #fffdf9;
  --card-bg: #ffffff; --border: #fde8c8;
  --text: #292524; --text-muted: #78716c;
}
[data-theme="senja-dark"] {
  --brand-50: #3d2e00; --brand-100: #78350f; --brand-200: #92400e;
  --brand-400: #fbbf24; --brand-600: #f59e0b;
  --brand-800: #fcd34d; --brand-900: #fde68a;
  --surface: #1e293b; --page: #0f172a;
  --card-bg: #1e293b; --border: #3d2e00;
  --text: #e2e8f0; --text-muted: #94a3b8;
}

/* ── FALLBACK: pastikan hijau-light aktif kalau data-theme belum di-set ── */
:root {
  --brand-50: #E1F5EE; --brand-100: #9FE1CB; --brand-200: #5DCAA5;
  --brand-400: #1D9E75; --brand-600: #0F6E56;
  --brand-800: #085041; --brand-900: #04342C;
  --surface: #F1EFE8; --page: #FAFAF8;
  --card-bg: #ffffff; --border: #e5e7eb;
  --text: #2C2C2A; --text-muted: #6b7280;
}
```

- [ ] **Step 2: Tambahkan dark structural overrides di AKHIR `index.css` (setelah semua `@layer`)**

```css
/* ── DARK MODE: structural overrides ── */
[data-theme*="-dark"] body {
  background-color: var(--page);
  color: var(--text);
}

[data-theme*="-dark"] .card {
  background-color: var(--card-bg);
  border-color: var(--border);
}

[data-theme*="-dark"] .input {
  background-color: var(--card-bg);
  border-color: var(--border);
  color: var(--text);
}

[data-theme*="-dark"] .input::placeholder {
  color: var(--text-muted);
}

/* Header */
[data-theme*="-dark"] header {
  background-color: rgba(30, 41, 59, 0.85) !important;
  border-color: var(--border);
}

/* Nav bottom mobile */
[data-theme*="-dark"] nav {
  background-color: var(--card-bg);
  border-color: var(--border);
}

/* Dropdown menu */
[data-theme*="-dark"] .absolute.bg-white {
  background-color: var(--card-bg);
  border-color: var(--border);
}

/* Gray text overrides */
[data-theme*="-dark"] .text-gray-400 { color: #94a3b8; }
[data-theme*="-dark"] .text-gray-500 { color: #94a3b8; }
[data-theme*="-dark"] .text-gray-600 { color: #cbd5e1; }
[data-theme*="-dark"] .text-gray-700 { color: #e2e8f0; }
[data-theme*="-dark"] .text-gray-900 { color: #f1f5f9; }

/* Gray background overrides */
[data-theme*="-dark"] .bg-gray-50  { background-color: #1e293b; }
[data-theme*="-dark"] .bg-gray-100 { background-color: #334155; }
[data-theme*="-dark"] .hover\:bg-gray-50:hover  { background-color: #334155; }
[data-theme*="-dark"] .hover\:bg-gray-100:hover { background-color: #475569; }
[data-theme*="-dark"] .hover\:bg-red-50:hover   { background-color: #450a0a; }

/* Border overrides */
[data-theme*="-dark"] .border-gray-100 { border-color: #334155; }
[data-theme*="-dark"] .border-gray-200 { border-color: #475569; }

/* Amber/warning cards in dark */
[data-theme*="-dark"] .bg-amber-50  { background-color: #2d1f00; }
[data-theme*="-dark"] .text-amber-600 { color: #fbbf24; }
[data-theme*="-dark"] .bg-brand-50  { background-color: var(--brand-50); }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: add CSS custom properties for 6 themes + dark structural overrides"
```

---

## Task 3: Tailwind Config — brand colors → CSS variables

**Files:**
- Modify: `frontend/tailwind.config.js`

- [ ] **Step 1: Ganti blok `colors` di `tailwind.config.js`**

Ganti seluruh isi file dengan:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  'var(--brand-50)',
          100: 'var(--brand-100)',
          200: 'var(--brand-200)',
          400: 'var(--brand-400)',
          600: 'var(--brand-600)',
          800: 'var(--brand-800)',
          900: 'var(--brand-900)',
        },
        amber: {
          50: '#FAEEDA', 200: '#EF9F27', 400: '#BA7517', 600: '#854F0B',
        },
        danger: { 400: '#E24B4A', 600: '#A32D2D' },
        info: { 400: '#378ADD' },
        surface: 'var(--surface)',
        page:    'var(--page)',
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'sans-serif'],
        body:    ['"Plus Jakarta Sans"', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 2: Verifikasi app masih tampil normal (hijau-light = warna lama)**

```bash
cd frontend && npm run dev
```

Buka `http://localhost:5173`. App harus terlihat **identik** dengan sebelumnya karena `hijau-light` pakai nilai hex yang sama dengan config lama. Tidak ada perubahan visual.

- [ ] **Step 3: Commit**

```bash
git add frontend/tailwind.config.js
git commit -m "feat: tailwind brand/surface/page colors now read from CSS custom properties"
```

---

## Task 4: main.jsx — Wrap App dengan ThemeProvider

**Files:**
- Modify: `frontend/src/main.jsx`

- [ ] **Step 1: Update `main.jsx`**

```jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { ThemeProvider } from './hooks/useTheme';

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    window.location.reload();
  });
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </React.StrictMode>
);
```

- [ ] **Step 2: Verifikasi — buka app, buka DevTools, cek `<html>` punya `data-theme="hijau-light"`**

Di console browser:
```js
document.documentElement.getAttribute('data-theme') // → "hijau-light"
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/main.jsx
git commit -m "feat: wrap app with ThemeProvider"
```

---

## Task 5: Layout.jsx — Toggle ☀️/🌙 di header

**Files:**
- Modify: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: Tambah import `useTheme` di baris atas**

Tambahkan di bawah baris `import { useAuth }...`:
```jsx
import { useTheme } from '../hooks/useTheme';
```

- [ ] **Step 2: Tambah `toggleMode` dan `mode` di dalam fungsi `Layout()`**

Tambahkan di bawah baris `const { user, loading, logout } = useAuth();`:
```jsx
const { mode, toggleMode } = useTheme();
```

- [ ] **Step 3: Tambah toggle button di header, dalam `<div className="flex items-center gap-1">`**

Temukan blok ini di `Layout.jsx`:
```jsx
<div className="flex items-center gap-1">
  <NotificationBell />
  <div className="relative" ref={menuRef}>
```

Ganti dengan:
```jsx
<div className="flex items-center gap-1">
  <NotificationBell />
  <button
    onClick={toggleMode}
    className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 transition-colors text-base"
    title={mode === 'light' ? 'Mode Gelap' : 'Mode Terang'}
  >
    {mode === 'light' ? '🌙' : '☀️'}
  </button>
  <div className="relative" ref={menuRef}>
```

- [ ] **Step 4: Verifikasi — klik ikon di header, app berubah ke dark mode**

Buka `http://localhost:5173`. Klik ikon 🌙 di header. Seluruh app harus berubah ke dark. Klik lagi → kembali light. Refresh halaman → pilihan terakhir tetap tersimpan.

Cek di DevTools console:
```js
JSON.parse(localStorage.getItem('jatahku_theme'))
// → { color: "hijau", mode: "dark" }  (atau light)
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.jsx
git commit -m "feat: add dark/light mode toggle in header"
```

---

## Task 6: Settings.jsx — Color picker section

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Tambah import `useTheme` di baris atas `Settings.jsx`**

Tambahkan di bawah `import { useAuth }...`:
```jsx
import { useTheme } from '../hooks/useTheme';
```

- [ ] **Step 2: Tambah `color` dan `setColor` di dalam fungsi `Settings()`**

Tambahkan di bawah baris `const { user, logout } = useAuth();`:
```jsx
const { color: themeColor, setColor } = useTheme();
```

- [ ] **Step 3: Tambah komponen ThemePicker sebelum fungsi `Settings`**

Sisipkan fungsi berikut **sebelum** `export default function Settings()`:

```jsx
const THEME_OPTIONS = [
  {
    id: 'hijau',
    label: '🌿 Hijau',
    from: '#1D9E75',
    to: '#5DCAA5',
  },
  {
    id: 'laut',
    label: '🌊 Laut',
    from: '#2563eb',
    to: '#60a5fa',
  },
  {
    id: 'senja',
    label: '🌅 Senja',
    from: '#d97706',
    to: '#fbbf24',
  },
];
```

- [ ] **Step 4: Tambah section tema di JSX `Settings`, tepat setelah `<h1 className="...">Settings</h1>`**

```jsx
{/* Tema Tampilan */}
<div className="card">
  <h3 className="font-semibold text-sm mb-3">🎨 Tema Tampilan</h3>
  <div className="grid grid-cols-3 gap-3">
    {THEME_OPTIONS.map(t => (
      <button
        key={t.id}
        onClick={() => setColor(t.id)}
        className={`rounded-xl overflow-hidden border-2 transition-all ${
          themeColor === t.id
            ? 'border-brand-600 ring-2 ring-brand-200'
            : 'border-transparent hover:border-brand-200'
        }`}
      >
        <div
          className="h-10 w-full"
          style={{ background: `linear-gradient(135deg, ${t.from}, ${t.to})` }}
        />
        <div className="py-2 text-xs font-semibold text-center">{t.label}</div>
      </button>
    ))}
  </div>
  <p className="text-xs text-gray-400 mt-3">
    Gunakan toggle ☀️/🌙 di header untuk ganti mode gelap.
  </p>
</div>
```

- [ ] **Step 5: Verifikasi — buka Settings, klik Laut, seluruh app berubah ke biru. Klik Senja → oranye. Refresh → warna tersimpan.**

Cek localStorage:
```js
JSON.parse(localStorage.getItem('jatahku_theme'))
// → { color: "laut", mode: "light" }
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Settings.jsx
git commit -m "feat: add color theme picker in Settings"
```

---

## Task 7: Build & Deploy

- [ ] **Step 1: Build frontend**

```bash
cd frontend && npm run build
```

Harus selesai tanpa error. Pastikan tidak ada warning tentang CSS vars yang tidak dikenali.

- [ ] **Step 2: Push ke main → CI/CD jalan otomatis**

```bash
git push origin main
```

- [ ] **Step 3: Verifikasi di production**

Buka `https://jatahku.com`, cek:
1. Default tema hijau-light tetap normal
2. Toggle 🌙 di header berfungsi
3. Settings → Tema Tampilan menampilkan 3 kartu warna
4. Pilihan warna tersimpan setelah refresh
