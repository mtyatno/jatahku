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
const PLUGIN = new Set();

export function registerCard(def) {
  CARDS.set(def.key, { kind: 'card', alignStart: false, ownRow: false, kosong: () => false, ...def });
}

/** Ganti semua kartu plugin terdaftar dengan `defs` (Plugin H3: kartu plugin yang aktif di ruang ini). Kartu yang
 *  tidak ada lagi di `defs` dilepas, jadi tata letak tidak pernah menggambar kartu plugin yang dijeda atau dicopot. */
export function gantiKartuPlugin(defs) {
  for (const key of PLUGIN) CARDS.delete(key);
  PLUGIN.clear();
  for (const def of defs) {
    if (CARDS.has(def.key)) continue;       // kunci inti tidak pernah ditimpa plugin
    registerCard(def);
    PLUGIN.add(def.key);
  }
}

export const getCard = (key) => CARDS.get(key);
export const knownCard = (key) => CARDS.has(key);
export const refreshEvents = () => [...new Set([...CARDS.values()].flatMap(c => c.refreshOn || []))];
