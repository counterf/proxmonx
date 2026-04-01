import type {
  GuestSummary,
  GuestDetail,
  HealthStatus,
  SetupStatus,
  FullSettings,
  SettingsSaveRequest,
  ConnectionTestResult,
  AppConfigDefault,
  AppConfigEntry,
  AuthStatus,
  CustomAppDef,
  GitHubTestResult,
  TaskRecord,
  BulkJob,
} from '../types';
import { API_PATHS } from './paths';

const BASE_URL = import.meta.env.VITE_API_URL || '';
export const AUTH_UNAUTHORIZED_EVENT = 'proxmon:unauthorized';

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
      if (
        response.status === 401
        && path !== API_PATHS.AUTH_LOGIN
        && path !== API_PATHS.AUTH_STATUS
      ) {
        window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
      }
      let detail = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const body = await response.json() as Record<string, unknown>;
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // non-JSON body — keep status text
      }
      throw new HttpError(response.status, detail);
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
  return fetchJson<GuestSummary[]>(API_PATHS.GUESTS);
}

export async function fetchGuest(id: string): Promise<GuestDetail> {
  return fetchJson<GuestDetail>(API_PATHS.GUEST(id));
}

export async function triggerRefresh(): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(API_PATHS.REFRESH, { method: 'POST' });
}

export async function fetchHealth(): Promise<HealthStatus> {
  return fetchJson<HealthStatus>(API_PATHS.HEALTH);
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  return fetchJson<SetupStatus>(API_PATHS.SETUP_STATUS);
}

export async function fetchFullSettings(): Promise<FullSettings> {
  return fetchJson<FullSettings>(API_PATHS.SETTINGS_FULL);
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
  return fetchJson<ConnectionTestResult>(API_PATHS.SETTINGS_TEST_CONNECTION, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function saveSettings(
  data: SettingsSaveRequest,
): Promise<{ success: boolean; message: string }> {
  return fetchJson<{ success: boolean; message: string }>(API_PATHS.SETTINGS, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function fetchAppConfigDefaults(): Promise<AppConfigDefault[]> {
  return fetchJson<AppConfigDefault[]>(API_PATHS.APP_CONFIG_DEFAULTS);
}

export async function fetchGuestConfig(id: string): Promise<AppConfigEntry> {
  return fetchJson<AppConfigEntry>(API_PATHS.GUEST_CONFIG(id));
}

export async function saveGuestConfig(
  id: string,
  data: AppConfigEntry,
): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(API_PATHS.GUEST_CONFIG(id), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function refreshGuest(guestId: string): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(API_PATHS.GUEST_REFRESH(guestId), { method: 'POST' });
}

export async function fetchTask(taskId: string): Promise<TaskRecord> {
  return fetchJson<TaskRecord>(API_PATHS.TASK(taskId));
}

export async function osUpdateGuest(
  guestId: string,
  batchId?: string,
): Promise<{ task_id: string; status: string }> {
  const qs = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : '';
  return fetchJson(API_PATHS.GUEST_OS_UPDATE(guestId) + qs, { method: 'POST' });
}

export async function appUpdateGuest(
  guestId: string,
  batchId?: string,
): Promise<{ task_id: string; status: string }> {
  const qs = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : '';
  return fetchJson(API_PATHS.GUEST_APP_UPDATE(guestId) + qs, { method: 'POST' });
}

export async function guestAction(
  guestId: string,
  action: 'start' | 'stop' | 'shutdown' | 'restart' | 'snapshot',
  snapshotName?: string,
): Promise<{ status: string; task: string }> {
  return fetchJson(API_PATHS.GUEST_ACTION(guestId), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, snapshot_name: snapshotName ?? null }),
  });
}

export async function deleteGuestConfig(
  id: string,
): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(API_PATHS.GUEST_CONFIG(id), {
    method: 'DELETE',
  });
}

export async function sendTestNotification(): Promise<{ success: boolean; message: string }> {
  return fetchJson<{ success: boolean; message: string }>(API_PATHS.NOTIFICATIONS_TEST, {
    method: 'POST',
  });
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  return fetchJson<AuthStatus>(API_PATHS.AUTH_STATUS);
}

export async function login(username: string, password: string): Promise<{ success: boolean }> {
  return fetchJson<{ success: boolean }>(API_PATHS.AUTH_LOGIN, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await fetchJson<{ success: boolean }>(API_PATHS.AUTH_LOGOUT, {
    method: 'POST',
  });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<{ success: boolean }> {
  return fetchJson<{ success: boolean }>(API_PATHS.AUTH_CHANGE_PASSWORD, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
}

export async function testGithubRepo(repo: string): Promise<GitHubTestResult> {
  return fetchJson<GitHubTestResult>(API_PATHS.GITHUB_TEST, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo }),
  });
}

export async function fetchCustomApps(): Promise<CustomAppDef[]> {
  return fetchJson<CustomAppDef[]>(API_PATHS.CUSTOM_APPS);
}

export async function createCustomApp(data: CustomAppDef): Promise<CustomAppDef> {
  return fetchJson<CustomAppDef>(API_PATHS.CUSTOM_APPS, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function updateCustomApp(name: string, data: CustomAppDef): Promise<CustomAppDef> {
  return fetchJson<CustomAppDef>(API_PATHS.CUSTOM_APP(name), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function deleteCustomApp(name: string): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(API_PATHS.CUSTOM_APP(name), {
    method: 'DELETE',
  });
}

export interface BackupStorage {
  storage: string;
  type: string;
  avail?: number | null;
}

export async function fetchBackupStorages(hostId: string): Promise<BackupStorage[] | { error: string }> {
  return fetchJson(API_PATHS.HOST_BACKUP_STORAGES(hostId));
}

export async function backupGuest(guestId: string): Promise<{ status: string; task: string }> {
  return fetchJson(API_PATHS.GUEST_BACKUP(guestId), { method: 'POST' });
}

export async function fetchTasks(): Promise<TaskRecord[]> {
  return fetchJson<TaskRecord[]>(API_PATHS.TASKS);
}

export async function clearTasks(): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(API_PATHS.TASKS, { method: 'DELETE' });
}

export async function startBulkJob(
  action: 'os_update' | 'app_update',
  guestIds: string[],
): Promise<{ job_id: string; status: string }> {
  return fetchJson(API_PATHS.BULK_JOBS, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, guest_ids: guestIds }),
  });
}

export async function fetchBulkJob(jobId: string): Promise<BulkJob> {
  return fetchJson<BulkJob>(API_PATHS.BULK_JOB(jobId));
}
