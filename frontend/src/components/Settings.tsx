import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { FullSettings, SettingsSaveRequest, AppConfigEntry, AppConfigDefault, ProxmoxHost } from '../types';
import { fetchFullSettings, saveSettings, changePassword, fetchAppConfigDefaults } from '../api/client';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';
import SuccessToast from './setup/SuccessToast';
import AppConfigSection from './settings/AppConfigSection';
import CustomAppsSection from './settings/CustomAppsSection';
import DiscoverySection from './settings/DiscoverySection';
import GitHubSection from './settings/GitHubSection';
import NotificationsSection from './settings/NotificationsSection';
import ProxmoxHostsSection from './settings/ProxmoxHostsSection';
import SecuritySection from './settings/SecuritySection';
import SSHSection from './settings/SSHSection';

type AuthMethod = 'key' | 'password';
type SettingsTab = 'connection' | 'security' | 'notifications' | 'apps';

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'connection',    label: 'Connection' },
  { id: 'security',     label: 'Security' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'apps',         label: 'Apps' },
];

interface FormData {
  poll_interval_seconds: number;
  pending_updates_interval_seconds: number;
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
  proxmon_api_key: string;
  trust_proxy_headers: boolean;
}

interface FormErrors {
  [key: string]: string | undefined;
}

function settingsToFormData(s: FullSettings): FormData {
  return {
    poll_interval_seconds: s.poll_interval_seconds,
    pending_updates_interval_seconds: s.pending_updates_interval_seconds ?? 3600,
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
    proxmon_api_key: (s.proxmon_api_key && s.proxmon_api_key !== '***') ? s.proxmon_api_key : '',
    trust_proxy_headers: s.trust_proxy_headers ?? false,
  };
}

