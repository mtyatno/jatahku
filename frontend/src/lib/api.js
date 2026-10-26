import { saveCache, loadCache } from './localCache';
import { clearAllHistory } from './chatHistory';
import { revokeSession } from './authLogout';
import { withClientHeader } from './clientInfo';
import { xhrUpload, sendWithRefresh } from './xhrUpload';
import { native } from '../native';

// Alamat API dan tempat token ditentukan lapisan native (ADR-M6), bukan ditebak.
const API_URL = native.platform.apiUrl;

// Semua panggilan ke API membawa X-Jatahku-Client (ADR-M9).
const apiFetch = (url, options = {}) => fetch(url, { ...options, headers: withClientHeader(options.headers) });

class ApiClient {
  get token() {
    return native.tokens.getAccess();
  }

  setToken(token) {
    native.tokens.setAccess(token);
  }

  setRefreshToken(token) {
    native.tokens.setRefresh(token);
  }

  getRefreshToken() {
    return native.tokens.getRefresh();
  }

  async request(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const headers = isFormData
      ? { ...options.headers }
      : { 'Content-Type': 'application/json', ...options.headers };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const res = await apiFetch(`${API_URL}${path}`, { ...options, headers });

    if (res.status === 401 && this.getRefreshToken()) {
      const refreshed = await this.refresh();
      if (refreshed) {
        headers['Authorization'] = `Bearer ${this.token}`;
        return apiFetch(`${API_URL}${path}`, { ...options, headers });
      }
    }

    return res;
  }

  // Unggah FormData lewat XHR supaya progres unggah terlapor (fetch tidak bisa).
  // Token + header klien dirakit ulang di setiap kirim: setelah refresh, kirim ulang memakai token baru.
  async uploadForm(path, formData, { onProgress, onUploaded, timeoutMs } = {}) {
    const send = () => {
      const headers = withClientHeader(this.token ? { Authorization: `Bearer ${this.token}` } : {});
      return xhrUpload({ url: `${API_URL}${path}`, body: formData, headers, timeoutMs, onProgress, onUploaded });
    };
    const { status, data, timedOut } = await sendWithRefresh(send, {
      hasRefreshToken: () => !!this.getRefreshToken(),
      refresh: () => this.refresh(),
    });
    return { ok: status >= 200 && status < 300, status, data, timedOut };
  }

