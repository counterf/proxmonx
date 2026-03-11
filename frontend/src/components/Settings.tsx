import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { FullSettings, SettingsSaveRequest, ConnectionTestResult, AppConfigEntry, ProxmoxHost } from '../types';
import { fetchFullSettings, saveSettings, testConnection, sendTestNotification, changePassword } from '../api/client';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';
import FormField from './setup/FormField';
import PasswordField from './setup/PasswordField';
import Toggle from './setup/Toggle';
import ConnectionTestButton from './setup/ConnectionTestButton';
import SuccessToast from './setup/SuccessToast';
import AppConfigSection from './settings/AppConfigSection';
import ProxmoxHostsSection from './settings/ProxmoxHostsSection';
import SecuritySection from './settings/SecuritySection';

const DETECTORS = [
  { name: 'sonarr', displayName: 'Sonarr' },
  { name: 'radarr', displayName: 'Radarr' },
  { name: 'bazarr', displayName: 'Bazarr' },
  { name: 'prowlarr', displayName: 'Prowlarr' },
  { name: 'plex', displayName: 'Plex' },
  { name: 'immich', displayName: 'Immich' },
  { name: 'overseerr', displayName: 'Overseerr' },
  { name: 'seerr', displayName: 'Seerr' },
  { name: 'gitea', displayName: 'Gitea' },
  { name: 'qbittorrent', displayName: 'qBittorrent' },
  { name: 'sabnzbd', displayName: 'SABnzbd' },
  { name: 'traefik', displayName: 'Traefik' },
  { name: 'caddy', displayName: 'Caddy' },
  { name: 'ntfy', displayName: 'ntfy' },
  { name: 'docker', displayName: 'Docker (generic)' },
];

type AuthMethod = 'key' | 'password';

interface FormData {
  proxmox_host: string;
  proxmox_token_id: string;
  proxmox_token_secret: string;
  proxmox_node: string;
  poll_interval_seconds: number;
  discover_vms: boolean;
  verify_ssl: boolean;
  ssh_enabled: boolean;
  ssh_username: string;
  ssh_key_path: string;
  ssh_password: string;
  github_token: string;
  log_level: string;
  version_detect_method: string;
  auth_mode: 'disabled' | 'forms';
  auth_username: string;
  notifications_enabled: boolean;
  ntfy_url: string;
  ntfy_token: string;
  ntfy_priority: number;
  notify_disk_threshold: number;
  notify_disk_cooldown_minutes: number;
  notify_on_outdated: boolean;
}

interface FormErrors {
  [key: string]: string | undefined;
}

function settingsToFormData(s: FullSettings): FormData {
  return {
    proxmox_host: s.proxmox_host || '',
    proxmox_token_id: s.proxmox_token_id || '',
    proxmox_token_secret: s.proxmox_token_secret || '',
    proxmox_node: s.proxmox_node || '',
    poll_interval_seconds: s.poll_interval_seconds,
    discover_vms: s.discover_vms,
    verify_ssl: s.verify_ssl,
    ssh_enabled: s.ssh_enabled,
    ssh_username: s.ssh_username,
    ssh_key_path: s.ssh_key_path || '',
    ssh_password: (s.ssh_password && s.ssh_password !== '***') ? s.ssh_password : '',
    github_token: (s.github_token && s.github_token !== '***') ? s.github_token : '',
    log_level: s.log_level,
    version_detect_method: s.version_detect_method || 'pct_first',
    auth_mode: s.auth_mode || 'forms',
    auth_username: s.auth_username || 'root',
    notifications_enabled: s.notifications_enabled ?? false,
    ntfy_url: s.ntfy_url || '',
    ntfy_token: (s.ntfy_token && s.ntfy_token !== '***') ? s.ntfy_token : '',
    ntfy_priority: s.ntfy_priority ?? 3,
    notify_disk_threshold: s.notify_disk_threshold ?? 95,
    notify_disk_cooldown_minutes: s.notify_disk_cooldown_minutes ?? 60,
    notify_on_outdated: s.notify_on_outdated ?? true,
  };
}

