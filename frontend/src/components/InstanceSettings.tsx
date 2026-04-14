import { useState, useEffect } from 'react';
import type { AppConfigEntry, AppConfigDefault, CustomAppDef, GitHubTestResult } from '../types';
import { fetchGuestConfig, saveGuestConfig, deleteGuestConfig, refreshGuest, fetchAppConfigDefaults, fetchCustomApps, testGithubRepo } from '../api/client';
import SshFieldGroup from './shared/SshFieldGroup';

const SOURCE_LABELS: Record<string, string> = {
  'releases/latest': 'latest release',
  releases_list: 'releases list',
  tags: 'tags',
};
const REASON_LABELS: Record<string, string> = {
  invalid_url: 'Invalid URL or repo format.',
  not_found: 'Repository not found. Private repos require a GitHub token — add one in Settings.',
  rate_limited: 'GitHub rate limit reached. Configure a token in Settings to increase the limit.',
  no_releases_or_tags: 'No releases or tags found in this repository.',
  network_error: 'Network or timeout error.',
  unknown: 'Unknown error.',
};

export default function InstanceSettings({ guestId, appName, detectorUsed }: { guestId: string; appName: string; detectorUsed?: string | null }) {
  const [cfg, setCfg] = useState<AppConfigEntry & { forced_detector?: string | null }>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [messageIsError, setMessageIsError] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [appDefaults, setAppDefaults] = useState<AppConfigDefault[]>([]);
  const [customApps, setCustomApps] = useState<CustomAppDef[]>([]);
  const [testResult, setTestResult] = useState<GitHubTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [sshExpanded, setSshExpanded] = useState(false);
  const [showSshPassword, setShowSshPassword] = useState(false);
  const [versionUrl, setVersionUrl] = useState('');

  useEffect(() => {
    Promise.all([
      fetchGuestConfig(guestId),
      fetchAppConfigDefaults(),
      fetchCustomApps(),
    ])
      .then(([data, defaults, customs]) => {
        setCfg(data);
        setAppDefaults(defaults);
        setCustomApps(customs);
        // Combine scheme + version_host into a single display URL
        const host = data.version_host;
        const scheme = data.scheme;
        if (host && scheme) {
          setVersionUrl(`${scheme}://${host}`);
        } else if (host) {
          setVersionUrl(host);
        } else if (scheme && scheme !== 'http') {
          setVersionUrl(`${scheme}://`);
        } else {
          setVersionUrl('');
        }
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [guestId]);

  const hasOverrides = loaded && Object.values(cfg).some((v) => v != null && v !== '');

  const customNames = new Set(customApps.map((c) => c.name));
  const builtinDefaults = appDefaults.filter((d) => !customNames.has(d.name));
  const customDefaults = appDefaults.filter((d) => customNames.has(d.name));
  const inheritedGithubRepo = appDefaults.find((d) => d.name === detectorUsed)?.github_repo ?? null;

  const allKnownNames = new Set(appDefaults.map((d) => d.name));
  const forcedDetector = (cfg as Record<string, unknown>).forced_detector as string | null | undefined;
  const isStaleForcedDetector = forcedDetector && !allKnownNames.has(forcedDetector);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    setMessageIsError(false);
    try {
      await saveGuestConfig(guestId, cfg);
      setMessage('Saved. Refreshing...');
      await refreshGuest(guestId);
      setMessage('Saved successfully.');
    } catch (err) {
      setMessageIsError(true);
      setMessage(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleVersionUrlChange = (input: string) => {
    setVersionUrl(input);
    const trimmed = input.trim();
    const lower = trimmed.toLowerCase();
    if (!trimmed) {
      setCfg({ ...cfg, scheme: null, version_host: null });
    } else if (lower.startsWith('https://')) {
      const host = trimmed.slice(8).replace(/\/+$/, '');
      setCfg({ ...cfg, scheme: 'https', version_host: host || null });
    } else if (lower.startsWith('http://')) {
      const host = trimmed.slice(7).replace(/\/+$/, '');
      setCfg({ ...cfg, scheme: null, version_host: host || null });
    } else {
      setCfg({ ...cfg, scheme: null, version_host: trimmed });
    }
  };

  const handleReset = async () => {
    setSaving(true);
    setMessage(null);
    setMessageIsError(false);
    try {
      await deleteGuestConfig(guestId);
      setCfg({});
      setVersionUrl('');
      setMessage('Reset to defaults. Refreshing...');
      await refreshGuest(guestId);
      setMessage('Reset to defaults.');
    } catch (err) {
      setMessageIsError(true);
      setMessage(err instanceof Error ? err.message : 'Reset failed');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!cfg.github_repo) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testGithubRepo(cfg.github_repo);
      setTestResult(result);
    } catch {
      setTestResult({ ok: false, repo: cfg.github_repo ?? '', version: null, source: null, reason: 'network_error' });
    } finally {
      setTesting(false);
    }
  };

  const handleClearStaleForcedDetector = async () => {
    setSaving(true);
    setMessage(null);
    setMessageIsError(false);
    try {
      const updated = { ...cfg, forced_detector: null };
      await saveGuestConfig(guestId, updated);
      setCfg(updated);
      setMessage('Cleared. Refreshing...');
      await refreshGuest(guestId);
      setMessage('Cleared successfully.');
    } catch (err) {
      setMessageIsError(true);
      setMessage(err instanceof Error ? err.message : 'Clear failed');
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) return null;

  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
        aria-expanded={expanded}
      >
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider">
          Instance Settings
        </h2>
        {hasOverrides && (
          <span className="px-1.5 py-0.5 text-[10px] font-semibold rounded bg-blue-900/40 text-blue-400">
            CUSTOM
          </span>
        )}
        <svg
          className={`w-3.5 h-3.5 text-gray-500 ml-auto transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {!expanded && (
        <p className="text-xs text-gray-600 mt-1">
          Override port, API key, version URL, GitHub repo, or SSH settings for this {appName} instance.
        </p>
      )}
      {expanded && (
        <div className="mt-3 space-y-3">
          {/* Monitored app dropdown */}
          <div>
            <label htmlFor="gc-forced-detector" className="text-xs text-gray-500">Monitored app</label>
            {isStaleForcedDetector ? (
              <div className="mt-1 p-2 rounded bg-amber-900/20 border border-amber-800/50 text-sm text-amber-400 flex items-center gap-2">
                <span>Previously assigned app no longer exists -- reassign or clear.</span>
                <button
                  type="button"
                  onClick={handleClearStaleForcedDetector}
                  disabled={saving}
                  className="px-2 py-1 text-xs rounded bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-50"
                >
                  Clear
                </button>
              </div>
            ) : (
              <>
                <select
                  id="gc-forced-detector"
                  value={forcedDetector ?? ''}
                  onChange={(e) => setCfg({ ...cfg, forced_detector: e.target.value || null } as typeof cfg)}
                  className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="">None -- use auto-detection only</option>
                  <optgroup label="Built-in apps">
                    {builtinDefaults.map((d) => (
                      <option key={d.name} value={d.name}>{d.display_name}</option>
                    ))}
                  </optgroup>
                  {customDefaults.length > 0 && (
                    <optgroup label="Custom apps">
                      {customDefaults.map((d) => (
                        <option key={d.name} value={d.name}>{d.display_name}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <p className="text-xs text-gray-600 mt-0.5">
                  Leave as 'None' if auto-detection is working. Only set this to override or when detection fails.
                </p>
              </>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="gc-port" className="text-xs text-gray-500">Port override</label>
              <input
                id="gc-port"
                type="number"
                value={cfg.port ?? ''}
                placeholder="Default"
                onChange={(e) => setCfg({ ...cfg, port: e.target.value ? parseInt(e.target.value, 10) : null })}
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="gc-apikey" className="text-xs text-gray-500">API Key</label>
              <input
                id="gc-apikey"
                type="password"
                value={cfg.api_key ?? ''}
                placeholder="Inherit from global"
                onChange={(e) => setCfg({ ...cfg, api_key: e.target.value })}
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Version URL override */}
          <div>
            <label htmlFor="gc-version-host" className="text-xs text-gray-500">Version check URL / IP</label>
            <input
              id="gc-version-host"
              type="text"
              value={versionUrl}
              placeholder="e.g. https://192.168.1.50 or 192.168.1.50"
              onChange={(e) => handleVersionUrlChange(e.target.value)}
              className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-600 mt-0.5">
              Override the IP/host proxmon probes for version checks. Prefix with https:// for HTTPS. Defaults to HTTP when omitted.
            </p>
          </div>

          {/* GitHub repo override */}
          <div>
            <label htmlFor="gc-github-repo" className="text-xs text-gray-500">GitHub repo override</label>
            <div className="flex items-center gap-2 mt-0.5">
              <input
                id="gc-github-repo"
                type="text"
                value={cfg.github_repo ?? ''}
                placeholder={inheritedGithubRepo ? `Inherited: ${inheritedGithubRepo}` : 'owner/repo or full GitHub URL'}
                onChange={(e) => { setCfg({ ...cfg, github_repo: e.target.value || null }); setTestResult(null); }}
                className="flex-1 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              {cfg.github_repo && (
                <button
                  type="button"
                  aria-label="Clear GitHub repo override"
                  onClick={() => { setCfg({ ...cfg, github_repo: null }); setTestResult(null); }}
                  className="text-gray-500 hover:text-white text-lg leading-none"
                >x</button>
              )}
              <button
                type="button"
                onClick={handleTest}
                disabled={testing || !cfg.github_repo}
                className="px-3 py-1.5 text-sm rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-40 transition-colors"
              >
                {testing ? 'Checking\u2026' : 'Check'}
              </button>
            </div>
            <p className="text-xs text-gray-600 mt-0.5">
              owner/repo or full GitHub URL accepted.
              {inheritedGithubRepo && ` Overrides the detector default (${inheritedGithubRepo}).`}
            </p>
            {testResult && (
              <p className={`text-xs mt-1 ${testResult.ok ? 'text-green-400' : 'text-red-400'}`}>
                {testResult.ok
                  ? `Latest release: ${testResult.version} (found via ${SOURCE_LABELS[testResult.source ?? ''] ?? testResult.source ?? 'unknown source'})`
                  : (REASON_LABELS[testResult.reason ?? ''] ?? REASON_LABELS['unknown'])}
              </p>
            )}
          </div>
          {/* SSH overrides */}
          <div>
            <button
              type="button"
              onClick={() => setSshExpanded(!sshExpanded)}
              className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
              aria-expanded={sshExpanded}
              aria-controls="gc-ssh-panel"
            >
              <span>{sshExpanded ? '\u25BC' : '\u25B6'}</span>
              <span>SSH</span>
            </button>
            {sshExpanded && (
              <div id="gc-ssh-panel">
                <SshFieldGroup
                  idPrefix="gc"
                  versionCmd={cfg.ssh_version_cmd ?? ''}
                  username={cfg.ssh_username ?? ''}
                  keyPath={cfg.ssh_key_path ?? ''}
                  password={cfg.ssh_password ?? ''}
                  showPassword={showSshPassword}
                  onVersionCmdChange={(v) => setCfg({ ...cfg, ssh_version_cmd: v || null })}
                  onUsernameChange={(v) => setCfg({ ...cfg, ssh_username: v || null })}
                  onKeyPathChange={(v) => setCfg({ ...cfg, ssh_key_path: v || null })}
                  onPasswordChange={(v) => setCfg({ ...cfg, ssh_password: v || null })}
                  onToggleShowPassword={() => setShowSshPassword(!showSshPassword)}
                  passwordPlaceholder="masked"
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-colors"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            {hasOverrides && (
              <button
                onClick={handleReset}
                disabled={saving}
                className="px-3 py-1.5 text-sm rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-50 transition-colors"
              >
                Reset to defaults
              </button>
            )}
            {message && (
              <span className={`text-xs ${messageIsError ? 'text-red-400' : 'text-green-400'}`}>
                {message}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
