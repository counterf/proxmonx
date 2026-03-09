import type {
  GuestSummary,
  GuestDetail,
  HealthStatus,
  AppSettings,
  SetupStatus,
  FullSettings,
  SettingsSaveRequest,
  ConnectionTestResult,
  AppConfigDefault,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

export class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'HttpError';
  }
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new HttpError(response.status, `HTTP ${response.status}: ${response.statusText}`);
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

export async function fetchSetupStatus(): Promise<SetupStatus> {
  return fetchJson<SetupStatus>('/api/setup/status');
}

export async function fetchFullSettings(): Promise<FullSettings> {
  return fetchJson<FullSettings>('/api/settings/full');
}

export async function testConnection(
  data: {
    proxmox_host: string;
    proxmox_token_id: string;
    proxmox_token_secret: string;
    proxmox_node: string;
    verify_ssl: boolean;
  },
): Promise<ConnectionTestResult> {
  return fetchJson<ConnectionTestResult>('/api/settings/test-connection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function saveSettings(
  data: SettingsSaveRequest,
): Promise<{ success: boolean; message: string }> {
  return fetchJson<{ success: boolean; message: string }>('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function fetchAppConfigDefaults(): Promise<AppConfigDefault[]> {
  return fetchJson<AppConfigDefault[]>('/api/app-config/defaults');
}