function initHostsFromSettings(s: FullSettings): ProxmoxHost[] {
  if (s.proxmox_hosts && s.proxmox_hosts.length > 0) {
    return s.proxmox_hosts;
  }
  return [{
    id: (crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)),
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
    backup_storage: null,
  }];
}

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [form, setForm] = useState<FormData | null>(null);
  const [savedForm, setSavedForm] = useState<FormData | null>(null);
  const [errors, setErrors] = useState<FormErrors>({});
  // UI-only hint derived from stored credentials; not persisted.
  const [authMethod, setAuthMethod] = useState<AuthMethod>('key');
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const ntfyTokenChanged = useRef(false);
  const apiKeyChanged = useRef(false);
  const githubTokenChanged = useRef(false);
  // Per-app configuration
  const [appConfigs, setAppConfigs] = useState<Record<string, AppConfigEntry>>({});
  const [savedAppConfigs, setSavedAppConfigs] = useState<Record<string, AppConfigEntry>>({});
  const changedApiKeys = useRef<Set<string>>(new Set());
  // Multi-host
  const [proxmoxHosts, setProxmoxHosts] = useState<ProxmoxHost[]>([]);
  const [savedProxmoxHosts, setSavedProxmoxHosts] = useState<ProxmoxHost[]>([]);
  // Auth password local state
  const [authPasswordSet, setAuthPasswordSet] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  // Detectors loaded from API
  const [detectors, setDetectors] = useState<AppConfigDefault[]>([]);
  // Tab state — persisted in sessionStorage
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    () => (sessionStorage.getItem('proxmon_settings_tab') as SettingsTab) ?? 'connection'
  );
  const [pendingTab, setPendingTab] = useState<SettingsTab | null>(null);

  useEffect(() => {
    Promise.all([fetchFullSettings(), fetchAppConfigDefaults()])
      .then(([s, defaults]) => {
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
        setDetectors(defaults);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load settings'))
      .finally(() => setLoading(false));
  }, []);

  const setField = useCallback(<K extends keyof FormData>(key: K, value: FormData[K]) => {
    setForm((prev) => prev ? { ...prev, [key]: value } : prev);
    setErrors((prev) => ({ ...prev, [key]: undefined }));
    if (key === 'ntfy_token') {
      ntfyTokenChanged.current = true;
    }
    if (key === 'proxmon_api_key') {
      apiKeyChanged.current = true;
    }
    if (key === 'github_token') {
      githubTokenChanged.current = true;
    }
  }, []);

  const appConfigDirty =
    changedApiKeys.current.size > 0 ||
    JSON.stringify(appConfigs) !== JSON.stringify(savedAppConfigs);
  const hostsDirty = JSON.stringify(proxmoxHosts) !== JSON.stringify(savedProxmoxHosts);
  const passwordDirty = currentPassword !== '' || newPassword !== '' || confirmPassword !== '';
  const isDirty =
    ntfyTokenChanged.current ||
    apiKeyChanged.current ||
    githubTokenChanged.current ||
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

  const switchTab = useCallback((tab: SettingsTab) => {
    setActiveTab(tab);
    sessionStorage.setItem('proxmon_settings_tab', tab);
    setPendingTab(null);
  }, []);

  const handleTabClick = useCallback((tab: SettingsTab) => {
    if (tab === activeTab) return;
    if (isDirty) {
      setPendingTab(tab);
    } else {
      switchTab(tab);
    }
  }, [activeTab, isDirty, switchTab]);

  const handleTabKeyDown = useCallback((e: React.KeyboardEvent) => {
    const ids = TABS.map(t => t.id);
    const current = ids.indexOf(activeTab);
    if (e.key === 'ArrowRight') { e.preventDefault(); handleTabClick(ids[(current + 1) % ids.length]); }
    if (e.key === 'ArrowLeft')  { e.preventDefault(); handleTabClick(ids[(current - 1 + ids.length) % ids.length]); }
    if (e.key === 'Home')       { e.preventDefault(); handleTabClick(ids[0]); }
    if (e.key === 'End')        { e.preventDefault(); handleTabClick(ids[ids.length - 1]); }
  }, [activeTab, handleTabClick]);

  const validate = (): boolean => {
    if (!form) return false;
    const errs: FormErrors = {};

    if (proxmoxHosts.length === 0) {
      errs.proxmox_hosts = 'At least one host is required';
    }

    if (form.poll_interval_seconds < 30 || form.poll_interval_seconds > 86400)
      errs.poll_interval_seconds = 'Must be between 30 and 86400 seconds';
    if (form.pending_updates_interval_seconds < 3600 || form.pending_updates_interval_seconds > 86400)
      errs.pending_updates_interval_seconds = 'Must be between 3600 and 86400 seconds';
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
    if (newPassword && newPassword.length < 8) {
      setSaveError('New password must be at least 8 characters');
      return;
    }
    if (form.auth_mode === 'forms' && !authPasswordSet && (!newPassword || newPassword !== confirmPassword)) {
      setSaveError('Set a password and confirm it when enabling authentication');
      return;
    }
    if (newPassword && authPasswordSet && !currentPassword && savedForm?.auth_mode !== 'disabled') {
      setSaveError('Current password is required to change password');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
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

      const payload: SettingsSaveRequest = {
        poll_interval_seconds: form.poll_interval_seconds,
        pending_updates_interval_seconds: form.pending_updates_interval_seconds,
        discover_vms: form.discover_vms,
        verify_ssl: form.verify_ssl,
        ssh_enabled: form.ssh_enabled,
        ssh_username: form.ssh_username,
        ssh_key_path: form.ssh_key_path || null,
        ssh_password: form.ssh_password || null,
        github_token: githubTokenChanged.current ? (form.github_token || null) : null,
        log_level: form.log_level,
        version_detect_method: form.version_detect_method,
        auth_mode: form.auth_mode,
        auth_username: form.auth_username,
        ...(form.auth_mode === 'forms' && newPassword && (!authPasswordSet || savedForm?.auth_mode === 'disabled') ? { new_password: newPassword } : {}),
        app_config: Object.keys(appConfigPayload).length > 0 ? appConfigPayload : undefined,
        proxmox_hosts: hostsPayload,
        notifications_enabled: form.notifications_enabled,
        ntfy_url: form.ntfy_url,
        ntfy_token: ntfyTokenChanged.current ? (form.ntfy_token || null) : null,
        ntfy_priority: form.ntfy_priority,
        notify_disk_threshold: form.notify_disk_threshold,
        notify_disk_cooldown_minutes: form.notify_disk_cooldown_minutes,
        notify_on_outdated: form.notify_on_outdated,
        proxmon_api_key: apiKeyChanged.current ? (form.proxmon_api_key || null) : null,
        trust_proxy_headers: form.trust_proxy_headers,
      };
      await saveSettings(payload);
      if (form.auth_mode === 'forms' && newPassword && (!authPasswordSet || savedForm?.auth_mode === 'disabled')) {
        setNewPassword('');
        setConfirmPassword('');
        setAuthPasswordSet(true);
      }
      setSavedForm({ ...form });
      setSavedAppConfigs({ ...appConfigs });
      setSavedProxmoxHosts([...proxmoxHosts]);
      ntfyTokenChanged.current = false;
      apiKeyChanged.current = false;
      githubTokenChanged.current = false;
      changedApiKeys.current = new Set();
      setPendingTab(null);
      setToast('Settings saved. Discovery restarting...');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save settings');
      return;
    } finally {
      setSaving(false);
    }
    // Change password (existing) only after settings are fully committed
    if (newPassword && authPasswordSet && savedForm?.auth_mode !== 'disabled') {
      try {
        await changePassword(currentPassword, newPassword);
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
        setAuthPasswordSet(true);
      } catch (err) {
        setSaveError('Settings saved, but password change failed: ' + (err instanceof Error ? err.message : 'unknown error'));
      }
    }
  };

  if (loading) return <LoadingSpinner text="Loading settings..." />;
  if (error) return <ErrorBanner key={error} message={error} />;
  if (!form) return null;

  return (
    <div className="space-y-4 pb-20">
      {/* Error banner */}
      {saveError && <ErrorBanner key={saveError} message={`Save failed: ${saveError}`} />}

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

      {/* Tab bar */}
      <div
        role="tablist"
        aria-label="Settings sections"
        className="flex overflow-x-auto border-b border-gray-800"
      >
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            role="tab"
            id={`tab-${id}`}
            aria-selected={activeTab === id}
            aria-controls={`panel-${id}`}
            onClick={() => handleTabClick(id)}
            onKeyDown={handleTabKeyDown}
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
              activeTab === id
                ? 'border-blue-500 text-white'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Unsaved changes banner — shown when switching tabs with dirty form */}
      {pendingTab && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded bg-amber-900/30 border border-amber-800 text-amber-300 text-sm">
          <span>You have unsaved changes.</span>
          <div className="flex gap-3 shrink-0">
            <button
              onClick={() => switchTab(pendingTab)}
              className="underline hover:text-amber-200"
            >
              Switch anyway
            </button>
            <button
              onClick={() => setPendingTab(null)}
              className="text-gray-400 hover:text-gray-200"
            >
              Stay
            </button>
          </div>
        </div>
      )}

      {/* Tab panels */}
      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
      >
        {activeTab === 'connection' && (
          <div className="space-y-4">
            <ProxmoxHostsSection
              hosts={proxmoxHosts}
              onChange={setProxmoxHosts}
              disabled={saving}
            />
            <DiscoverySection
              pollInterval={form.poll_interval_seconds}
              pendingUpdatesInterval={form.pending_updates_interval_seconds}
              discoverVms={form.discover_vms}
              verifySsl={form.verify_ssl}
              versionDetectMethod={form.version_detect_method}
              errors={errors}
              onPollIntervalChange={(v) => setField('poll_interval_seconds', v)}
              onPendingUpdatesIntervalChange={(v) => setField('pending_updates_interval_seconds', v)}
              onDiscoverVmsChange={(v) => setField('discover_vms', v)}
              onVerifySslChange={(v) => setField('verify_ssl', v)}
              onVersionDetectMethodChange={(v) => setField('version_detect_method', v)}
              disabled={saving}
            />
          </div>
        )}

        {activeTab === 'security' && (
          <div className="space-y-4">
            <SecuritySection
              authMode={form.auth_mode}
              savedAuthMode={savedForm?.auth_mode}
              authUsername={form.auth_username}
              authPasswordSet={authPasswordSet}
              currentPassword={currentPassword}
              newPassword={newPassword}
              confirmPassword={confirmPassword}
              proxmonApiKey={form.proxmon_api_key}
              trustProxyHeaders={form.trust_proxy_headers}
              onAuthModeChange={(v) => setField('auth_mode', v)}
              onAuthUsernameChange={(v) => setField('auth_username', v)}
              onCurrentPasswordChange={setCurrentPassword}
              onNewPasswordChange={setNewPassword}
              onConfirmPasswordChange={setConfirmPassword}
              onApiKeyChange={(v) => setField('proxmon_api_key', v)}
              onTrustProxyHeadersChange={(v) => setField('trust_proxy_headers', v)}
              disabled={saving}
            />
            <SSHSection
              sshEnabled={form.ssh_enabled}
              sshUsername={form.ssh_username}
              sshKeyPath={form.ssh_key_path}
              sshPassword={form.ssh_password}
              authMethod={authMethod}
              onSshEnabledChange={(v) => setField('ssh_enabled', v)}
              onSshUsernameChange={(v) => setField('ssh_username', v)}
              onSshKeyPathChange={(v) => setField('ssh_key_path', v)}
              onSshPasswordChange={(v) => setField('ssh_password', v)}
              onAuthMethodChange={setAuthMethod}
              disabled={saving}
            />
            <GitHubSection
              githubToken={form.github_token}
              onGithubTokenChange={(v) => setField('github_token', v)}
              disabled={saving}
            />
          </div>
        )}

        {activeTab === 'notifications' && (
          <NotificationsSection
            enabled={form.notifications_enabled}
            ntfyUrl={form.ntfy_url}
            ntfyToken={form.ntfy_token}
            ntfyPriority={form.ntfy_priority}
            diskThreshold={form.notify_disk_threshold}
            diskCooldown={form.notify_disk_cooldown_minutes}
            notifyOnOutdated={form.notify_on_outdated}
            onEnabledChange={(v) => setField('notifications_enabled', v)}
            onNtfyUrlChange={(v) => setField('ntfy_url', v)}
            onNtfyTokenChange={(v) => setField('ntfy_token', v)}
            onNtfyPriorityChange={(v) => setField('ntfy_priority', v)}
            onDiskThresholdChange={(v) => setField('notify_disk_threshold', v)}
            onDiskCooldownChange={(v) => setField('notify_disk_cooldown_minutes', v)}
            onNotifyOnOutdatedChange={(v) => setField('notify_on_outdated', v)}
            disabled={saving}
          />
        )}

        {activeTab === 'apps' && (
          <div className="space-y-4">
            <AppConfigSection
              appConfigs={appConfigs}
              onChange={setAppConfigs}
              changedKeys={changedApiKeys}
              defaults={detectors}
              disabled={saving}
            />
            <CustomAppsSection />
            {detectors.length > 0 && (
              <div className="p-4 rounded bg-surface border border-gray-800">
                <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Plugins (Detectors)</h2>
                <p className="text-xs text-gray-500 mb-3">
                  Built-in detectors that identify applications running inside guests by name, tag, or Docker image.
                </p>
                <div className="space-y-1">
                  {detectors.map((d) => (
                    <div key={d.name} className="flex items-center justify-between text-sm py-0.5">
                      <span className="text-gray-300">{d.display_name}</span>
                      <span className="px-1.5 py-0.5 text-[11px] font-semibold rounded bg-green-900 text-green-500">
                        Enabled
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
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
