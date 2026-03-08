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
