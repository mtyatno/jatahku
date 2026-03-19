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
  async register(email, password, name) {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name }),
    });
    const data = await res.json();
    if (res.ok) {
      this.setToken(data.access_token);
      this.setRefreshToken(data.refresh_token);
    }
    return { ok: res.ok, data };
  }

  async login(email, password) {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (res.ok) {
      this.setToken(data.access_token);
      this.setRefreshToken(data.refresh_token);
    }
    return { ok: res.ok, data };
  }

  async getMe() {
    const res = await this.request('/auth/me');
    return res.ok ? res.json() : null;
  }

  // Envelopes
  async getEnvelopeSummary() {
    const res = await this.request("/envelopes/summary");
    return res.ok ? res.json() : [];
  }

  async getEnvelopes() {
    const res = await this.request('/envelopes/');
    return res.ok ? res.json() : [];
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

  // Transactions
  async getTransactions(envelopeId = null, limit = 50) {
    const params = new URLSearchParams({ limit });
    if (envelopeId) params.set('envelope_id', envelopeId);
    const res = await this.request(`/transactions/?${params}`);
    return res.ok ? res.json() : [];
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
}

export const api = new ApiClient();
