import type { GuestSummary, GuestDetail, HealthStatus, AppSettings } from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchGuests(): Promise<GuestSummary[]> {
  return fetchJson<GuestSummary[]>('/api/guests');
}

export async function fetchGuest(id: string): Promise<GuestDetail> {
  return fetchJson<GuestDetail>(`/api/guests/${id}`);
}

export async function triggerRefresh(): Promise<{ status: string }> {
  return fetchJson<{ status: string }>('/api/refresh', { method: 'POST' });
}

export async function fetchSettings(): Promise<AppSettings> {
  return fetchJson<AppSettings>('/api/settings');
}

export async function fetchHealth(): Promise<HealthStatus> {
  return fetchJson<HealthStatus>('/health');
}
