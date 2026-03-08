import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { FullSettings, SettingsSaveRequest, ConnectionTestResult } from '../types';
import { fetchFullSettings, saveSettings, testConnection } from '../api/client';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';
import FormField from './setup/FormField';
import PasswordField from './setup/PasswordField';
import Toggle from './setup/Toggle';
import ConnectionTestButton from './setup/ConnectionTestButton';
import SuccessToast from './setup/SuccessToast';

const DETECTORS = [
  { name: 'sonarr', displayName: 'Sonarr' },
  { name: 'radarr', displayName: 'Radarr' },
  { name: 'bazarr', displayName: 'Bazarr' },
  { name: 'prowlarr', displayName: 'Prowlarr' },
  { name: 'plex', displayName: 'Plex' },
  { name: 'immich', displayName: 'Immich' },
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
    ssh_password: s.ssh_password || '',
    github_token: s.github_token || '',
    log_level: s.log_level,
  };
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

  useEffect(() => {
    fetchFullSettings()
      .then((s) => {
        const fd = settingsToFormData(s);
        setForm(fd);
        setSavedForm(fd);
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
  }, []);

  // tokenSecretChanged must be ORed in: typing "***" back after changing it would
  // produce equal JSON strings, hiding a real change from the dirty check.
  const isDirty =
    tokenSecretChanged.current ||
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
    if (!form.proxmox_host) errs.proxmox_host = 'Proxmox Host is required';
    else if (!form.proxmox_host.startsWith('http://') && !form.proxmox_host.startsWith('https://'))
      errs.proxmox_host = 'Enter a valid URL starting with http:// or https://';
    if (!form.proxmox_token_id.trim()) errs.proxmox_token_id = 'Token ID is required';
    if (!form.proxmox_node.trim()) errs.proxmox_node = 'Node name is required';
    if (form.poll_interval_seconds < 30 || form.poll_interval_seconds > 3600)
      errs.poll_interval_seconds = 'Must be between 30 and 3600 seconds';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSave = async () => {
    if (!form || !validate()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload: SettingsSaveRequest = {
        proxmox_host: form.proxmox_host,
        proxmox_token_id: form.proxmox_token_id,
        // Send null if token wasn't changed (keep current)
        proxmox_token_secret: tokenSecretChanged.current ? form.proxmox_token_secret : null,
        proxmox_node: form.proxmox_node,
        poll_interval_seconds: form.poll_interval_seconds,
        discover_vms: form.discover_vms,
        verify_ssl: form.verify_ssl,
        ssh_enabled: form.ssh_enabled,
        ssh_username: form.ssh_username,
        ssh_key_path: form.ssh_key_path || null,
        ssh_password: form.ssh_password || null,
        github_token: form.github_token || null,
        log_level: form.log_level,
      };
      await saveSettings(payload);
      setSavedForm({ ...form });
      tokenSecretChanged.current = false;
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

      {/* Proxmox Connection */}
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

      {/* Discovery */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Discovery</h2>
        <div className="space-y-3">
          <FormField label="Poll Interval (seconds)" required error={errors.poll_interval_seconds} htmlFor="s_poll_interval">
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
            hint="Discover VMs in addition to LXC containers"
          />

          <Toggle
            id="s_verify_ssl"
            label="Verify SSL"
            checked={form.verify_ssl}
            onChange={(v) => setField('verify_ssl', v)}
          />

          {!form.verify_ssl && (
            <div className="flex items-start gap-2 p-2 rounded bg-amber-900/30 border border-amber-800 text-amber-400 text-xs">
              <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <span>SSL verification is disabled. Proxmox uses self-signed certificates by default.</span>
            </div>
          )}
        </div>
      </div>

      {/* SSH */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">SSH</h2>
        <div className="space-y-3">
          <Toggle
            id="s_ssh_enabled"
            label="Enable SSH"
            checked={form.ssh_enabled}
            onChange={(v) => setField('ssh_enabled', v)}
          />

          {form.ssh_enabled && (
            <>
              <FormField label="SSH Username" required htmlFor="s_ssh_username">
                <input
                  id="s_ssh_username"
                  type="text"
                  value={form.ssh_username}
                  onChange={(e) => setField('ssh_username', e.target.value)}
                  className={inputClass('ssh_username')}
                />
              </FormField>

              <div>
                <p className="text-xs text-gray-400 mb-2">Authentication</p>
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
                <FormField label="Private Key Path" htmlFor="s_ssh_key_path">
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

      {/* Plugins */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Plugins (Detectors)</h2>
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
            className="px-6 py-2 text-sm font-medium rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
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
