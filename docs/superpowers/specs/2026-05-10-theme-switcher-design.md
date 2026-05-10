# Theme Switcher — Design Spec

**Date:** 2026-05-10
**Status:** Approved

---

## Overview

Tambahkan theme switcher ke aplikasi Jatahku. User bisa memilih warna dasar di Settings dan toggle dark/light mode dari nav header kapan saja.

**6 kombinasi tema:**

| Warna | Light | Dark |
|-------|-------|------|
| 🌿 Hijau (default) | `hijau-light` | `hijau-dark` |
| 🌊 Laut | `laut-light` | `laut-dark` |
| 🌅 Senja | `senja-light` | `senja-dark` |

---

## Data Model & State

### Struktur
```
color: 'hijau' | 'laut' | 'senja'   // warna dasar
mode:  'light' | 'dark'             // mode terang/gelap
```

Keduanya digabung jadi `data-theme` attribute pada `<html>`:
```
data-theme="hijau-light"   // default
data-theme="laut-dark"     // contoh kombinasi lain
```

### Penyimpanan
- **localStorage** key: `jatahku_theme`
- Format: `{ color: 'hijau', mode: 'light' }`
- Dibaca saat mount, ditulis setiap kali user mengubah pilihan

### `src/hooks/useTheme.jsx` — Context + Hook

Implementasi sebagai **React Context** agar state tema dibagi semua komponen tanpa prop drilling:

```js
// ThemeProvider membungkus app di main.jsx
export function ThemeProvider({ children }) { ... }

// Hook untuk consume context — dipakai di Layout dan Settings
export function useTheme() {
  return useContext(ThemeContext);
}

// Ekspor dari hook:
{
  color,       // 'hijau' | 'laut' | 'senja'
  mode,        // 'light' | 'dark'
  setColor,    // (color) => void — dipakai di Settings
  toggleMode,  // () => void — dipakai di Layout header
}
```

`ThemeProvider` mengelola state dan side-effect:
- Init: baca localStorage, set `data-theme` pada `<html>` sebelum render pertama
- Setiap perubahan: tulis localStorage + update `data-theme`

**`main.jsx`** — satu-satunya file tambahan yang disentuh: wrap `<App>` dengan `<ThemeProvider>`.

---

## CSS Variables + Tailwind Config

### Pendekatan
CSS Custom Properties per tema, Tailwind membaca via `var()`. Tidak ada perubahan di file JSX selain `Layout.jsx` dan `Settings.jsx`.

### `tailwind.config.js` — warna custom → CSS variables
```js
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
  surface: 'var(--surface)',
  page:    'var(--page)',
}
```

`amber`, `danger`, `info` tidak berubah per tema — tetap hardcoded.

### `src/index.css` — 6 blok tema

**Light themes:**
```css
[data-theme="hijau-light"] {
  --brand-50: #E1F5EE; --brand-100: #9FE1CB; --brand-200: #5DCAA5;
  --brand-400: #1D9E75; --brand-600: #0F6E56;
  --brand-800: #085041; --brand-900: #04342C;
  --surface: #F1EFE8; --page: #FAFAF8;
  --card-bg: #ffffff; --border: #e5e7eb;
  --text: #2C2C2A; --text-muted: #6b7280;
}

[data-theme="laut-light"] {
  --brand-50: #eff6ff; --brand-100: #dbeafe; --brand-200: #bfdbfe;
  --brand-400: #3b82f6; --brand-600: #2563eb;
  --brand-800: #1e40af; --brand-900: #1e3a8a;
  --surface: #f0f7ff; --page: #f8faff;
  --card-bg: #ffffff; --border: #dbeafe;
  --text: #1e293b; --text-muted: #64748b;
}

[data-theme="senja-light"] {
  --brand-50: #fffbeb; --brand-100: #fef3c7; --brand-200: #fde68a;
  --brand-400: #f59e0b; --brand-600: #d97706;
  --brand-800: #92400e; --brand-900: #78350f;
  --surface: #fdf8f3; --page: #fffdf9;
  --card-bg: #ffffff; --border: #fde8c8;
  --text: #292524; --text-muted: #78716c;
}
```

