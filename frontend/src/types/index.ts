export type UpdateStatus = 'up-to-date' | 'outdated' | 'unknown';

export const SUPPORTED_OS_TYPES = ['alpine','debian','ubuntu','devuan','fedora','centos','archlinux','opensuse'] as const;
export type GuestType = 'lxc' | 'vm';
export type GuestStatus = 'running' | 'stopped';

export interface VersionCheck {
  timestamp: string;
  installed_version: string | null;
  latest_version: string | null;
  update_status: UpdateStatus;
}

export interface Guest {
  id: string;
  name: string;
  type: GuestType;
  status: GuestStatus;
  app_name: string | null;
  installed_version: string | null;
  latest_version: string | null;
  update_status: UpdateStatus;
  last_checked: string | null;
  tags: string[];
  web_url: string | null;
  host_id: string;
  host_label: string;
  ip: string | null;
  detection_method: string | null;
  detector_used: string | null;
  raw_detection_output: Record<string, string | number | boolean | null> | null;
  version_history: VersionCheck[];
  version_detection_method: string | null;
  github_repo_queried: string | null;
  github_lookup_status: string | null;
  latest_version_source: string | null;
  disk_used: number | null;
  disk_total: number | null;
  os_type: string | null;
  probe_url: string | null;
  probe_error: string | null;
  pending_updates?: number | null;
  pending_update_packages?: string[] | null;
  reboot_required?: boolean | null;
  has_community_script?: boolean | null;
  pending_updates_checked_at?: string | null;
}

export interface TaskRecord {
  id: string;
  guest_id: string;
  guest_name: string;
  host_id: string;
  action: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped';
  started_at: string;
  finished_at: string | null;
  output: string | null;
  detail: string | null;
  batch_id?: string | null;
}

export interface BulkJobResult {
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped';
  task_id: string | null;
  guest_name: string;
  error: string | null;
}

export interface BulkJob {
  id: string;
  action: 'os_update' | 'app_update';
  status: 'pending' | 'running' | 'completed' | 'failed';
  guest_ids: string[];
  results: Record<string, BulkJobResult>;
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface HealthStatus {
  status: string;
  configured?: boolean;
  last_poll: string | null;
  guest_count: number;
  is_polling: boolean;
  seconds_since_last_poll: number | null;
}

export interface SetupStatus {
  configured: boolean;
}

export interface AppConfigEntry {
  port?: number | null;
  api_key?: string | null;
  scheme?: string | null;
  github_repo?: string | null;
  ssh_version_cmd?: string | null;
  ssh_username?: string | null;
  ssh_key_path?: string | null;
  ssh_password?: string | null;
  version_host?: string | null;
}

export interface AppConfigDefault {
  name: string;
  display_name: string;
  default_port: number;
  accepts_api_key: boolean;
  github_repo: string | null;
}

export interface ProxmoxHost {
  id: string;
  label: string;
  host: string;
  token_id: string;
  token_secret: string | null;
  node: string;
  ssh_username: string;
  ssh_password: string | null;
  ssh_key_path: string | null;
  pct_exec_enabled: boolean;
  backup_storage: string | null;
}

export interface FullSettings {
  poll_interval_seconds: number;
  pending_updates_interval_seconds: number;
  discover_vms: boolean;
  ssh_enabled: boolean;
  ssh_username: string;
  ssh_key_path: string | null;
  ssh_password: string | null;
  github_token: string | null;
  log_level: string;
  version_detect_method: string;
  app_config?: Record<string, AppConfigEntry>;
  proxmox_hosts: ProxmoxHost[];
  auth_mode: 'disabled' | 'forms';
  auth_username: string;
  auth_password_set: boolean;
  notifications_enabled: boolean;
  ntfy_url: string | null;
  ntfy_token: string | null;
  ntfy_priority: number;
  notify_disk_threshold: number;
  notify_disk_cooldown_minutes: number;
  notify_on_outdated: boolean;
  proxmon_api_key: string | null;
  trust_proxy_headers: boolean;
}

export interface SettingsSaveRequest {
  poll_interval_seconds: number;
  pending_updates_interval_seconds?: number;
  discover_vms: boolean;
  ssh_enabled: boolean;
  ssh_username: string;
  ssh_key_path: string | null;
  ssh_password: string | null;
  github_token: string | null;
  log_level: string;
  version_detect_method: string;
  app_config?: Record<string, AppConfigEntry>;
  proxmox_hosts?: ProxmoxHost[];
  auth_mode?: 'disabled' | 'forms';
  auth_username?: string;
  /** Set initial password when enabling auth (no current password required) */
  new_password?: string;
  notifications_enabled?: boolean;
  ntfy_url?: string;
  ntfy_token?: string | null;
  ntfy_priority?: number;
  notify_disk_threshold?: number;
  notify_disk_cooldown_minutes?: number;
  notify_on_outdated?: boolean;
  proxmon_api_key?: string | null;
  trust_proxy_headers?: boolean;
}

export interface ConnectionTestRequest {
  host: string;
  token_id: string;
  token_secret: string;
  node: string;
  host_id?: string;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  node_info: Record<string, unknown> | null;
}

export interface AuthStatus {
  auth_mode: 'disabled' | 'forms';
  authenticated: boolean;
  username: string | null;
}

export interface GitHubTestResult {
  ok: boolean;
  repo: string;
  version: string | null;
  source: string | null;
  reason: string | null;
}

export interface CustomAppDef {
  name: string;
  display_name: string;
  default_port: number;
  scheme: string;
  version_path: string | null;
  github_repo: string | null;
  aliases: string[];
  docker_images: string[];
  accepts_api_key: boolean;
  auth_header: string | null;
  version_keys: string[];
  strip_v: boolean;
}
