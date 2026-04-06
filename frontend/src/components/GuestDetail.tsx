import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { Guest as GuestDetailType, AppConfigEntry, AppConfigDefault, CustomAppDef, GitHubTestResult } from '../types';
import { fetchGuest, fetchGuestConfig, saveGuestConfig, deleteGuestConfig, refreshGuest, fetchAppConfigDefaults, fetchCustomApps, testGithubRepo } from '../api/client';
import StatusBadge from './StatusBadge';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';
import AppIcon from './AppIcon';
import GuestActions from './GuestActions';


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

function InstanceSettings({ guestId, appName, detectorUsed }: { guestId: string; appName: string; detectorUsed?: string | null }) {
  const [cfg, setCfg] = useState<AppConfigEntry & { forced_detector?: string | null }>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [appDefaults, setAppDefaults] = useState<AppConfigDefault[]>([]);
  const [customApps, setCustomApps] = useState<CustomAppDef[]>([]);
  const [testResult, setTestResult] = useState<GitHubTestResult | null>(null);
  const [testing, setTesting] = useState(false);

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
    try {
      await saveGuestConfig(guestId, cfg);
      setMessage('Saved. Refreshing...');
      await refreshGuest(guestId);
      setMessage('Saved successfully.');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await deleteGuestConfig(guestId);
      setCfg({});
      setMessage('Reset to defaults. Refreshing...');
      await refreshGuest(guestId);
      setMessage('Reset to defaults.');
    } catch (err) {
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
    try {
      const updated = { ...cfg, forced_detector: null };
      await saveGuestConfig(guestId, updated);
      setCfg(updated);
      setMessage('Cleared. Refreshing...');
      await refreshGuest(guestId);
      setMessage('Cleared successfully.');
    } catch (err) {
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
          Override port, API key, scheme, version hostname, or GitHub repo for this {appName} instance.
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

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
              <label htmlFor="gc-scheme" className="text-xs text-gray-500">Scheme</label>
              <select
                id="gc-scheme"
                value={cfg.scheme ?? 'http'}
                onChange={(e) => setCfg({ ...cfg, scheme: e.target.value === 'http' ? null : e.target.value })}
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="http">http</option>
                <option value="https">https</option>
              </select>
            </div>
            <div>
              <label htmlFor="gc-apikey" className="text-xs text-gray-500">API Key</label>
              <input
                id="gc-apikey"
                type="password"
                value={cfg.api_key ?? ''}
                placeholder="Inherit from global"
                onChange={(e) => setCfg({ ...cfg, api_key: e.target.value || null })}
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Version hostname override */}
          <div>
            <label htmlFor="gc-version-host" className="text-xs text-gray-500">Version check hostname / IP</label>
            <input
              id="gc-version-host"
              type="text"
              value={cfg.version_host ?? ''}
              placeholder="Auto-detected from Proxmox"
              onChange={(e) => setCfg({ ...cfg, version_host: e.target.value || null })}
              className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-600 mt-0.5">
              Override the IP proxmon probes for this guest's version endpoint. Useful when the auto-detected IP is not reachable.
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
                >×</button>
              )}
              <button
                type="button"
                onClick={handleTest}
                disabled={testing || !cfg.github_repo}
                className="px-3 py-1.5 text-sm rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-40 transition-colors"
              >
                {testing ? 'Checking…' : 'Check'}
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
              <span className={`text-xs ${message.includes('fail') ? 'text-red-400' : 'text-green-400'}`}>
                {message}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function GuestDetail() {
  const { id } = useParams<{ id: string }>();
  const [guest, setGuest] = useState<GuestDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawExpanded, setRawExpanded] = useState(false);

  const loadGuest = useCallback((guestId: string) => {
    setLoading(true);
    fetchGuest(guestId)
      .then(setGuest)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load guest'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!id) return;
    loadGuest(id);
  }, [id, loadGuest]);

  if (loading) return <LoadingSpinner text="Loading guest details..." />;
  if (error) return <ErrorBanner key={error} message={error} />;
  if (!guest) return <ErrorBanner message="Guest not found" />;

  const githubRepo = guest.github_repo_queried;
  const releaseUrl = githubRepo && guest.latest_version
    ? `https://github.com/${githubRepo}/releases`
    : null;

  const typeBadgeClass = guest.type === 'lxc'
    ? 'border-blue-500 text-blue-400'
    : 'border-purple-500 text-purple-400';

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="text-sm text-gray-500">
        <Link to="/" className="hover:text-white">Dashboard</Link>
        <span className="mx-2">&gt;</span>
        <span aria-current="page" className="text-gray-300 truncate max-w-[160px] sm:max-w-none inline-block align-bottom">{guest.name}</span>
      </nav>

      {/* Title + status */}
      <div className="flex items-center justify-between min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <AppIcon appName={guest.app_name} size={28} />
          <h1 className="text-xl font-bold text-white truncate">{guest.name}</h1>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={guest.update_status} />
          <GuestActions guest={guest} onActionComplete={() => { if (id) loadGuest(id); }} />
        </div>
      </div>

      {/* Metadata row */}
      <div className="flex flex-wrap items-center gap-2 text-sm text-gray-400">
        <span className={`inline-block px-1.5 py-0.5 text-[11px] font-semibold rounded border ${typeBadgeClass}`}>
          {guest.type.toUpperCase()}
        </span>
        <span>ID: {guest.id}</span>
        <span className="flex items-center gap-1">
          <span className={`inline-block w-2 h-2 rounded-full ${guest.status === 'running' ? 'bg-green-500' : 'bg-gray-500'}`} />
          {guest.status === 'running' ? 'Running' : 'Stopped'}
        </span>
        {guest.tags.length > 0 && (
          <span className="flex items-center gap-1">
            Tags: {guest.tags.map((tag) => (
              <span key={tag} className="px-1.5 py-0.5 text-[11px] rounded bg-gray-800 text-gray-400">{tag}</span>
            ))}
          </span>
        )}
      </div>

      {/* App Detection panel */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">App Detection</h2>
        {guest.app_name ? (
          <div className="space-y-1 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">App:</span>
              <AppIcon appName={guest.app_name} size={18} />
              <span className="text-gray-200">{guest.app_name}</span>
            </div>
            <div><span className="text-gray-500">Detection method:</span> <span className="text-gray-200">{guest.detection_method || '\u2014'}</span></div>
            <div><span className="text-gray-500">Plugin:</span> <span className="text-gray-200">{guest.detector_used || '\u2014'}</span></div>
            <div className="pt-2">
              {guest.web_url ? (
                <a
                  href={guest.web_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={guest.web_url}
                  aria-label={`Open ${guest.app_name} at ${guest.web_url} (opens in new tab)`}
                  className="inline-flex items-center gap-1.5 py-2.5 px-4 sm:py-1.5 sm:px-3 text-sm rounded border border-blue-500/50 text-blue-400 hover:bg-blue-500/10 hover:border-blue-400 transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 focus-visible:outline-offset-2"
                  data-testid="app-link"
                >
                  Open {guest.app_name}
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </a>
              ) : (
                <span className="text-sm text-gray-500">No web address detected.</span>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            No app detected for this guest. The guest may be stopped, running an unsupported app, or detection may have failed.
          </p>
        )}
      </div>

      {/* Instance Settings (per-guest overrides) */}
      <InstanceSettings guestId={guest.id} appName={guest.app_name || guest.name} detectorUsed={guest.detector_used} />

      {/* Version Status panel */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Version Status</h2>
        <div className="space-y-1 text-sm">
          <div>
            <span className="text-gray-500">Installed:</span>{' '}
            <span className="text-base sm:text-lg font-mono text-gray-200">{guest.installed_version || '\u2014'}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-500">Latest:</span>{' '}
            <span className={`text-base sm:text-lg font-mono ${guest.update_status === 'outdated' ? 'text-green-400' : 'text-gray-200'}`}>
              {guest.latest_version || '\u2014'}
            </span>
            {releaseUrl && (
              <a
                href={releaseUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300"
                aria-label={`View release notes for ${guest.app_name} ${guest.latest_version} (opens in new tab)`}
              >
                View release notes &rarr;
              </a>
            )}
          </div>
          <div>
            <span className="text-gray-500">Checked:</span>{' '}
            <span className="text-gray-300">{guest.last_checked ? new Date(guest.last_checked).toLocaleString() : '\u2014'}</span>
          </div>
          {guest.ip && (
            <div>
              <span className="text-gray-500">IP:</span>{' '}
              <span className="text-gray-300 font-mono">{guest.ip}</span>
            </div>
          )}
        </div>
      </div>

      {/* OS Updates panel — only shown when data is available (LXC + SSH enabled) */}
      {(guest.pending_updates != null || guest.reboot_required != null) && (
        <div className="p-4 rounded bg-surface border border-gray-800">
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">OS Updates</h2>
          <div className="space-y-4 text-sm">

            {guest.pending_updates != null && (
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-gray-500">Package updates:</span>
                  {guest.pending_updates === 0 ? (
                    <span className="text-green-400">{'\u2713'} Up to date</span>
                  ) : (
                    <span className="text-amber-400 font-medium">{guest.pending_updates} pending</span>
                  )}
                </div>
                {guest.pending_updates > 0 && guest.pending_update_packages && guest.pending_update_packages.length > 0 && (
                  <ul className="mt-1 ml-2 pl-2 border-l border-gray-700 space-y-0.5">
                    {guest.pending_update_packages.map((pkg) => (
                      <li key={pkg} className="text-xs font-mono text-gray-300">{pkg}</li>
                    ))}
                  </ul>
                )}
                {guest.pending_updates_checked_at && (
                  <p className="text-xs text-gray-600 mt-1">
                    Last checked: {new Date(guest.pending_updates_checked_at).toLocaleString()}
                  </p>
                )}
              </div>
            )}

            {guest.reboot_required != null && (
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-gray-500">Reboot required:</span>
                  {guest.reboot_required ? (
                    <span className="text-orange-400 font-medium">{'\u26a0'} Yes — reboot required</span>
                  ) : (
                    <span className="text-green-400">{'\u2713'} No reboot needed</span>
                  )}
                </div>
                {guest.pending_updates_checked_at && (
                  <p className="text-xs text-gray-600 mt-1">
                    Last checked: {new Date(guest.pending_updates_checked_at).toLocaleString()}
                  </p>
                )}
              </div>
            )}

          </div>
        </div>
      )}

      {/* Version Detection panel */}
      {guest.app_name && (() => {
        const method = guest.version_detection_method;
        const installedVersion = guest.installed_version;
        const repoQueried = guest.github_repo_queried || githubRepo || null;
        const lookupStatus = guest.github_lookup_status;

        const methodConfig: Record<string, { label: string; bg: string; text: string }> = {
          http: { label: 'HTTP API', bg: 'bg-blue-900/40', text: 'text-blue-300' },
          ssh: { label: 'SSH command', bg: 'bg-yellow-900/40', text: 'text-yellow-300' },
          pct_exec: { label: 'Container exec (pct)', bg: 'bg-purple-900/40', text: 'text-purple-300' },
        };
        const fallback = installedVersion
          ? { label: 'Unknown', bg: 'bg-gray-800', text: 'text-gray-500' }
          : { label: 'Not detected', bg: 'bg-gray-800', text: 'text-gray-500' };
        const badge = method ? (methodConfig[method] || fallback) : fallback;

        const statusColors: Record<string, string> = {
          success: 'text-green-400',
          failed: 'text-red-400',
          no_repo: 'text-gray-500',
        };

        return (
          <div className="p-4 rounded bg-surface border border-gray-800">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Version Detection</h2>
            <div className="space-y-1 text-sm">
              <div>
                <span className="text-gray-500">Installed version source:</span>{' '}
                <span
                  className={`font-mono text-xs px-1.5 py-0.5 rounded ${badge.bg} ${badge.text}`}
                  aria-label={`Installed version source: ${badge.label}`}
                >
                  {badge.label}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Latest version source:</span>{' '}
                <span className="text-gray-200">
                  {guest.latest_version_source === 'custom'
                    ? 'App repository'
                    : 'GitHub Releases'}
                  {!guest.latest_version && <span className="text-gray-500"> (not found)</span>}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Repository:</span>{' '}
                {repoQueried ? (
                  <a
                    href={`https://github.com/${repoQueried}/releases`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300"
                    aria-label={`GitHub releases for ${repoQueried} (opens in new tab)`}
                  >
                    {repoQueried}
                  </a>
                ) : (
                  <span className="text-gray-500">{'\u2014'}</span>
                )}
              </div>
              {lookupStatus && (
                <div>
                  <span className="text-gray-500">Lookup status:</span>{' '}
                  <span className={statusColors[lookupStatus] || 'text-gray-500'}>
                    {lookupStatus === 'no_repo' ? 'No repo configured' : lookupStatus}
                  </span>
                </div>
              )}
              {guest.probe_url && (
                <div>
                  <span className="text-gray-500">Probe URL:</span>{' '}
                  <span className="text-gray-300 font-mono text-xs break-all">{guest.probe_url}</span>
                </div>
              )}
              {guest.probe_error && (
                <div>
                  <span className="text-gray-500">Probe error:</span>{' '}
                  <span className="text-amber-400 text-xs">{guest.probe_error}</span>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* Version History */}
      {guest.version_history.length > 0 && (
        <div className="p-4 rounded bg-surface border border-gray-800">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider">Version History</h2>
            <span className="text-xs text-gray-600">last {guest.version_history.length}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="px-2 py-1 text-xs text-gray-500 font-medium">Timestamp</th>
                  <th className="px-2 py-1 text-xs text-gray-500 font-medium">Installed</th>
                  <th className="px-2 py-1 text-xs text-gray-500 font-medium">Latest</th>
                  <th className="px-2 py-1 text-xs text-gray-500 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {[...guest.version_history].reverse().map((check) => (
                  <tr key={check.timestamp} className="border-b border-gray-800/50">
                    <td className="px-2 py-1 text-gray-400 text-xs">{new Date(check.timestamp).toLocaleString()}</td>
                    <td className="px-2 py-1 text-gray-300 font-mono">{check.installed_version || '\u2014'}</td>
                    <td className="px-2 py-1 text-gray-300 font-mono">{check.latest_version || '\u2014'}</td>
                    <td className="px-2 py-1">
                      <StatusBadge status={check.update_status as 'up-to-date' | 'outdated' | 'unknown'} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Raw Detection Output */}
      {guest.raw_detection_output && (
        <div className="p-4 rounded bg-surface border border-gray-800">
          <button
            onClick={() => setRawExpanded(!rawExpanded)}
            aria-expanded={rawExpanded}
            aria-controls="raw-output"
            className="text-xs font-medium text-gray-500 uppercase tracking-wider hover:text-gray-300"
          >
            {rawExpanded ? 'Hide raw output' : 'Show raw output'}
          </button>
          {rawExpanded && (
            <pre
              id="raw-output"
              className="mt-3 p-3 rounded bg-gray-900 text-xs text-gray-400 overflow-y-auto max-h-[200px] sm:max-h-[300px] font-mono"
            >
              {JSON.stringify(guest.raw_detection_output, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Back button */}
      <div>
        <Link to="/" className="text-sm text-blue-400 hover:text-blue-300">
          &larr; Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
