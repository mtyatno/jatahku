// Registry kartu Beranda di frontend (Plugin B2, 01-kajian.md "Kontrak kartu di frontend").
// Kunci sama dengan registry server (`app/services/dashboard/registry.py`). Data kartu datang dari
// POST /dashboard/data; komponen hanya memformat (AGENTS.md "Plugin dan ruang" aturan 6).
//
// Definisi: { key, Component, kind: 'kpi' | 'link' | 'card', alignStart, ownRow, kosong(entri, ctx) }
// - kind menentukan jarak baris (lib/dashboardRegistry.js rowGapAbove), meniru Beranda lama.
// - kosong(entri, ctx) → true = kartu tidak digambar (mis. AI Advisor di periode lalu, Target tabungan
//   tanpa amplop tabungan); baris lalu disusun ulang tanpa lubang.
// - Kartu plugin (H3) mendaftar dari src/plugins/<id>/cards.js dengan `React.lazy`.

const CARDS = new Map();

export function registerCard(def) {
  CARDS.set(def.key, { kind: 'card', alignStart: false, ownRow: false, kosong: () => false, ...def });
}

export const getCard = (key) => CARDS.get(key);
export const knownCard = (key) => CARDS.has(key);
export const refreshEvents = () => [...new Set([...CARDS.values()].flatMap(c => c.refreshOn || []))];
