import { useState, useCallback, useEffect, useRef } from 'react';
import type { SettingsSaveRequest, ConnectionTestResult } from '../../types';
import { testConnection, saveSettings, fetchHealth } from '../../api/client';
import FormField from './FormField';
import PasswordField from './PasswordField';
import Toggle from './Toggle';
import ConnectionTestButton from './ConnectionTestButton';
import LoadingSpinner from '../LoadingSpinner';

const STEP_TITLES = [
  'Proxmox Connection',
  'Discovery',
  'SSH',
  'GitHub Token',
  'Review & Save',
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

const initialFormData: FormData = {
  proxmox_host: '',
  proxmox_token_id: '',
  proxmox_token_secret: '',
  proxmox_node: '',
  poll_interval_seconds: 300,
  discover_vms: false,
  verify_ssl: false,
  ssh_enabled: true,
  ssh_username: 'root',
  ssh_key_path: '',
  ssh_password: '',
  github_token: '',
  log_level: 'info',
};

interface SetupWizardProps {
  onComplete: () => void;
}

export default function SetupWizard({ onComplete }: SetupWizardProps) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormData>(initialFormData);
  const [errors, setErrors] = useState<FormErrors>({});
  const [authMethod, setAuthMethod] = useState<AuthMethod>('key');
  const [testPassed, setTestPassed] = useState(false);
  const [testSkipped, setTestSkipped] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const setField = useCallback(<K extends keyof FormData>(key: K, value: FormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    // Clear error on edit
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }, []);

  // --- Validation ---

  const validateStep1 = (): boolean => {
    const errs: FormErrors = {};
    if (!form.proxmox_host) {
      errs.proxmox_host = 'Proxmox Host is required';
    } else if (!form.proxmox_host.startsWith('http://') && !form.proxmox_host.startsWith('https://')) {
      errs.proxmox_host = 'Enter a valid URL starting with http:// or https://';
    }
    if (!form.proxmox_token_id.trim()) errs.proxmox_token_id = 'Token ID is required';
    if (!form.proxmox_token_secret.trim()) errs.proxmox_token_secret = 'Token Secret is required';
    if (!form.proxmox_node.trim()) errs.proxmox_node = 'Node name is required';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const validateStep2 = (): boolean => {
    const errs: FormErrors = {};
    if (form.poll_interval_seconds < 30 || form.poll_interval_seconds > 3600) {
      errs.poll_interval_seconds = 'Must be between 30 and 3600 seconds';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const validateStep3 = (): boolean => {
    if (!form.ssh_enabled) return true;
    const errs: FormErrors = {};
    if (!form.ssh_username.trim()) errs.ssh_username = 'Username is required when SSH is enabled';
    if (authMethod === 'key' && !form.ssh_key_path.trim()) errs.ssh_key_path = 'Key path is required';
    if (authMethod === 'password' && !form.ssh_password.trim()) errs.ssh_password = 'Password is required';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const validateBlur = (field: string) => {
    const value = form[field as keyof FormData];
    const errs = { ...errors };
    if (field === 'proxmox_host') {
      if (!value) errs.proxmox_host = 'Proxmox Host is required';
      else if (typeof value === 'string' && !value.startsWith('http://') && !value.startsWith('https://'))
        errs.proxmox_host = 'Enter a valid URL starting with http:// or https://';
      else delete errs.proxmox_host;
    }
    if (field === 'proxmox_token_id') {
      if (!value || (typeof value === 'string' && !value.trim())) errs.proxmox_token_id = 'Token ID is required';
      else delete errs.proxmox_token_id;
    }
    if (field === 'proxmox_token_secret') {
      if (!value || (typeof value === 'string' && !value.trim())) errs.proxmox_token_secret = 'Token Secret is required';
      else delete errs.proxmox_token_secret;
    }
    if (field === 'proxmox_node') {
      if (!value || (typeof value === 'string' && !value.trim())) errs.proxmox_node = 'Node name is required';
      else delete errs.proxmox_node;
    }
    if (field === 'poll_interval_seconds') {
      if (typeof value === 'number' && (value < 30 || value > 3600))
        errs.poll_interval_seconds = 'Must be between 30 and 3600 seconds';
      else delete errs.poll_interval_seconds;
    }
    setErrors(errs);
  };

  const handleNext = () => {
    let valid = true;
    if (step === 1) valid = validateStep1();
    if (step === 2) valid = validateStep2();
    if (step === 3) valid = validateStep3();
    if (valid) {
      setErrors({});
      setStep((s) => Math.min(s + 1, 5));
    }
  };

  const handleBack = () => {
    setErrors({});
    setStep((s) => Math.max(s - 1, 1));
  };

  const handleTest = async (): Promise<ConnectionTestResult> => {
    const result = await testConnection({
      proxmox_host: form.proxmox_host,
      proxmox_token_id: form.proxmox_token_id,
      proxmox_token_secret: form.proxmox_token_secret,
      proxmox_node: form.proxmox_node,
      verify_ssl: form.verify_ssl,
    });
    setTestPassed(result.success);
    return result;
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const payload: SettingsSaveRequest = {
        proxmox_host: form.proxmox_host,
        proxmox_token_id: form.proxmox_token_id,
        proxmox_token_secret: form.proxmox_token_secret,
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
      // Transition to discovery screen
      setTransitioning(true);
      // Poll health until guests are found or 30s timeout; await so finally clears saving state
      const startTime = Date.now();
      while (mountedRef.current && Date.now() - startTime < 30_000) {
        try {
          const h = await fetchHealth();
          if (h.guest_count > 0) break;
        } catch {
          // network hiccup — keep polling
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      if (mountedRef.current) {
        onComplete();
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  // --- Transition screen ---
  if (transitioning) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background">
        <LoadingSpinner text="" />
        <p className="text-sm text-gray-300 mt-2">Discovering your guests...</p>
        <p className="text-xs text-gray-500 mt-1">This may take up to 30 seconds.</p>
      </div>
    );
  }

  // --- Step content renderers ---

  const inputClass = (field: string) =>
    `w-full px-3 py-1.5 text-sm bg-surface border rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
      errors[field] ? 'border-red-500' : 'border-gray-800'
    }`;

  const renderStep1 = () => (
    <div className="space-y-4">
      <FormField label="Proxmox Host" required error={errors.proxmox_host} htmlFor="proxmox_host">
        <input
          id="proxmox_host"
          type="text"
          value={form.proxmox_host}
          onChange={(e) => setField('proxmox_host', e.target.value)}
          onBlur={() => validateBlur('proxmox_host')}
          placeholder="https://192.168.1.10:8006"
          aria-required
          aria-describedby={errors.proxmox_host ? 'proxmox_host-error' : undefined}
          className={inputClass('proxmox_host')}
        />
      </FormField>

      <FormField label="API Token ID" required error={errors.proxmox_token_id} htmlFor="proxmox_token_id">
        <input
          id="proxmox_token_id"
          type="text"
          value={form.proxmox_token_id}
          onChange={(e) => setField('proxmox_token_id', e.target.value)}
          onBlur={() => validateBlur('proxmox_token_id')}
          placeholder="root@pam!proxmon"
          aria-required
          aria-describedby={errors.proxmox_token_id ? 'proxmox_token_id-error' : undefined}
          className={inputClass('proxmox_token_id')}
        />
      </FormField>

      <PasswordField
        id="proxmox_token_secret"
        label="API Token Secret"
        required
        value={form.proxmox_token_secret}
        onChange={(v) => setField('proxmox_token_secret', v)}
        error={errors.proxmox_token_secret}
      />

      <FormField label="Node Name" required error={errors.proxmox_node} htmlFor="proxmox_node">
        <input
          id="proxmox_node"
          type="text"
          value={form.proxmox_node}
          onChange={(e) => setField('proxmox_node', e.target.value)}
          onBlur={() => validateBlur('proxmox_node')}
          placeholder="pve"
          aria-required
          aria-describedby={errors.proxmox_node ? 'proxmox_node-error' : undefined}
          className={inputClass('proxmox_node')}
        />
      </FormField>
    </div>
  );

  const renderStep2 = () => (
    <div className="space-y-4">
      <FormField label="Poll Interval (seconds)" required error={errors.poll_interval_seconds} htmlFor="poll_interval">
        <input
          id="poll_interval"
          type="number"
          min={30}
          max={3600}
          value={form.poll_interval_seconds}
          onChange={(e) => setField('poll_interval_seconds', parseInt(e.target.value) || 300)}
          onBlur={() => validateBlur('poll_interval_seconds')}
          className={inputClass('poll_interval_seconds')}
        />
      </FormField>

      <Toggle
        id="discover_vms"
        label="Include VMs"
        checked={form.discover_vms}
        onChange={(v) => setField('discover_vms', v)}
        hint="Discover VMs in addition to LXC containers"
      />

      <Toggle
        id="verify_ssl"
        label="Verify SSL"
        checked={form.verify_ssl}
        onChange={(v) => setField('verify_ssl', v)}
      />

      {!form.verify_ssl && (
        <div className="flex items-start gap-2 p-2 rounded bg-amber-900/30 border border-amber-800 text-amber-400 text-xs">
          <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          <span>SSL verification is disabled. Proxmox uses self-signed certificates by default. Enable only if you have a valid cert.</span>
        </div>
      )}
    </div>
  );

  const renderStep3 = () => (
    <div className="space-y-4">
      <Toggle
        id="ssh_enabled"
        label="Enable SSH"
        checked={form.ssh_enabled}
        onChange={(v) => setField('ssh_enabled', v)}
      />

      {form.ssh_enabled && (
        <div className="space-y-4 mt-2">
          <FormField label="SSH Username" required error={errors.ssh_username} htmlFor="ssh_username">
            <input
              id="ssh_username"
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
                  name="auth_method"
                  checked={authMethod === 'key'}
                  onChange={() => setAuthMethod('key')}
                  className="accent-blue-500"
                />
                Key file
              </label>
              <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="auth_method"
                  checked={authMethod === 'password'}
                  onChange={() => setAuthMethod('password')}
                  className="accent-blue-500"
                />
                Password
              </label>
            </div>
          </div>

          {authMethod === 'key' && (
            <FormField label="Private Key Path" required error={errors.ssh_key_path} htmlFor="ssh_key_path">
              <input
                id="ssh_key_path"
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
              id="ssh_password"
              label="SSH Password"
              value={form.ssh_password}
              onChange={(v) => setField('ssh_password', v)}
              error={errors.ssh_password}
            />
          )}
        </div>
      )}
    </div>
  );

  const renderStep4 = () => (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        A personal access token increases the GitHub API rate limit from 60 to 5,000 requests/hour,
        improving version-check accuracy for your guests.
      </p>
      <p className="text-xs text-gray-500">Leave blank to use the unauthenticated limit.</p>

      <PasswordField
        id="github_token"
        label="GitHub Token"
        value={form.github_token}
        onChange={(v) => setField('github_token', v)}
        hint="Optional"
      />
    </div>
  );

  const renderStep5 = () => {
    const maskSecret = (v: string) => (v ? '\u25CF\u25CF\u25CF\u25CF\u25CF\u25CF\u25CF\u25CF' : 'Not set');
    const maskTokenId = (v: string) => {
      if (!v) return 'Not set';
      const parts = v.split('!');
      return parts.length === 2 ? `${parts[0]}!****` : '****';
    };

    return (
      <div className="space-y-4">
        {saveError && (
          <div role="alert" className="px-3 py-2 rounded bg-red-900/60 border border-red-800 text-red-200 text-xs">
            Save failed: {saveError}
          </div>
        )}

        <div className="space-y-3 text-sm">
          <div>
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Proxmox Connection</h3>
            <div className="space-y-0.5 text-xs">
              <div className="flex"><span className="text-gray-500 w-28">Host</span><span className="text-gray-200">{form.proxmox_host}</span></div>
              <div className="flex"><span className="text-gray-500 w-28">Token ID</span><span className="text-gray-200 font-mono">{maskTokenId(form.proxmox_token_id)}</span></div>
              <div className="flex"><span className="text-gray-500 w-28">Token Secret</span><span className="text-gray-200">{maskSecret(form.proxmox_token_secret)}</span></div>
              <div className="flex"><span className="text-gray-500 w-28">Node</span><span className="text-gray-200">{form.proxmox_node}</span></div>
            </div>
          </div>

          <div>
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Discovery</h3>
            <div className="space-y-0.5 text-xs">
              <div className="flex"><span className="text-gray-500 w-28">Poll every</span><span className="text-gray-200">{form.poll_interval_seconds} s</span></div>
              <div className="flex"><span className="text-gray-500 w-28">Include VMs</span><span className="text-gray-200">{form.discover_vms ? 'Yes' : 'No'}</span></div>
              <div className="flex"><span className="text-gray-500 w-28">Verify SSL</span><span className="text-gray-200">{form.verify_ssl ? 'Yes' : 'No'}</span></div>
            </div>
          </div>

          <div>
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">SSH</h3>
            <div className="space-y-0.5 text-xs">
              <div className="flex"><span className="text-gray-500 w-28">Enabled</span><span className="text-gray-200">{form.ssh_enabled ? 'Yes' : 'No'}</span></div>
              {form.ssh_enabled && (
                <>
                  <div className="flex"><span className="text-gray-500 w-28">Username</span><span className="text-gray-200">{form.ssh_username}</span></div>
                  <div className="flex">
                    <span className="text-gray-500 w-28">Auth method</span>
                    <span className="text-gray-200">
                      {authMethod === 'key' ? `Key file${form.ssh_key_path ? ` (${form.ssh_key_path})` : ''}` : 'Password'}
                    </span>
                  </div>
                </>
              )}
            </div>
          </div>

          <div>
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">GitHub Token</h3>
            <p className="text-xs text-gray-200">{form.github_token ? 'Set' : 'Not set'}</p>
          </div>
        </div>

        <div className="pt-2 space-y-3">
          <ConnectionTestButton onTest={handleTest} />

          <button
            type="button"
            onClick={handleSave}
            disabled={saving || (!testPassed && !testSkipped)}
            className={`w-full px-4 py-2 text-sm font-medium rounded text-white disabled:opacity-50 disabled:cursor-not-allowed ${
              !testPassed && !testSkipped
                ? 'bg-blue-600/50 border-2 border-dashed border-amber-500'
                : 'bg-blue-600 hover:bg-blue-500'
            }`}
          >
            {saving ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Saving...
              </span>
            ) : (
              'Save & Start'
            )}
          </button>

          {!testPassed && !testSkipped && (
            <button
              type="button"
              onClick={() => setTestSkipped(true)}
              className="block w-full text-center text-xs text-gray-500 hover:text-gray-300"
            >
              Skip test and save anyway
            </button>
          )}
        </div>
      </div>
    );
  };

  const stepRenderers = [renderStep1, renderStep2, renderStep3, renderStep4, renderStep5];

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background px-4">
      {/* Progress bar */}
      <div className="w-full max-w-lg mb-6">
        {/* Step dots */}
        <div
          className="flex items-center justify-center gap-0 mb-4"
          role="progressbar"
          aria-valuenow={step}
          aria-valuemin={1}
          aria-valuemax={5}
          aria-label={`Setup progress, step ${step} of 5`}
        >
          {[1, 2, 3, 4, 5].map((s) => (
            <div key={s} className="flex items-center">
              <div
                className={`w-2 h-2 rounded-full ${
                  s < step
                    ? 'bg-blue-500'
                    : s === step
                    ? 'bg-blue-500 ring-2 ring-blue-500/40'
                    : 'bg-gray-700'
                }`}
              />
              {s < 5 && <div className="w-8 h-px bg-gray-700" />}
            </div>
          ))}
        </div>

        {/* Step label */}
        <div className="text-center">
          <p className="text-xs text-gray-500">Step {step} of 5</p>
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="text-sm font-medium text-gray-300 outline-none"
          >
            {STEP_TITLES[step - 1]}
          </h2>
        </div>
      </div>

      {/* Card */}
      <div className="w-full max-w-lg bg-surface border border-gray-800 rounded p-6">
        {stepRenderers[step - 1]()}
      </div>

      {/* Navigation */}
      <div className="w-full max-w-lg flex flex-col-reverse sm:flex-row sm:justify-between gap-2 mt-4">
        {step > 1 ? (
          <button
            type="button"
            onClick={handleBack}
            className="w-full sm:w-auto px-4 py-2.5 sm:py-1.5 text-sm text-gray-400 hover:text-white text-center"
          >
            Back
          </button>
        ) : (
          <div />
        )}
        {step < 5 && (
          <button
            type="button"
            onClick={handleNext}
            className="w-full sm:w-auto px-4 py-2.5 sm:py-1.5 text-sm font-medium rounded bg-blue-600 hover:bg-blue-500 text-white"
          >
            {step === 4 ? 'Review' : 'Next'}
          </button>
        )}
      </div>
    </div>
  );
}