**Dark themes:**
```css
[data-theme="hijau-dark"] {
  --brand-50: #1e3a2f; --brand-100: #14532d; --brand-200: #166534;
  --brand-400: #34d399; --brand-600: #10b981;
  --brand-800: #6ee7b7; --brand-900: #a7f3d0;
  --surface: #1e293b; --page: #0f172a;
  --card-bg: #1e293b; --border: #334155;
  --text: #e2e8f0; --text-muted: #94a3b8;
}

[data-theme="laut-dark"] {
  --brand-50: #1e3a5f; --brand-100: #1e40af; --brand-200: #1d4ed8;
  --brand-400: #60a5fa; --brand-600: #3b82f6;
  --brand-800: #93c5fd; --brand-900: #bfdbfe;
  --surface: #1e293b; --page: #0f172a;
  --card-bg: #1e293b; --border: #1e3a4f;
  --text: #e2e8f0; --text-muted: #94a3b8;
}

[data-theme="senja-dark"] {
  --brand-50: #3d2e00; --brand-100: #78350f; --brand-200: #92400e;
  --brand-400: #fbbf24; --brand-600: #f59e0b;
  --brand-800: #fcd34d; --brand-900: #fde68a;
  --surface: #1e293b; --page: #0f172a;
  --card-bg: #1e293b; --border: #3d2e00;
  --text: #e2e8f0; --text-muted: #94a3b8;
}
```

### Dark mode structural overrides (di `index.css`)

Menangani `bg-white`, `text-gray-*`, `.card` yang tidak bisa dicover hanya dengan brand vars:

```css
[data-theme*="-dark"] body {
  background: var(--page);
  color: var(--text);
}

[data-theme*="-dark"] .card {
  background: var(--card-bg);
  border-color: var(--border);
}

[data-theme*="-dark"] .input {
  background: var(--card-bg);
  border-color: var(--border);
  color: var(--text);
}

[data-theme*="-dark"] .input::placeholder {
  color: var(--text-muted);
}

/* Override hardcoded bg-white/border-gray yang dipakai di banyak tempat */
[data-theme*="-dark"] header,
[data-theme*="-dark"] nav {
  background: color-mix(in srgb, var(--card-bg) 90%, transparent);
  border-color: var(--border);
}
```

---

## Komponen yang Diubah

### File baru
- `src/hooks/useTheme.jsx` — ThemeContext + ThemeProvider + useTheme hook

### File dimodifikasi
| File | Perubahan |
|------|-----------|
| `tailwind.config.js` | brand/surface/page → CSS vars |
| `src/index.css` | 6 blok tema + dark structural overrides |
| `src/main.jsx` | Wrap `<App>` dengan `<ThemeProvider>` |
| `src/components/Layout.jsx` | Import `useTheme`, tambah toggle pill di header |
| `src/pages/Settings.jsx` | Tambah section "Tema Tampilan" dengan 3 kartu warna |

### Tidak disentuh
Semua page dan component lain: Dashboard, Envelopes, Transactions, Allocate, dll.

---

## UI Detail

### Toggle di Header (`Layout.jsx`)
Posisi: kanan header, sebelah kiri avatar user.

```
[☀️ Light] [🌙 Dark]   ← pill toggle, style seperti nav aktif
```

- Klik toggle → `toggleMode()`
- Style pill mengikuti warna brand aktif

### Color Picker di Settings (`Settings.jsx`)
Section baru "Tema Tampilan" dengan 3 kartu horizontal:

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│  gradient │  │  gradient │  │  gradient │
│  Hijau   │  │  Laut    │  │  Senja   │
│  ✓ aktif  │  │           │  │           │
└──────────┘  └──────────┘  └──────────┘
Gunakan toggle di header untuk mode gelap
```

Kartu aktif: border `brand-600`, ring tipis. Klik kartu lain → langsung berlaku.

---

## Error Handling

- localStorage tidak tersedia (private browsing): fallback ke in-memory state, tidak crash
- `data-theme` invalid: CSS variables undefined → browser fallback ke `initial` (tidak broken, hanya tidak berwarna)
- Default selalu `hijau-light` kalau localStorage kosong/corrupt

---

## Out of Scope

- Sinkronisasi tema ke server/akun (bisa ditambah di session berikutnya)
- Tema tambahan di luar 3 warna ini
- Kustomisasi warna per-user (color picker bebas)
