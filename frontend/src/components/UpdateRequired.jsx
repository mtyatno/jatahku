// Layar "perlu update" (paket mobile 1.3): tampil hanya bila /app/config
// menyatakan versi klien di bawah min_supported_version. Web tidak pernah
// mendapat status ini (web diperbarui lewat service worker).
export default function UpdateRequired({ config }) {
  const storeUrl = config?.update?.store_url;
  return (
    <div className="min-h-screen bg-page flex items-center justify-center px-6">
      <div className="max-w-sm w-full text-center rounded-2xl p-8"
        style={{ background: 'var(--card-bg)', border: '1px solid var(--border)' }}>
        <p className="text-brand-600 font-display text-xl font-bold">Jatahku</p>
        <h1 className="mt-4 text-lg font-bold" style={{ color: 'var(--text)' }}>Perlu pembaruan</h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>
          Versi aplikasi ini sudah tidak didukung. Perbarui ke versi terbaru supaya
          catatanmu tetap tersimpan dengan benar.
        </p>
        {storeUrl && (
          <a href={storeUrl} target="_blank" rel="noopener noreferrer"
            className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white">
            Perbarui sekarang
          </a>
        )}
      </div>
    </div>
  );
}
