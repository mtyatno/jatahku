import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';

export default function Upgrade() {
  const [price, setPrice] = useState(null);
  const [banks, setBanks] = useState([]);
  const [promo, setPromo] = useState('');
  const [promoApplied, setPromoApplied] = useState(false);
  const [order, setOrder] = useState(null);
  const [orders, setOrders] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState('');
  const [step, setStep] = useState(1);
  const [copyBank, setCopyBank] = useState(-1); // 1=pricing, 2=payment, 3=upload, 4=done

  useEffect(() => {
    loadPrice();
    loadOrders();
    api.request('/payment/bank-accounts').then(r => r.ok ? r.json() : []).then(setBanks);
  }, []);

  const loadPrice = async (code) => {
    const url = code ? `/payment/price?promo_code=${encodeURIComponent(code)}` : '/payment/price';
    const r = await api.request(url);
    if (r.ok) setPrice(await r.json());
  };

  const loadOrders = async () => {
    const r = await api.request('/payment/my-orders');
    if (r.ok) setOrders(await r.json());
  };

  const applyPromo = () => {
    if (!promo.trim()) return;
    loadPrice(promo.trim());
    setPromoApplied(true);
  };

  const createOrder = async () => {
    const r = await api.request('/payment/create-order', {
      method: 'POST',
      body: JSON.stringify({ promo_code: promoApplied ? promo : null }),
    });
    if (r.ok) {
      const data = await r.json();
      if (data.status === 'completed') {
        setStep(4);
        setMsg('Selamat! Kamu sekarang Pro!');
        return;
      }
      setOrder(data);
      setStep(2);
    } else {
      const d = await r.json();
      setMsg(d.detail || 'Error');
    }
  };

  const uploadProof = async (e) => {
    const file = e.target.files[0];
    if (!file || !order) return;
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    const baseUrl = api.baseUrl || 'https://api.jatahku.com';
    const r = await fetch(`${baseUrl}/payment/upload-proof/${order.order_id}`, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + api.token },
      body: form,
    });
    if (r.ok) {
      setStep(3);
      setMsg('Bukti transfer diterima! Admin akan memverifikasi dalam 1x24 jam.');
    }
    setUploading(false);
  };

  if (!price) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const statusLabel = (s) => ({
    pending: '⏳ Menunggu pembayaran',
    waiting_confirmation: '🔍 Menunggu verifikasi admin',
    completed: '✅ Selesai',
    rejected: '❌ Ditolak',
  }[s] || s);

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="text-center">
        <h1 className="text-2xl font-display font-bold">Upgrade ke Pro</h1>
        <p className="text-sm text-gray-500 mt-1">Sekali bayar, selamanya unlimited</p>
      </div>

      {msg && <div className="bg-green-50 border border-green-200 text-sm px-4 py-3 rounded-xl text-green-700">{msg}</div>}

      {step === 1 && (
        <>
          {/* Features comparison */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-semibold">Pro mendapat:</span>
              <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full font-bold">⭐ LIFETIME</span>
            </div>
            <div className="space-y-2 text-sm">
              {['Unlimited amplop', 'Unlimited transaksi/bulan', 'Unlimited langganan', 'Cooling period & envelope lock', 'Daily spending limit', 'Export CSV & laporan', 'Analytics & prediksi', 'Household bersama'].map((f, i) => (
                <div key={i} className="flex items-center gap-2"><span className="text-brand-600 font-bold">✓</span><span>{f}</span></div>
              ))}
            </div>
          </div>

          {/* Pricing */}
          <div className="card text-center">
            {price.discount_pct > 0 && (
              <div className="mb-2">
                <span className="text-sm text-gray-400 line-through">{formatCurrency(price.original_price)}</span>
                <span className="ml-2 text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full font-bold">-{price.discount_pct}%</span>
              </div>
            )}
            <p className="font-display text-4xl font-bold text-brand-600">
              {price.final_price === 0 ? 'GRATIS' : formatCurrency(price.final_price)}
            </p>
            <p className="text-sm text-gray-400 mt-1">sekali bayar, selamanya</p>
          </div>

          {/* Promo code */}
          <div className="card">
            <p className="text-sm font-semibold mb-2">Punya kode promo?</p>
            <div className="flex gap-2">
              <input className="input text-sm flex-1" placeholder="Masukkan kode" value={promo}
                onChange={e => setPromo(e.target.value)} />
              <button onClick={applyPromo} className="px-4 py-2 bg-gray-100 text-sm font-medium rounded-xl hover:bg-gray-200">
                Pakai
              </button>
            </div>
            {promoApplied && price.promo_valid && <p className="text-xs text-green-600 mt-2">✅ Kode valid! Diskon {price.discount_pct}%</p>}
            {promoApplied && !price.promo_valid && <p className="text-xs text-red-500 mt-2">❌ Kode tidak valid atau sudah expired</p>}
          </div>

          <button onClick={createOrder} className="btn-primary w-full justify-center text-center py-3 text-base">
            {price.final_price === 0 ? 'Aktifkan Pro Gratis →' : `Bayar ${formatCurrency(price.final_price)} →`}
          </button>
        </>
      )}

      {step === 2 && order && (
        <>
          <div className="card">
            <h3 className="font-semibold text-sm mb-3">Transfer ke rekening berikut:</h3>
            {banks.length > 0 ? (
              <div className="space-y-3">
                {banks.map((b, i) => (
                  <div key={i} className="bg-gray-50 rounded-xl p-4">
                    <p className="text-sm font-bold">{b.bank}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="font-mono text-lg font-bold text-brand-600">{b.account_number}</p>
                      <button onClick={() => {navigator.clipboard.writeText(b.account_number); setCopyBank(i); setTimeout(() => setCopyBank(-1), 2000);}}
                        className="px-2 py-1 bg-white border border-gray-200 rounded-lg text-xs text-gray-500 hover:text-brand-600 hover:border-brand-400 transition-all">
                        {copyBank === i ? '✅' : '📋'}
                      </button>
                    </div>
                    <p className="text-xs text-gray-500">a.n. {b.account_name}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400">Belum ada rekening tujuan. Hubungi admin.</p>
            )}
            <div className="mt-4 bg-amber-50 rounded-xl p-4">
              <p className="text-sm font-semibold text-amber-700">Jumlah transfer:</p>
              <p className="font-display text-2xl font-bold text-amber-600">{formatCurrency(order.amount)}</p>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-sm mb-3">Upload bukti transfer:</h3>
            <label className="block w-full border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-brand-400 transition-colors">
              <span className="text-3xl block mb-2">📸</span>
              <span className="text-sm text-gray-500">{uploading ? 'Uploading...' : 'Klik untuk upload screenshot bukti transfer'}</span>
              <input type="file" accept="image/*" className="hidden" onChange={uploadProof} disabled={uploading} />
            </label>
          </div>
        </>
      )}

      {step === 3 && (
        <div className="card text-center py-8">
          <span className="text-5xl block mb-3">🔍</span>
          <h3 className="font-display text-xl font-bold mb-2">Menunggu Verifikasi</h3>
          <p className="text-sm text-gray-500">Bukti transfer kamu sudah diterima. Admin akan memverifikasi dalam 1x24 jam.</p>
          <p className="text-sm text-gray-500 mt-2">Kamu akan mendapat notifikasi saat upgrade berhasil.</p>
        </div>
      )}

      {step === 4 && (
        <div className="card text-center py-8">
          <span className="text-5xl block mb-3">🎉</span>
          <h3 className="font-display text-xl font-bold mb-2">Selamat, kamu Pro!</h3>
          <p className="text-sm text-gray-500">Semua fitur unlimited sudah aktif.</p>
          <a href="/" className="btn-primary mt-4 inline-flex">Ke Dashboard →</a>
        </div>
      )}

      {/* Order history */}
      {orders.length > 0 && step === 1 && (
        <div className="card">
          <h3 className="font-semibold text-sm mb-3">Riwayat pembayaran</h3>
          <div className="space-y-2">
            {orders.map(o => (
              <div key={o.id} className="flex items-center justify-between text-sm border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium">{formatCurrency(o.amount)}</p>
                  <p className="text-xs text-gray-400">{new Date(o.created_at).toLocaleDateString('id-ID')}</p>
                </div>
                <span className="text-xs">{statusLabel(o.status)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