  async refresh() {
    try {
      const res = await apiFetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: this.getRefreshToken() }),
      });
      if (res.ok) {
        const data = await res.json();
        this.setToken(data.access_token);
        this.setRefreshToken(data.refresh_token);
        return true;
      }
    } catch {}
    this.logout({ revoke: false }); // refresh ditolak: sesinya sudah mati di server
    return false;
  }

  logout({ revoke = true } = {}) {
    if (revoke) revokeSession(API_URL, this.getRefreshToken(), apiFetch);
    this.setToken(null);
    this.setRefreshToken(null);
    clearAllHistory(); // riwayat chat bot berisi saldo & transaksi — jangan tertinggal
    window.location.href = '/login';
  }

  // Auth
  async register(email, password, name) {
    try {
      const res = await apiFetch(`${API_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        this.setToken(data.access_token);
        this.setRefreshToken(data.refresh_token);
      }
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Terjadi kesalahan jaringan' } };
    }
  }

  async login(email, password) {
    try {
      const res = await apiFetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        this.setToken(data.access_token);
        this.setRefreshToken(data.refresh_token);
      }
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Terjadi kesalahan jaringan' } };
    }
  }

  async forgotPassword(email) {
    try {
      const res = await apiFetch(`${API_URL}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Terjadi kesalahan jaringan' } };
    }
  }

  // Halaman /hapus-akun (tanpa login): minta link konfirmasi, lalu konfirmasi dengan token.
  async requestAccountDeletion(email) {
    return this._publicPost('/user/account/deletion-request', { email });
  }

  async confirmAccountDeletion(token) {
    return this._publicPost('/user/account/deletion-confirm', { token });
  }

  async _publicPost(path, body) {
    try {
      const res = await apiFetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Terjadi kesalahan jaringan' } };
    }
  }

  async resetPassword(token, newPassword) {
    try {
      const res = await apiFetch(`${API_URL}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        this.setToken(data.access_token);
        this.setRefreshToken(data.refresh_token);
      }
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Terjadi kesalahan jaringan' } };
    }
  }

  async getMe() {
    try {
      const res = await this.request('/auth/me');
      if (res.ok) {
        const data = await res.json();
        saveCache('me', data);
        return data;
      }
    } catch {}
    return loadCache('me');
  }

  async getGoogleClientId() {
    try {
      const res = await apiFetch(`${API_URL}/auth/google/config`);
      if (res.ok) return (await res.json()).client_id || null;
    } catch {}
    return null;
  }

  async loginWithGoogle(credential) {
    try {
      const res = await apiFetch(`${API_URL}/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        this.setToken(data.access_token);
        this.setRefreshToken(data.refresh_token);
      }
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Terjadi kesalahan jaringan' } };
    }
  }

  async loginWithTgToken(token) {
    const res = await apiFetch(`${API_URL}/auth/tg-login?token=${encodeURIComponent(token)}`);
    const data = await res.json();
    if (res.ok) {
      this.setToken(data.access_token);
      this.setRefreshToken(data.refresh_token);
    }
    return { ok: res.ok, data };
  }

  // Config klien (paket mobile 1.3). null = gagal; lihat lib/appConfig.js.
  async getAppConfig() {
    try {
      const res = await apiFetch(`${API_URL}/app/config`);
      if (res.ok) return await res.json();
    } catch {}
    return null;
  }

  // Laporan error klien; tidak pernah melempar.
  async reportClientError(report) {
    try {
      await apiFetch(`${API_URL}/app/errors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(report),
        keepalive: true,
      });
    } catch {}
  }

  // Envelopes
  async getEnvelopeSummary(periodStart = null, periodEnd = null) {
    const params = new URLSearchParams();
    if (periodStart) params.set('period_start', periodStart);
    if (periodEnd) params.set('period_end', periodEnd);
    const qs = params.toString() ? `?${params}` : '';
    const cacheKey = `envelope_summary${periodStart ? `_${periodStart}` : ''}`;
    try {
      const res = await this.request(`/envelopes/summary${qs}`);
      if (res.ok) {
        const data = await res.json();
        if (!periodStart) saveCache(cacheKey, data); // only cache current period
        return data;
      }
    } catch {}
    return loadCache(cacheKey) ?? [];
  }

  async getHouseholdMembers() {
    try {
      const res = await this.request('/household/members');
      if (res.ok) return res.json();
    } catch {}
    return [];
  }

  async getEnvelopes() {
    try {
      const res = await this.request('/envelopes/');
      if (res.ok) {
        const data = await res.json();
        saveCache('envelopes', data);
        return data;
      }
    } catch {}
    return loadCache('envelopes') ?? [];
  }

  async createEnvelope(data) {
    const res = await this.request('/envelopes/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async updateEnvelope(id, data) {
    const res = await this.request(`/envelopes/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async updateEnvelopeClassification(env, classification) {
    return this.updateEnvelopeFields(env, { classification });
  }

  // Ubah sebagian field amplop: PUT butuh body EnvelopeCreate penuh, jadi dibangun dari baris summary.
  async updateEnvelopeFields(env, fields) {
    return this.updateEnvelope(env.id, {
      name: env.name,
      emoji: env.emoji,
      budget_amount: Number(env.budget_amount),
      is_rollover: env.is_rollover,
      group_id: env.group_id ?? null,
      is_personal: env.is_personal,
      is_locked: env.is_locked,
      daily_limit: env.daily_limit ?? null,
      cooling_threshold: env.cooling_threshold ?? null,
      purpose: env.purpose,
      classification: env.classification,
      ...fields,
    });
  }

  async deleteEnvelope(id) {
    try {
      const res = await this.request(`/envelopes/${id}`, { method: 'DELETE' });
      return { ok: res.ok, data: res.ok ? {} : await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }

  async transferEnvelope(fromId, toId, amount) {
    try {
      const res = await this.request(
        `/envelopes/transfer?from_id=${fromId}&to_id=${toId}&amount=${amount}`,
        { method: 'POST' }
      );
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }

  async getEnvelopeGroups() {
    try {
      const res = await this.request('/envelopes/groups');
      if (res.ok) return res.json();
    } catch {}
    return [];
  }

  async createEnvelopeGroup(name, jenis = null) {
    const res = await this.request('/envelopes/groups', {
      method: 'POST',
      body: JSON.stringify(jenis ? { name, jenis } : { name }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async renameEnvelopeGroup(id, name) {
    const res = await this.request(`/envelopes/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  // Jenis grup untuk jatah harian AI Advisor (Fase 5): 'harian' | 'bulanan' | null (otomatis).
  async setEnvelopeGroupJenis(id, jenis) {
    const res = await this.request(`/envelopes/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ jenis: jenis || null }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async deleteEnvelopeGroup(id) {
    const res = await this.request(`/envelopes/groups/${id}`, { method: 'DELETE' });
    return res.ok;
  }

  // Analytics
  async getPeriods(count = 12) {
    const res = await this.request(`/analytics/periods?count=${count}`);
    return res.ok ? res.json() : [];
  }

  async getDailySpending(periodStart = null, periodEnd = null) {
    const params = new URLSearchParams();
    if (periodStart) params.set('period_start', periodStart);
    if (periodEnd) params.set('period_end', periodEnd);
    const qs = params.toString() ? `?${params}` : '';
    const res = await this.request(`/analytics/daily-spending${qs}`);
    return res.ok ? res.json() : [];
  }

  async getEnvelopeBreakdown(periodStart = null, periodEnd = null) {
    const params = new URLSearchParams();
    if (periodStart) params.set('period_start', periodStart);
    if (periodEnd) params.set('period_end', periodEnd);
    const qs = params.toString() ? `?${params}` : '';
    const res = await this.request(`/analytics/envelope-breakdown${qs}`);
    return res.ok ? res.json() : [];
  }

  async getAllocationSummary(periodStart = null, periodEnd = null) {
    const params = new URLSearchParams();
    if (periodStart) params.set('period_start', periodStart);
    if (periodEnd) params.set('period_end', periodEnd);
    const qs = params.toString() ? `?${params}` : '';
    const res = await this.request(`/analytics/allocation-summary${qs}`);
    return res.ok ? res.json() : null;
  }

  // Transactions
  async getTransactions(envelopeId = null, limit = 50, startDate = null, endDate = null) {
    const params = new URLSearchParams({ limit });
    if (envelopeId) params.set('envelope_id', envelopeId);
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    const cacheKey = `transactions_${envelopeId || 'all'}_${startDate || 'cur'}`;
    try {
      const res = await this.request(`/transactions/?${params}`);
      if (res.ok) {
        const data = await res.json();
        if (!startDate) saveCache(cacheKey, data); // only cache current period
        return data;
      }
    } catch {}
    return loadCache(cacheKey) ?? [];
  }

  async createTransaction(data) {
    const res = await this.request('/transactions/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
  }

  async suggestEnvelope(description) {
    try {
      const res = await this.request('/transactions/suggest-envelope', {
        method: 'POST',
        body: JSON.stringify({ description }),
      });
      if (res.ok) return res.json();
    } catch {}
    return null;
  }

  async batchSuggestEnvelopes(descriptions) {
    try {
      const res = await this.request('/transactions/suggest-envelopes', {
        method: 'POST',
        body: JSON.stringify({ descriptions }),
      });
      if (res.ok) return res.json();
    } catch {}
    return null;
  }

  // status 0 = tidak sampai/terputus. ok=false dengan status 2xx/0/409/5xx berarti
  // hasilnya belum pasti (sebagian mungkin sudah tercatat).
  async batchCreateTransactions(items) {
    let res;
    try {
      res = await this.request('/transactions/batch', {
        method: 'POST',
        body: JSON.stringify({ items }),
      });
    } catch {
      return { ok: false, status: 0, data: [] };
    }
    const data = await res.json().catch(() => null);
    if (res.ok && Array.isArray(data)) return { ok: true, status: res.status, data };
    return { ok: false, status: res.status, data: data && !Array.isArray(data) ? data : {} };
  }

  async deleteTransaction(id) {
    const res = await this.request(`/transactions/${id}`, { method: 'DELETE' });
    return res.ok;
  }

  async transcribe(audioBlob) {
    try {
      const form = new FormData();
      const ext = (audioBlob.type || '').includes('mp4') ? 'audio.mp4' : 'audio.webm';
      form.append('audio', audioBlob, ext);
      const res = await this.request('/transactions/transcribe', {
        method: 'POST',
        body: form,
      });
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { detail: 'Transkripsi gagal, coba lagi' } };
    }
  }

  // Scan struk: foto (sudah dikompres) → toko/tanggal/total.
  // onProgress(persen) saat mengunggah, onUploaded() begitu foto selesai terkirim (server mulai membaca).
  async scanReceipt(imageBlob, { onProgress, onUploaded } = {}) {
    const koneksiGagal = 'Gagal mengirim foto. Cek koneksi lalu coba lagi.';
    try {
      const form = new FormData();
      form.append('image', imageBlob, 'struk.jpg');
      const res = await this.uploadForm('/transactions/scan-receipt', form, { onProgress, onUploaded });
      if (res.status === 0 && !res.data.detail) res.data = { ...res.data, detail: koneksiGagal };
      return res;
    } catch {
      return { ok: false, status: 0, data: { detail: koneksiGagal }, timedOut: false };
    }
  }

  // Nilai akhir yang disimpan user → bahan belajar scan struk (best-effort).
  async receiptFeedback(scanId, payload) {
    try {
      await this.request(`/transactions/scan-receipt/${scanId}/feedback`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    } catch {}
  }

  // Incomes
  async getIncomes(periodStart = null, periodEnd = null) {
    const params = new URLSearchParams();
    if (periodStart) params.set('period_start', periodStart);
    if (periodEnd) params.set('period_end', periodEnd);
    const qs = params.toString() ? `?${params}` : '';
    const res = await this.request(`/incomes/${qs}`);
    return res.ok ? res.json() : [];
  }

  async createIncome(data) {
    const res = await this.request('/incomes/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async allocateIncome(incomeId, allocations) {
    const res = await this.request(`/incomes/${incomeId}/allocate`, {
      method: 'POST',
      body: JSON.stringify({ allocations }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async getAdvisorInsights() {
    try {
      const res = await this.request('/advisor/insights');
      if (res.ok) {
        const data = await res.json();
        return { cards: [], dashboard_cards: [], notes: [], ...data, _error: false };
      }
      console.error('[advisor] insights request failed:', res.status);
    } catch (e) {
      console.error('[advisor] insights request error:', e);
    }
    return { cards: [], dashboard_cards: [], _error: true };
  }

  async getSinkingFundAdvice() {
    try {
      const res = await this.request('/advisor/sinking-funds');
      if (res.ok) return res.json();
    } catch {}
    return {
      summary: {
        monthly_reserve_needed: 0,
        new_reserve_needed: 0,
        recommendation_count: 0,
        high_confidence_count: 0,
      },
      recommendations: [],
    };
  }

  async getAllocationRecommendation(incomeAmount) {
    const res = await this.request('/advisor/allocation-recommendation', {
      method: 'POST',
      body: JSON.stringify({ income_amount: Number(incomeAmount) }),
    });
    return { ok: res.ok, data: await res.json() };
  }

  // Halaman Alokasi (S14): banner INC-04/INC-03 + amplop penerima sisa income.
  async getAlokasiPage() {
    try {
      const res = await this.request('/advisor/page/alokasi');
      if (res.ok) return await res.json();
    } catch {}
    return { enabled: false, banner: [], sisa_ke: null };
  }

  // AI Advisor v2 — pipa CTA (S8). Kontrak: docs/ai-advisor/04-kontrak-api.md.
  // GET /advisor/dashboard (S3). {"enabled": false} → user di luar flag; null bila gagal.
  // Keduanya membuat Beranda memakai UI lama.
  async getAdvisorDashboard() {
    try {
      const res = await this.request('/advisor/dashboard');
      if (res.ok) return await res.json();
      console.error('[advisor] dashboard request failed:', res.status);
    } catch (e) {
      console.error('[advisor] dashboard request error:', e);
    }
    return null;
  }

  // GET /advisor/page/amplop (S11): strip AI per kartu amplop. {"enabled": false} atau null →
  // halaman Amplop memakai strip lama (envelopeInsight).
  async getAdvisorAmplop() {
    try {
      const res = await this.request('/advisor/page/amplop');
      if (res.ok) return await res.json();
      console.error('[advisor] amplop request failed:', res.status);
    } catch (e) {
      console.error('[advisor] amplop request error:', e);
    }
    return null;
  }

  // GET /advisor/page/transaksi (S13): banner sesuai filter + penanda baris. null bila gagal.
  async getAdvisorTransaksi({ tanggal = null, amplop = null } = {}) {
    const q = new URLSearchParams();
    if (tanggal) q.set('tanggal', tanggal);
    if (amplop) q.set('amplop', amplop);
    const qs = q.toString();
    try {
      const res = await this.request(`/advisor/page/transaksi${qs ? `?${qs}` : ''}`);
      if (res.ok) return await res.json();
      console.error('[advisor] transaksi request failed:', res.status);
    } catch (e) {
      console.error('[advisor] transaksi request error:', e);
    }
    return null;
  }

  // GET /advisor/page/langganan (S12). Sama: {"enabled": false} atau null → halaman tanpa AI.
  async getAdvisorLangganan() {
    try {
      const res = await this.request('/advisor/page/langganan');
      if (res.ok) return await res.json();
      console.error('[advisor] langganan request failed:', res.status);
    } catch (e) {
      console.error('[advisor] langganan request error:', e);
    }
    return null;
  }

  // GET /advisor/page/analitik (S15). Sama: {"enabled": false} atau null → Analitik tanpa AI v2.
  async getAdvisorAnalitik() {
    try {
      const res = await this.request('/advisor/page/analitik');
      if (res.ok) return await res.json();
      console.error('[advisor] analitik request failed:', res.status);
    } catch (e) {
      console.error('[advisor] analitik request error:', e);
    }
    return null;
  }

  async _advisorPost(path, body) {
    try {
      const res = await this.request(path, { method: 'POST', body: JSON.stringify(body) });
      const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, data };
    } catch {
      return { ok: false, status: 0, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }

  advisorPlan(kebutuhan, kecuali = []) {
    return this._advisorPost('/advisor/plan', kecuali.length ? { kebutuhan, kecuali } : { kebutuhan });
  }

  advisorExecute(body) {
    return this._advisorPost('/advisor/execute', body);
  }

  advisorDismiss(kunci, pilihan = 'nanti') {
    return this._advisorPost('/advisor/dismiss', { kunci, pilihan });
  }

  // Urungkan / Munculkan lagi (#91). 204 juga bila tidak ada yang disembunyikan.
  async advisorUndismiss(kunci) {
    try {
      const res = await this.request(`/advisor/dismiss?kunci=${encodeURIComponent(kunci)}`, { method: 'DELETE' });
      return { ok: res.ok, status: res.status };
    } catch {
      return { ok: false, status: 0 };
    }
  }

  async resetData(email = null) {
    const body = email ? { email } : {};
    return this.request('/user/reset', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async getGoals() {
    try {
      const res = await this.request('/goals/');
      if (res.ok) return res.json();
    } catch {}
    return [];
  }

  async createGoal(data) {
    const res = await this.request('/goals/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async updateGoal(id, data) {
    const res = await this.request(`/goals/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
    return { ok: res.ok, data: await res.json() };
  }

  async deleteGoal(id) {
    const res = await this.request(`/goals/${id}`, { method: 'DELETE' });
    return res.ok;
  }

  // Recurring / Langganan payment
  async getRecurring() {
    try { const res = await this.request('/recurring/'); if (res.ok) return res.json(); } catch {}
    return [];
  }

  async payRecurring(id, amount = null) {
    const res = await this.request(`/recurring/${id}/pay`, {
      method: 'POST', body: JSON.stringify(amount == null ? {} : { amount: Number(amount) }),
    });
    return { ok: res.ok, data: await res.json().catch(() => ({})) };
  }

  async skipRecurring(id) {
    const res = await this.request(`/recurring/${id}/skip`, { method: 'POST' });
    return { ok: res.ok, data: await res.json().catch(() => ({})) };
  }

  // Tandai lunas: majukan next_run tanpa transaksi baru (endpoint dari S4).
  async markRecurringPaid(id) {
    try {
      const res = await this.request(`/recurring/${id}/mark-paid`, { method: 'POST' });
      return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, status: 0, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }

  // Undo: kembalikan next_run sebuah langganan ke nilai sebelumnya (PUT butuh body penuh)
  async restoreRecurringNextRun(item, prevNextRun) {
    return this.request(`/recurring/${item.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        envelope_id: item.envelope_id, amount: Number(item.amount),
        description: item.description, frequency: item.frequency, next_run: prevNextRun,
      }),
    });
  }

  // Cocokkan saldo
  async getBalanceCheckStatus() {
    try {
      const res = await this.request('/balance-check/status');
      if (res.ok) return res.json();
    } catch {}
    return null;
  }

  async previewBalanceCheck(actualAmount) {
    try {
      const res = await this.request('/balance-check/preview', {
        method: 'POST', body: JSON.stringify({ actual_amount: Number(actualAmount) }),
      });
      return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, status: 0, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }

  async applyBalanceCheck(payload) {
    try {
      const res = await this.request('/balance-check/apply', {
        method: 'POST', body: JSON.stringify(payload),
      });
      return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, status: 0, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }

  // Chat bot di webapp — handler bot Telegram yang sama (app/bot/web_adapter.py).
  // clientId = id pesan di riwayat lokal: kirim ulang dengan id sama tidak dicatat dua kali.
  async chatSend(text, clientId) {
    return this._chat('/bot/chat/message', { text, client_id: clientId });
  }

  async chatAction(messageId, data) {
    return this._chat('/bot/chat/action', { message_id: messageId, data });
  }

  // Pesan proaktif AI Advisor saat panel chat dibuka (S16): maks sekali per hari, server yang membatasi.
  async chatProaktif() {
    return this._chat('/bot/chat/proaktif', {});
  }

  // Foto struk dari chat → alur scan struk bot (kuota sama dengan tombol Struk).
  async chatPhoto(blob, clientId, { onProgress, onUploaded } = {}) {
    const koneksiGagal = 'Gagal mengirim foto. Cek koneksi lalu coba lagi.';
    try {
      const form = new FormData();
      form.append('image', blob, 'struk.jpg');
      if (clientId) form.append('client_id', clientId);
      const res = await this.uploadForm('/bot/chat/photo', form, { onProgress, onUploaded });
      const d = res.data;
      if (res.ok) return { ok: true, ops: Array.isArray(d.ops) ? d.ops : [] };
      if (res.timedOut) return { ok: false, error: 'Koneksi lambat, foto belum terkirim. Coba lagi.' };
      if (res.status === 0) return { ok: false, error: koneksiGagal };
      if (res.status === 429) return { ok: false, error: 'Terlalu banyak scan. Tunggu sebentar, ya.' };
      return { ok: false, error: (typeof d.detail === 'string' && d.detail) || 'Foto tidak bisa dikirim. Coba lagi.' };
    } catch {
      return { ok: false, error: koneksiGagal };
    }
  }

  async _chat(path, body) {
    try {
      const res = await this.request(path, { method: 'POST', body: JSON.stringify(body) });
      if (res.ok) {
        const d = await res.json().catch(() => ({}));
        return { ok: true, ops: Array.isArray(d.ops) ? d.ops : [] };
      }
      if (res.status === 429) return { ok: false, error: 'Terlalu banyak pesan. Tunggu sebentar, ya.' };
      return { ok: false, error: 'Bot sedang tidak bisa dihubungi. Coba lagi.' };
    } catch {
      return { ok: false, error: 'Koneksi gagal. Coba lagi.' };
    }
  }

  async undoBalanceCheck(id) {
    try {
      const res = await this.request(`/balance-check/${id}/undo`, { method: 'POST' });
      return { ok: res.ok, data: await res.json().catch(() => ({})) };
    } catch {
      return { ok: false, data: { detail: 'Koneksi gagal, coba lagi' } };
    }
  }
}

export const api = new ApiClient();
