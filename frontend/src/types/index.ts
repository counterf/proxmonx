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
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  node_info: Record<string, unknown> | null;
}
