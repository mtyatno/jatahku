// Rekomendasi alokasi AI Advisor (S14) → isi form. Murni, dites dengan node --test.
// Angka & alasan dari POST /advisor/allocation-recommendation; amplop penerima sisa
// income (`sisa_ke`) dari backend, frontend tidak mencocokkan nama amplop.

const sisaKeId = rec => (rec?.sisa_ke?.envelope_id != null ? String(rec.sisa_ke.envelope_id) : null);

// { envelope_id: jumlah } untuk form. Amplop penerima sisa dilewati (sisa income otomatis
// masuk ke sana saat disimpan); `fundable` (Set id) membatasi ke amplop yang ada di form.
export function recommendationAllocations(rec, fundable = null) {
  const skip = sisaKeId(rec);
  const out = {};
  (rec?.items || []).forEach(it => {
    const id = String(it.envelope_id);
    const amt = Number(it.recommended_amount) || 0;
    if (amt <= 0 || id === skip || (fundable && !fundable.has(id))) return;
    out[id] = amt;
  });
  return out;
}

// Persen tiap baris dari income (dibulatkan), untuk form dengan kolom %.
export function percentagesFor(allocations, income) {
  const out = {};
  if (!(income > 0)) return out;
  Object.entries(allocations).forEach(([id, amt]) => { out[id] = Math.round((amt / income) * 100); });
  return out;
}

// { envelope_id: { alasan: [teks], keyakinan } } — alasan per amplop di bawah barisnya.
export function reasonsById(rec) {
  const out = {};
  (rec?.items || []).forEach(it => {
    const alasan = (it.alasan || []).map(a => a.teks).filter(Boolean);
    out[String(it.envelope_id)] = { alasan, keyakinan: it.keyakinan || null };
  });
  return out;
}

// Amplop yang tampil di form: semua kecuali penerima sisa (barisnya "→ {nama} (otomatis)").
export function formEnvelopes(envelopes, sisaKe) {
  const skip = sisaKe?.envelope_id != null ? String(sisaKe.envelope_id) : null;
  return envelopes.filter(e => String(e.id) !== skip);
}
