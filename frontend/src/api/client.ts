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
  AppConfigEntry,
  AuthStatus,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || '';

export class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'HttpError';
  }
}

const DEFAULT_TIMEOUT_MS = 30_000;

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      credentials: 'include',
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new HttpError(response.status, `HTTP ${response.status}: ${response.statusText}`);
    }
    try {
      return await response.json() as T;
    } catch {
      throw new Error('Invalid JSON response from server');
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('Request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
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

export async function fetchGuestConfig(id: string): Promise<AppConfigEntry> {
  return fetchJson<AppConfigEntry>(`/api/guests/${encodeURIComponent(id)}/config`);
}

export async function saveGuestConfig(
  id: string,
  data: AppConfigEntry,
): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(`/api/guests/${encodeURIComponent(id)}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function deleteGuestConfig(
  id: string,
): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(`/api/guests/${encodeURIComponent(id)}/config`, {
    method: 'DELETE',
  });
}

export async function sendTestNotification(): Promise<{ success: boolean; message: string }> {
  return fetchJson<{ success: boolean; message: string }>('/api/notifications/test', {
    method: 'POST',
  });
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  return fetchJson<AuthStatus>('/api/auth/status');
}

export async function login(username: string, password: string): Promise<{ success: boolean }> {
  return fetchJson<{ success: boolean }>('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await fetchJson<{ success: boolean }>('/api/auth/logout', {
    method: 'POST',
  });
}

export async function changePassword(newPassword: string): Promise<{ success: boolean }> {
  return fetchJson<{ success: boolean }>('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }),
  });
}
