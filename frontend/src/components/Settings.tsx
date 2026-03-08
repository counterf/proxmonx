import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import type { AppSettings } from '../types';
import { fetchSettings, fetchHealth } from '../api/client';
import type { HealthStatus } from '../types';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';

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

export default function Settings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSettings(), fetchHealth()])
      .then(([s, h]) => {
        setSettings(s);
        setHealth(h);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load settings'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner text="Loading settings..." />;
  if (error) return <ErrorBanner message={error} />;
  if (!settings) return null;

  const connected = health?.status === 'ok';

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="text-sm text-gray-500">
        <Link to="/" className="hover:text-white">Dashboard</Link>
        <span className="mx-2">&gt;</span>
        <span aria-current="page" className="text-gray-300">Settings</span>
      </nav>

      <div>
        <h1 className="text-xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-500">Read-only in this version</p>
      </div>

      {/* Proxmox Connection */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Proxmox Connection</h2>
        <div className="space-y-1 text-sm">
          <div><span className="text-gray-500">Endpoint:</span> <span className="text-gray-200">{settings.proxmox_host}</span></div>
          <div><span className="text-gray-500">Token name:</span> <span className="text-gray-200 font-mono">{settings.proxmox_token_id}</span></div>
          <div className="flex items-center gap-2">
            <span className="text-gray-500">Status:</span>
            <span className={`px-1.5 py-0.5 text-[11px] font-semibold rounded ${connected ? 'bg-green-900 text-green-500' : 'bg-red-900 text-red-400'}`}>
              {connected ? 'Connected' : 'Unreachable'}
            </span>
          </div>
        </div>
      </div>

      {/* Discovery */}
      <div className="p-4 rounded bg-surface border border-gray-800">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Discovery</h2>
        <div className="space-y-1 text-sm">
          <div><span className="text-gray-500">Poll interval:</span> <span className="text-gray-200">{Math.floor(settings.poll_interval_seconds / 60)} minutes</span></div>
          <div><span className="text-gray-500">Guest types:</span> <span className="text-gray-200">LXC{settings.discover_vms ? ', VM' : ''}</span></div>
          <div><span className="text-gray-500">Node:</span> <span className="text-gray-200">{settings.proxmox_node}</span></div>
          <div><span className="text-gray-500">SSH enabled:</span> <span className="text-gray-200">{settings.ssh_enabled ? 'Yes' : 'No'}</span></div>
          <div><span className="text-gray-500">GitHub token:</span> <span className="text-gray-200">{settings.github_token_set ? 'Set' : 'Not set'}</span></div>
        </div>
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

      <p className="text-xs text-gray-600">
        To change settings, edit your <code className="text-gray-500">.env</code> file and restart proxmon.
      </p>
    </div>
  );
}
