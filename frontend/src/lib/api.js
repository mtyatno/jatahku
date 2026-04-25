import { saveCache, loadCache } from './localCache';

const API_URL = import.meta.env.PROD
  ? 'https://api.jatahku.com'
  : '/api';

class ApiClient {
  constructor() {
    this.token = localStorage.getItem('jatahku_token');
  }

  setToken(token) {
    this.token = token;
    if (token) {
      localStorage.setItem('jatahku_token', token);
    } else {
      localStorage.removeItem('jatahku_token');
    }
  }

  setRefreshToken(token) {
    if (token) {
      localStorage.setItem('jatahku_refresh', token);
    } else {
      localStorage.removeItem('jatahku_refresh');
    }
  }

  getRefreshToken() {
    return localStorage.getItem('jatahku_refresh');
  }

  async request(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const res = await fetch(`${API_URL}${path}`, { ...options, headers });

    if (res.status === 401 && this.getRefreshToken()) {
      const refreshed = await this.refresh();
      if (refreshed) {
        headers['Authorization'] = `Bearer ${this.token}`;
        return fetch(`${API_URL}${path}`, { ...options, headers });
      }
    }

    return res;
  }

  async refresh() {
    try {
      const res = await fetch(`${API_URL}/auth/refresh`, {
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
    this.logout();
    return false;
  }

  logout() {
    this.setToken(null);
    this.setRefreshToken(null);
    window.location.href = '/login';
  }

  // Auth
  async register(email, password, name, promoCode) {
    try {
      const res = await fetch(`${API_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name, promo_code: promoCode || undefined }),
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
      const res = await fetch(`${API_URL}/auth/login`, {
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

  async loginWithTgToken(token) {
    const res = await fetch(`${API_URL}/auth/tg-login?token=${encodeURIComponent(token)}`);
    const data = await res.json();
    if (res.ok) {
      this.setToken(data.access_token);
      this.setRefreshToken(data.refresh_token);
    }
    return { ok: res.ok, data };
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

  async deleteEnvelope(id) {
    const res = await this.request(`/envelopes/${id}`, { method: 'DELETE' });
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

  async getWeeklyPattern(periods = 3) {
    const res = await this.request(`/analytics/weekly-pattern?periods=${periods}`);
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
    return { ok: res.ok, data: await res.json() };
  }

  async deleteTransaction(id) {
    const res = await this.request(`/transactions/${id}`, { method: 'DELETE' });
    return res.ok;
  }

  // Incomes
  async getIncomes() {
    const res = await this.request('/incomes/');
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

  async getWhatsAppStatus() {
    const res = await this.request('/auth/link/whatsapp-status');
    return res.ok ? res.json() : { linked: false, whatsapp_id: null, phone: null };
  }

  async linkWhatsApp(code) {
    return this.request('/auth/link/whatsapp', {
      method: 'POST',
      body: JSON.stringify({ code }),
    });
  }

  async unlinkWhatsApp() {
    return this.request('/auth/link/unlink-whatsapp', { method: 'POST' });
  }

  async saveWhatsAppPhone(phone) {
    return this.request('/auth/link/whatsapp-phone', {
      method: 'PUT',
      body: JSON.stringify({ phone }),
    });
  }
}

export const api = new ApiClient();
