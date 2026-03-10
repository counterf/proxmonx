export type UpdateStatus = 'up-to-date' | 'outdated' | 'unknown';
export type GuestType = 'lxc' | 'vm';
export type GuestStatus = 'running' | 'stopped';

export interface GuestSummary {
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
  detection_method: string | null;
  version_detection_method: string | null;
  latest_version_source: string | null;
  disk_used: number | null;
  disk_total: number | null;
  os_type: string | null;
}

export interface VersionCheck {
  timestamp: string;
  installed_version: string | null;
  latest_version: string | null;
  update_status: string;
}

export interface GuestDetail extends GuestSummary {
  ip: string | null;
  detection_method: string | null;
  detector_used: string | null;
  raw_detection_output: Record<string, string | number | boolean | null> | null;
  version_history: VersionCheck[];
  github_repo_queried: string | null;
  github_lookup_status: string | null;  // "success" | "failed" | "no_repo" | null
}

export interface HealthStatus {
  status: string;
  configured?: boolean;
  last_poll: string | null;
  guest_count: number;
  is_polling: boolean;
  seconds_since_last_poll: number | null;
}

export interface AppSettings {
  proxmox_host: string;
  proxmox_token_id: string;
  proxmox_node: string;
  poll_interval_seconds: number;
  discover_vms: boolean;
  verify_ssl: boolean;
  ssh_username: string;
  ssh_enabled: boolean;
  github_token_set: boolean;
  log_level: string;
  proxmon_enabled: boolean;
}

export interface SetupStatus {
  configured: boolean;
  missing_fields: string[];
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
}

export interface AppConfigDefault {
  name: string;
  display_name: string;
  default_port: number;
  accepts_api_key: boolean;
  default_scheme: string;
  github_repo: string | null;
}

export interface ProxmoxHost {
  id: string;
  label: string;
  host: string;
  token_id: string;
  token_secret: string | null;
  node: string;
  verify_ssl: boolean;
  ssh_username: string;
  ssh_password: string | null;
  ssh_key_path: string | null;
  pct_exec_enabled: boolean;
}

export interface FullSettings {
  proxmox_host: string | null;
  proxmox_token_id: string | null;
  proxmox_token_secret: string | null;
  proxmox_node: string | null;
  poll_interval_seconds: number;
  discover_vms: boolean;
  verify_ssl: boolean;
  ssh_enabled: boolean;
  ssh_username: string;
  ssh_key_path: string | null;
  ssh_password: string | null;
  github_token: string | null;
  log_level: string;
  version_detect_method: string;
  app_config?: Record<string, AppConfigEntry>;
  proxmox_hosts: ProxmoxHost[];
  notifications_enabled: boolean;
  ntfy_url: string | null;
  ntfy_token: string | null;
  ntfy_priority: number;
  notify_disk_threshold: number;
  notify_disk_cooldown_minutes: number;
  notify_on_outdated: boolean;
}

export interface SettingsSaveRequest {
  proxmox_host: string;
  proxmox_token_id: string;
  proxmox_token_secret: string | null;
  proxmox_node: string;
  poll_interval_seconds: number;
  discover_vms: boolean;
  verify_ssl: boolean;
  ssh_enabled: boolean;
  ssh_username: string;
  ssh_key_path: string | null;
  ssh_password: string | null;
  github_token: string | null;
  log_level: string;
  version_detect_method: string;
  app_config?: Record<string, AppConfigEntry>;
  proxmox_hosts?: ProxmoxHost[];
  notifications_enabled?: boolean;
  ntfy_url?: string;
  ntfy_token?: string | null;
  ntfy_priority?: number;
  notify_disk_threshold?: number;
  notify_disk_cooldown_minutes?: number;
  notify_on_outdated?: boolean;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  node_info: Record<string, unknown> | null;
}
