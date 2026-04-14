import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import type { Guest as GuestDetailType } from '../types';
import { fetchGuest, fetchFullSettings } from '../api/client';
import StatusBadge from './StatusBadge';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';
import AppIcon from './AppIcon';
import GuestActions from './GuestActions';
import InstanceSettings from './InstanceSettings';


export default function GuestDetail() {
  const { id } = useParams<{ id: string }>();
  const [guest, setGuest] = useState<GuestDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backupEnabled, setBackupEnabled] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const loadGuest = useCallback((guestId: string) => {
    setError(null);
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

  useEffect(() => {
    if (!guest) return;
    fetchFullSettings()
      .then((s) => {
        const host = s.proxmox_hosts.find((h) => h.id === guest.host_id);
        setBackupEnabled(!!host?.backup_storage);
      })
      .catch(() => {});
  }, [guest?.host_id ?? null]);

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
          <GuestActions guest={guest} backupEnabled={backupEnabled} onActionComplete={() => {
            if (!id) return;
            if (pollRef.current) clearInterval(pollRef.current);
            const prev = guest.last_checked;
            let elapsed = 0;
            pollRef.current = setInterval(async () => {
              elapsed += 1000;
              try {
                const g = await fetchGuest(id);
                if (g.last_checked !== prev) {
                  if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                  setGuest(g);
                }
              } catch { /* ignore */ }
              if (elapsed >= 30000 && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            }, 1000);
          }} />
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

      {/* Version Info panel */}
      {(() => {
        const method = guest.app_name ? guest.version_detection_method : null;
        const repoQueried = guest.app_name ? (guest.github_repo_queried || githubRepo || null) : null;
        const lookupStatus = guest.app_name ? guest.github_lookup_status : null;

        const methodConfig: Record<string, { label: string; bg: string; text: string }> = {
          http: { label: 'HTTP API', bg: 'bg-blue-900/40', text: 'text-blue-300' },
          ssh: { label: 'SSH command', bg: 'bg-yellow-900/40', text: 'text-yellow-300' },
          pct_exec: { label: 'Container exec (pct)', bg: 'bg-purple-900/40', text: 'text-purple-300' },
        };
        const fallback = guest.installed_version
          ? { label: 'Unknown', bg: 'bg-gray-800', text: 'text-gray-500' }
          : { label: 'Not detected', bg: 'bg-gray-800', text: 'text-gray-500' };
        const badge = method ? (methodConfig[method] || fallback) : fallback;

        return (
          <div className="p-4 rounded bg-surface border border-gray-800">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Version Info</h2>
            <div className="space-y-1 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-gray-500">Installed:</span>{' '}
                <span className="text-base sm:text-lg font-mono text-gray-200">{guest.installed_version || '\u2014'}</span>
                {guest.app_name && (
                  <span
                    className={`font-mono text-xs px-1.5 py-0.5 rounded ${badge.bg} ${badge.text}`}
                    aria-label={`Installed version source: ${badge.label}`}
                  >
                    {badge.label}
                  </span>
                )}
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
                {guest.app_name && (
                  <span className="text-xs text-gray-500">
                    via {guest.latest_version_source === 'custom' ? 'App repository' : 'GitHub'}
                  </span>
                )}
              </div>
              {guest.app_name && (lookupStatus === 'failed' || lookupStatus === 'no_repo') && (
                <div>
                  <span className="text-gray-500">Lookup status:</span>{' '}
                  <span className={lookupStatus === 'failed' ? 'text-red-400' : 'text-gray-500'}>
                    {lookupStatus === 'no_repo' ? 'No repo configured' : lookupStatus}
                  </span>
                </div>
              )}
              {repoQueried && (
                <div>
                  <span className="text-gray-500">Repository:</span>{' '}
                  <a
                    href={`https://github.com/${repoQueried}/releases`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300"
                    aria-label={`GitHub releases for ${repoQueried} (opens in new tab)`}
                  >
                    {repoQueried}
                  </a>
                </div>
              )}
              <div>
                <span className="text-gray-500">Checked:</span>{' '}
                <span className="text-gray-300">{guest.last_checked ? new Date(guest.last_checked).toLocaleString() : '\u2014'}</span>
              </div>
              {guest.app_name && guest.probe_error && (
                <div>
                  <span className="text-gray-500">Probe error:</span>{' '}
                  <span className="text-amber-400 text-xs">{guest.probe_error}</span>
                </div>
              )}
              {guest.app_name && guest.probe_url && (
                <div>
                  <span className="text-gray-500">Probe URL:</span>{' '}
                  <span className="text-gray-300 font-mono text-xs break-all">{guest.probe_url}</span>
                </div>
              )}
              {guest.ip && (
                <div>
                  <span className="text-gray-500">IP:</span>{' '}
                  <span className="text-gray-300 font-mono">{guest.ip}</span>
                </div>
              )}
            </div>
          </div>
        );
      })()}

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
                {[...guest.version_history].reverse().map((check, index) => (
                  <tr key={`${check.timestamp}-${index}`} className="border-b border-gray-800/50">
                    <td className="px-2 py-1 text-gray-400 text-xs">{new Date(check.timestamp).toLocaleString()}</td>
                    <td className="px-2 py-1 text-gray-300 font-mono">{check.installed_version || '\u2014'}</td>
                    <td className="px-2 py-1 text-gray-300 font-mono">{check.latest_version || '\u2014'}</td>
                    <td className="px-2 py-1">
                      <StatusBadge status={check.update_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
