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

  async forgotPassword(email) {
    try {
      const res = await fetch(`${API_URL}/auth/forgot-password`, {
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

  async resetPassword(token, newPassword) {
    try {
      const res = await fetch(`${API_URL}/auth/reset-password`, {
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
    // Rebuild the full EnvelopeCreate body from a summary row (PUT replaces all fields).
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
      classification,
    });
  }

  async deleteEnvelope(id) {
    const res = await this.request(`/envelopes/${id}`, { method: 'DELETE' });
    return res.ok;
  }

  async getEnvelopeGroups() {
    try {
      const res = await this.request('/envelopes/groups');
      if (res.ok) return res.json();
    } catch {}
    return [];
  }

  async createEnvelopeGroup(name) {
    const res = await this.request('/envelopes/groups', {
      method: 'POST',
      body: JSON.stringify({ name }),
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
    return { ok: res.ok, data: await res.json() };
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

  async batchCreateTransactions(items) {
    try {
      const res = await this.request('/transactions/batch', {
        method: 'POST',
        body: JSON.stringify({ items }),
      });
      const data = await res.json();
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: [] };
    }
  }

  async deleteTransaction(id) {
    const res = await this.request(`/transactions/${id}`, { method: 'DELETE' });
    return res.ok;
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

  async getAdvisorInsights() {
    try {
      const res = await this.request('/advisor/insights');
      if (res.ok) {
        const data = await res.json();
        return { cards: [], dashboard_cards: [], ...data, _error: false };
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
}

export const api = new ApiClient();