function initHostsFromSettings(s: FullSettings): ProxmoxHost[] {
  if (s.proxmox_hosts && s.proxmox_hosts.length > 0) {
    return s.proxmox_hosts;
  }
  // Seed from flat fields
  if (s.proxmox_host || s.proxmox_token_id) {
    return [{
      id: 'default',
      label: 'Default',
      host: s.proxmox_host || '',
      token_id: s.proxmox_token_id || '',
      token_secret: s.proxmox_token_secret || '',
      node: s.proxmox_node || '',
      verify_ssl: s.verify_ssl,
      ssh_username: s.ssh_username || 'root',
      ssh_password: s.ssh_password,
      ssh_key_path: s.ssh_key_path,
      pct_exec_enabled: false,
    }];
  }
  return [{
    id: crypto.randomUUID(),
    label: 'Default',
    host: '',
    token_id: '',
    token_secret: '',
    node: '',
    verify_ssl: false,
    ssh_username: 'root',
    ssh_password: null,
    ssh_key_path: null,
    pct_exec_enabled: false,
  }];
}

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [form, setForm] = useState<FormData | null>(null);
  const [savedForm, setSavedForm] = useState<FormData | null>(null);
  const [errors, setErrors] = useState<FormErrors>({});
  const [authMethod, setAuthMethod] = useState<AuthMethod>('key');
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  // Track whether token_secret was changed from the masked value
  const tokenSecretChanged = useRef(false);
  const ntfyTokenChanged = useRef(false);
  const [testingNotification, setTestingNotification] = useState(false);
  const [notificationTestResult, setNotificationTestResult] = useState<string | null>(null);
  // Per-app configuration
  const [appConfigs, setAppConfigs] = useState<Record<string, AppConfigEntry>>({});
  const [savedAppConfigs, setSavedAppConfigs] = useState<Record<string, AppConfigEntry>>({});
  const changedApiKeys = useRef<Set<string>>(new Set());
  // Multi-host
  const [proxmoxHosts, setProxmoxHosts] = useState<ProxmoxHost[]>([]);
  const [savedProxmoxHosts, setSavedProxmoxHosts] = useState<ProxmoxHost[]>([]);
  // Auth password local state
  const [authPasswordSet, setAuthPasswordSet] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  // Whether we use multi-host mode
  const useMultiHost = true;

  useEffect(() => {
    fetchFullSettings()
      .then((s) => {
        const fd = settingsToFormData(s);
        setForm(fd);
        setSavedForm(fd);
        setAuthPasswordSet(s.auth_password_set ?? false);
        // Load app config
        const ac = s.app_config || {};
        setAppConfigs(ac);
        setSavedAppConfigs(ac);
        // Load hosts
        const hosts = initHostsFromSettings(s);
        setProxmoxHosts(hosts);
        setSavedProxmoxHosts(hosts);
        // Detect auth method from loaded data
        if (s.ssh_password && s.ssh_password !== '***') {
          setAuthMethod('password');
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load settings'))
      .finally(() => setLoading(false));
  }, []);

  const setField = useCallback(<K extends keyof FormData>(key: K, value: FormData[K]) => {
    setForm((prev) => prev ? { ...prev, [key]: value } : prev);
    setErrors((prev) => ({ ...prev, [key]: undefined }));
    if (key === 'proxmox_token_secret') {
      tokenSecretChanged.current = true;
    }
    if (key === 'ntfy_token') {
      ntfyTokenChanged.current = true;
    }
  }, []);

  // tokenSecretChanged must be ORed in: typing "***" back after changing it would
  // produce equal JSON strings, hiding a real change from the dirty check.
  const appConfigDirty =
    changedApiKeys.current.size > 0 ||
    JSON.stringify(appConfigs) !== JSON.stringify(savedAppConfigs);
  const hostsDirty = JSON.stringify(proxmoxHosts) !== JSON.stringify(savedProxmoxHosts);
  const passwordDirty = newPassword !== '' || confirmPassword !== '';
  const isDirty =
    tokenSecretChanged.current ||
    ntfyTokenChanged.current ||
    appConfigDirty ||
    hostsDirty ||
    passwordDirty ||
    (form !== null && savedForm !== null && JSON.stringify(form) !== JSON.stringify(savedForm));

  // beforeunload warning
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const validate = (): boolean => {
    if (!form) return false;
    const errs: FormErrors = {};

    if (useMultiHost) {
      // Validate first host at minimum
      if (proxmoxHosts.length === 0) {
        errs.proxmox_hosts = 'At least one host is required';
      } else {
        const first = proxmoxHosts[0];
        if (!first.host) errs.proxmox_host = 'Host URL is required';
        else if (!first.host.startsWith('http://') && !first.host.startsWith('https://'))
          errs.proxmox_host = 'Enter a valid URL starting with http:// or https://';
        if (!first.token_id.trim()) errs.proxmox_token_id = 'Token ID is required';
        if (!first.node.trim()) errs.proxmox_node = 'Node name is required';
      }
    } else {
      if (!form.proxmox_host) errs.proxmox_host = 'Proxmox Host is required';
      else if (!form.proxmox_host.startsWith('http://') && !form.proxmox_host.startsWith('https://'))
        errs.proxmox_host = 'Enter a valid URL starting with http:// or https://';
      if (!form.proxmox_token_id.trim()) errs.proxmox_token_id = 'Token ID is required';
      if (!form.proxmox_node.trim()) errs.proxmox_node = 'Node name is required';
    }

    if (form.poll_interval_seconds < 30 || form.poll_interval_seconds > 3600)
      errs.poll_interval_seconds = 'Must be between 30 and 3600 seconds';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSave = async () => {
    if (!form || !validate()) return;
    // Password validation
    if (newPassword && newPassword !== confirmPassword) {
      setSaveError('Passwords do not match');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      // Change password first if provided
      if (newPassword) {
        await changePassword(newPassword);
        setNewPassword('');
        setConfirmPassword('');
        setAuthPasswordSet(true);
      }
      // Build app_config payload: include all overridden fields
      const appConfigPayload: Record<string, AppConfigEntry> = {};
      for (const [name, cfg] of Object.entries(appConfigs)) {
        const entry: AppConfigEntry = {};
        // Plain fields -- always send current value (null = clear/default)
        entry.port = cfg.port || null;
        entry.scheme = cfg.scheme || null;
        entry.github_repo = cfg.github_repo || null;
        entry.ssh_version_cmd = cfg.ssh_version_cmd || null;
        entry.ssh_username = cfg.ssh_username || null;
        entry.ssh_key_path = cfg.ssh_key_path || null;
        // Secret fields -- only send if explicitly changed; otherwise backend
        // keeps existing value (prevents "***" being written back as the token)
        if (changedApiKeys.current.has(name)) {
          entry.api_key = cfg.api_key ?? '';
          entry.ssh_password = cfg.ssh_password ?? '';
        }
        // Only include this app if at least one field is set
        const hasContent = entry.port || entry.scheme || entry.github_repo ||
          entry.ssh_version_cmd || entry.ssh_username || entry.ssh_key_path ||
          changedApiKeys.current.has(name);
        if (hasContent) {
          appConfigPayload[name] = entry;
        }
      }

      // Build proxmox_hosts payload -- mask secrets that haven't changed
      const hostsPayload: ProxmoxHost[] = proxmoxHosts.map((h) => {
        const saved = savedProxmoxHosts.find((s) => s.id === h.id);
        return {
          ...h,
          // If token_secret is still the masked sentinel, send null to keep backend value
          token_secret: h.token_secret === '***' ? null : (h.token_secret || null),
          ssh_password: h.ssh_password === '***' ? null : (h.ssh_password || null),
          // Preserve ssh_key_path
          ssh_key_path: h.ssh_key_path || saved?.ssh_key_path || null,
        };
      });

      // Use first host for flat fields (backward compat)
      const firstHost = proxmoxHosts[0];

      const payload: SettingsSaveRequest = {
        proxmox_host: firstHost?.host || form.proxmox_host,
        proxmox_token_id: firstHost?.token_id || form.proxmox_token_id,
        proxmox_token_secret: tokenSecretChanged.current ? form.proxmox_token_secret : null,
        proxmox_node: firstHost?.node || form.proxmox_node,
        poll_interval_seconds: form.poll_interval_seconds,
        discover_vms: form.discover_vms,
        verify_ssl: form.verify_ssl,
        ssh_enabled: form.ssh_enabled,
        ssh_username: form.ssh_username,
        ssh_key_path: form.ssh_key_path || null,
        ssh_password: form.ssh_password || null,
        github_token: form.github_token || null,
        log_level: form.log_level,
        version_detect_method: form.version_detect_method,
        auth_mode: form.auth_mode,
        auth_username: form.auth_username,
        app_config: Object.keys(appConfigPayload).length > 0 ? appConfigPayload : undefined,
        proxmox_hosts: hostsPayload,
        notifications_enabled: form.notifications_enabled,
        ntfy_url: form.ntfy_url,
        ntfy_token: ntfyTokenChanged.current ? (form.ntfy_token || null) : null,
        ntfy_priority: form.ntfy_priority,
        notify_disk_threshold: form.notify_disk_threshold,
        notify_disk_cooldown_minutes: form.notify_disk_cooldown_minutes,
        notify_on_outdated: form.notify_on_outdated,
      };
      await saveSettings(payload);
      setSavedForm({ ...form });
      setSavedAppConfigs({ ...appConfigs });
      setSavedProxmoxHosts([...proxmoxHosts]);
      tokenSecretChanged.current = false;
      ntfyTokenChanged.current = false;
      changedApiKeys.current = new Set();
      setToast('Settings saved. Discovery restarting...');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (): Promise<ConnectionTestResult> => {
    if (!form) throw new Error('Form not loaded');
    // If token secret wasn't changed, we can't test with masked value
    const secret = tokenSecretChanged.current ? form.proxmox_token_secret : '';
    if (!secret || secret === '***') {
      return {
        success: false,
        message: 'Please enter the token secret to test the connection',
        node_info: null,
      };
    }
    return testConnection({
      proxmox_host: form.proxmox_host,
      proxmox_token_id: form.proxmox_token_id,
      proxmox_token_secret: secret,
      proxmox_node: form.proxmox_node,
      verify_ssl: form.verify_ssl,
    });
  };

  if (loading) return <LoadingSpinner text="Loading settings..." />;
  if (error) return <ErrorBanner message={error} />;
  if (!form) return null;

  const inputClass = (field: string) =>
    `w-full px-3 py-1.5 text-sm bg-surface border rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
      errors[field] ? 'border-red-500' : 'border-gray-800'
    }`;

  return (
    <div className="space-y-4 pb-20">
      {/* Error banner */}
      {saveError && <ErrorBanner message={`Save failed: ${saveError}`} />}

      {/* Toast */}
      {toast && <SuccessToast message={toast} onDismiss={() => setToast(null)} />}

      {/* Breadcrumb + unsaved indicator */}
      <div className="flex items-center justify-between">
        <nav aria-label="Breadcrumb" className="text-sm text-gray-500">
          <Link to="/" className="hover:text-white">Dashboard</Link>
          <span className="mx-2">&gt;</span>
          <span aria-current="page" className="text-gray-300">Settings</span>
        </nav>
        {isDirty && (
          <span className="text-xs text-amber-400">&#8226; Unsaved changes</span>
        )}
      </div>

      <h1 className="text-xl font-bold text-white">Settings</h1>

      {/* Security */}
      <SecuritySection
        authMode={form.auth_mode}
        authUsername={form.auth_username}
        authPasswordSet={authPasswordSet}
        newPassword={newPassword}
        confirmPassword={confirmPassword}
        onAuthModeChange={(v) => setField('auth_mode', v)}
        onAuthUsernameChange={(v) => setField('auth_username', v)}
        onNewPasswordChange={setNewPassword}
        onConfirmPasswordChange={setConfirmPassword}
        disabled={saving}
      />

      {/* Proxmox Hosts (multi-host) */}
      {useMultiHost ? (
        <ProxmoxHostsSection
          hosts={proxmoxHosts}
          onChange={setProxmoxHosts}
          disabled={saving}
        />
      ) : (
        /* Legacy single-host Proxmox Connection */
        <div className="p-4 rounded bg-surface border border-gray-800">
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Proxmox Connection</h2>
          <div className="space-y-3">
            <FormField label="Proxmox Host" required error={errors.proxmox_host} htmlFor="s_proxmox_host">
              <input
                id="s_proxmox_host"
                type="text"
                value={form.proxmox_host}
                onChange={(e) => setField('proxmox_host', e.target.value)}
                placeholder="https://192.168.1.10:8006"
                aria-required
                className={inputClass('proxmox_host')}
              />
            </FormField>

            <FormField label="API Token ID" required error={errors.proxmox_token_id} htmlFor="s_proxmox_token_id">
              <input
                id="s_proxmox_token_id"
                type="text"
                value={form.proxmox_token_id}
                onChange={(e) => setField('proxmox_token_id', e.target.value)}
                placeholder="root@pam!proxmon"
                aria-required
                className={inputClass('proxmox_token_id')}
              />
            </FormField>

            <PasswordField
              id="s_proxmox_token_secret"
              label="API Token Secret"
              required
              value={form.proxmox_token_secret}
              onChange={(v) => setField('proxmox_token_secret', v)}
              error={errors.proxmox_token_secret}
            />

            <FormField label="Node Name" required error={errors.proxmox_node} htmlFor="s_proxmox_node">
              <input
                id="s_proxmox_node"
                type="text"
                value={form.proxmox_node}
                onChange={(e) => setField('proxmox_node', e.target.value)}
                placeholder="pve"
                aria-required
                className={inputClass('proxmox_node')}
              />
            </FormField>

            <ConnectionTestButton onTest={handleTest} />
          </div>
        </div>
      )}

      {/* Discovery */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Discovery</h2>
        <div className="space-y-3">
          <FormField label="Poll Interval (seconds)" required error={errors.poll_interval_seconds} htmlFor="s_poll_interval" hint="How often proxmon re-scans guests and checks for new versions (30 -- 3600)">
            <input
              id="s_poll_interval"
              type="number"
              min={30}
              max={3600}
              value={form.poll_interval_seconds}
              onChange={(e) => setField('poll_interval_seconds', parseInt(e.target.value) || 300)}
              className={inputClass('poll_interval_seconds')}
            />
          </FormField>

          <Toggle
            id="s_discover_vms"
            label="Include VMs"
            checked={form.discover_vms}
            onChange={(v) => setField('discover_vms', v)}
            hint="Scan QEMU virtual machines in addition to LXC containers"
          />

          <Toggle
            id="s_verify_ssl"
            label="Verify SSL"
            checked={form.verify_ssl}
            onChange={(v) => setField('verify_ssl', v)}
            hint="Validate TLS certificates when connecting to Proxmox and application APIs"
          />

          {!form.verify_ssl && (
            <div className="flex items-start gap-2 p-2 rounded bg-amber-900/30 border border-amber-800 text-amber-400 text-xs">
              <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <span>SSL verification is disabled. Proxmox uses self-signed certificates by default.</span>
            </div>
          )}

          <FormField label="Version Detection Method" htmlFor="s_version_detect_method" hint="CLI fallback strategy when an app's HTTP API probe does not return a version">
            <select
              id="s_version_detect_method"
              value={form.version_detect_method}
              onChange={(e) => setField('version_detect_method', e.target.value)}
              className={inputClass('version_detect_method')}
            >
              <option value="pct_first">pct exec first, fallback to SSH</option>
              <option value="ssh_first">SSH first, fallback to pct exec</option>
              <option value="ssh_only">SSH only</option>
              <option value="pct_only">pct exec only</option>
            </select>
          </FormField>
        </div>
      </div>

      {/* SSH */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">SSH</h2>
        <p className="text-xs text-gray-500 mb-3">
          Global SSH defaults used for direct connections to guests. Per-host and per-app overrides take priority.
        </p>
        <div className="space-y-3">
          <Toggle
            id="s_ssh_enabled"
            label="Enable SSH"
            checked={form.ssh_enabled}
            onChange={(v) => setField('ssh_enabled', v)}
            hint="Allow SSH and pct exec for CLI-based version detection"
          />

          {form.ssh_enabled && (
            <>
              <FormField label="SSH Username" required htmlFor="s_ssh_username" hint="Default username for SSH connections to guest containers">
                <input
                  id="s_ssh_username"
                  type="text"
                  value={form.ssh_username}
                  onChange={(e) => setField('ssh_username', e.target.value)}
                  className={inputClass('ssh_username')}
                />
              </FormField>

              <div>
                <p className="text-xs text-gray-400 mb-1">Authentication</p>
                <p className="text-xs text-gray-600 mb-2">Choose how proxmon authenticates when connecting via SSH</p>
                <div className="flex gap-4">
                  <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                    <input
                      type="radio"
                      name="s_auth_method"
                      checked={authMethod === 'key'}
                      onChange={() => setAuthMethod('key')}
                      className="accent-blue-500"
                    />
                    Key file
                  </label>
                  <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                    <input
                      type="radio"
                      name="s_auth_method"
                      checked={authMethod === 'password'}
                      onChange={() => setAuthMethod('password')}
                      className="accent-blue-500"
                    />
                    Password
                  </label>
                </div>
              </div>

              {authMethod === 'key' && (
                <FormField label="Private Key Path" htmlFor="s_ssh_key_path" hint="Absolute path to the SSH private key inside the proxmon container">
                  <input
                    id="s_ssh_key_path"
                    type="text"
                    value={form.ssh_key_path}
                    onChange={(e) => setField('ssh_key_path', e.target.value)}
                    placeholder="/root/.ssh/id_ed25519"
                    className={inputClass('ssh_key_path')}
                  />
                </FormField>
              )}

              {authMethod === 'password' && (
                <PasswordField
                  id="s_ssh_password"
                  label="SSH Password"
                  value={form.ssh_password}
                  onChange={(v) => setField('ssh_password', v)}
                  hint="Fallback password when no key is configured"
                />
              )}
            </>
          )}
        </div>
      </div>

      {/* GitHub Token */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">GitHub Token</h2>
        <p className="text-xs text-gray-500 mb-3">
          A personal access token increases the GitHub API rate limit from 60 to 5,000 req/hr.
          Leave blank for unauthenticated access.
        </p>
        <PasswordField
          id="s_github_token"
          label="GitHub Token"
          value={form.github_token}
          onChange={(v) => setField('github_token', v)}
          hint="Optional"
        />
      </div>

      {/* Notifications */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Notifications</h2>
        <p className="text-xs text-gray-500 mb-3">
          Push alerts to an ntfy server when disk usage or version thresholds are exceeded.
        </p>
        <div className="space-y-3">
          <Toggle
            id="s_notifications_enabled"
            label="Enable Notifications"
            checked={form.notifications_enabled}
            onChange={(v) => setField('notifications_enabled', v)}
            hint="Activate push notifications after each discovery cycle"
          />

          {form.notifications_enabled && (
            <>
              <FormField label="ntfy URL" required htmlFor="s_ntfy_url" hint="Full URL including the topic name, e.g. https://ntfy.sh/my-proxmon-alerts">
                <input
                  id="s_ntfy_url"
                  type="text"
                  value={form.ntfy_url}
                  onChange={(e) => setField('ntfy_url', e.target.value)}
                  placeholder="https://ntfy.sh/my-proxmon-alerts"
                  className={inputClass('ntfy_url')}
                />
              </FormField>

              <PasswordField
                id="s_ntfy_token"
                label="ntfy Access Token"
                value={form.ntfy_token}
                onChange={(v) => setField('ntfy_token', v)}
                hint="Required only if the ntfy topic uses access control"
              />

              <FormField label="Priority" htmlFor="s_ntfy_priority" hint="Default priority for notifications (disk alerts always use High)">
                <select
                  id="s_ntfy_priority"
                  value={form.ntfy_priority}
                  onChange={(e) => setField('ntfy_priority', parseInt(e.target.value))}
                  className={inputClass('ntfy_priority')}
                >
                  <option value={1}>1 - Min</option>
                  <option value={2}>2 - Low</option>
                  <option value={3}>3 - Default</option>
                  <option value={4}>4 - High</option>
                  <option value={5}>5 - Urgent</option>
                </select>
              </FormField>

              <FormField label="Disk Usage Threshold (%)" htmlFor="s_disk_threshold" hint="Send an alert when a guest's disk usage reaches or exceeds this percentage (50 -- 100)">
                <input
                  id="s_disk_threshold"
                  type="number"
                  min={50}
                  max={100}
                  value={form.notify_disk_threshold}
                  onChange={(e) => setField('notify_disk_threshold', parseInt(e.target.value) || 95)}
                  className={inputClass('notify_disk_threshold')}
                />
              </FormField>

              <FormField label="Disk Alert Cooldown (minutes)" htmlFor="s_disk_cooldown" hint="Minimum wait time before re-sending a disk alert for the same guest (15 -- 1440)">
                <input
                  id="s_disk_cooldown"
                  type="number"
                  min={15}
                  max={1440}
                  value={form.notify_disk_cooldown_minutes}
                  onChange={(e) => setField('notify_disk_cooldown_minutes', parseInt(e.target.value) || 60)}
                  className={inputClass('notify_disk_cooldown_minutes')}
                />
              </FormField>

              <Toggle
                id="s_notify_outdated"
                label="Notify on Outdated"
                checked={form.notify_on_outdated}
                onChange={(v) => setField('notify_on_outdated', v)}
                hint="Send a one-time alert when an app transitions from up-to-date to outdated"
              />

              <div className="pt-2">
                <button
                  type="button"
                  onClick={async () => {
                    setTestingNotification(true);
                    setNotificationTestResult(null);
                    try {
                      const res = await sendTestNotification();
                      setNotificationTestResult(res.success ? res.message : `Failed: ${res.message}`);
                    } catch (err) {
                      setNotificationTestResult(err instanceof Error ? err.message : 'Test failed');
                    } finally {
                      setTestingNotification(false);
                    }
                  }}
                  disabled={testingNotification || !form.ntfy_url}
                  className="px-4 py-1.5 text-sm font-medium rounded bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {testingNotification ? 'Sending...' : 'Send Test Notification'}
                </button>
                {notificationTestResult && (
                  <p className={`text-xs mt-2 ${notificationTestResult.startsWith('Failed') ? 'text-red-400' : 'text-green-400'}`}>
                    {notificationTestResult}
                  </p>
                )}
                {!form.ntfy_url && (
                  <p className="text-xs text-gray-500 mt-2">Save settings with a valid ntfy URL first to test notifications</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* App Configuration */}
      <AppConfigSection
        appConfigs={appConfigs}
        onChange={setAppConfigs}
        changedKeys={changedApiKeys}
        disabled={saving}
      />

      {/* Plugins */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Plugins (Detectors)</h2>
        <p className="text-xs text-gray-500 mb-3">
          Built-in detectors that identify applications running inside guests by name, tag, or Docker image.
        </p>
        <div className="space-y-1">
          {DETECTORS.map((d) => (
            <div key={d.name} className="flex items-center justify-between text-sm py-0.5">
              <span className="text-gray-300">{d.displayName}</span>
              <span className="px-1.5 py-0.5 text-[11px] font-semibold rounded bg-green-900 text-green-500">
                Enabled
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Sticky save bar */}
      <div className="fixed bottom-0 left-0 right-0 py-3 px-4 bg-background border-t border-gray-800 flex justify-center z-40">
        <div className="w-full max-w-7xl flex justify-end">
          <button
            type="button"
            onClick={handleSave}
            disabled={!isDirty || saving}
            aria-disabled={!isDirty || saving}
            className="w-full sm:w-auto px-6 py-2 text-sm font-medium rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Saving...
              </span>
            ) : (
              'Save Changes'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
