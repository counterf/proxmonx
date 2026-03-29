import { useNavigate } from 'react-router-dom';
import type { GuestSummary } from '../types';
import type { ColumnKey } from '../hooks/useColumnVisibility';
import StatusBadge from './StatusBadge';
import AppIcon from './AppIcon';
import GuestActions from './GuestActions';

interface GuestRowProps {
  guest: GuestSummary;
  visibleColumns?: Set<ColumnKey>;
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '\u2014';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  return `${diffDays}d ago`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(0)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  const gb = mb / 1024;
  if (gb < 1024) return `${gb.toFixed(1)} GB`;
  return `${(gb / 1024).toFixed(1)} TB`;
}

function diskBarColor(pct: number): string {
  if (pct > 90) return 'bg-red-500';
  if (pct > 75) return 'bg-amber-500';
  if (pct >= 50) return 'bg-green-500';
  return 'bg-blue-500';
}

function DiskUsageCell({ guest }: { guest: GuestSummary }) {
  if (guest.disk_used == null || guest.disk_total == null || guest.disk_total === 0) {
    return <span className="text-gray-500">{'\u2014'}</span>;
  }
  const pct = Math.min((guest.disk_used / guest.disk_total) * 100, 100);
  const color = diskBarColor(pct);
  const title = `${formatBytes(guest.disk_used)} / ${formatBytes(guest.disk_total)}`;
  return (
    <div className="flex items-center gap-1.5" title={title}>
      <div className="w-16 h-2 rounded-full bg-gray-700 overflow-hidden" aria-hidden="true">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 tabular-nums w-8 text-right">{pct.toFixed(0)}%</span>
    </div>
  );
}

const VERSION_SOURCE_STYLES: Record<string, { label: string; bg: string; text: string }> = {
  http: { label: 'API', bg: 'bg-blue-900/40', text: 'text-blue-300' },
  ssh: { label: 'SSH', bg: 'bg-yellow-900/40', text: 'text-yellow-300' },
  pct_exec: { label: 'PCT', bg: 'bg-purple-900/40', text: 'text-purple-300' },
};

function VersionSourceCell({ guest }: { guest: GuestSummary }) {
  const method = guest.version_detection_method;
  if (!method) return <span className="text-gray-500">{'\u2014'}</span>;
  const style = VERSION_SOURCE_STYLES[method];
  if (!style) return <span className="text-xs text-gray-400">{method}</span>;
  return (
    <span className={`inline-block px-1.5 py-0.5 text-[11px] font-medium rounded ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function PendingUpdatesCell({
  count,
  packages,
  rebootRequired,
}: {
  count: number | null | undefined;
  packages?: string[] | null;
  rebootRequired?: boolean | null;
}) {
  const tooltip =
    packages && packages.length > 0
      ? packages.slice(0, 30).join('\n') + (packages.length > 30 ? `\n…and ${packages.length - 30} more` : '')
      : undefined;

  return (
    <div className="flex flex-col items-center gap-0.5">
      {count == null ? (
        <span className="text-gray-600">{'\u2014'}</span>
      ) : count === 0 ? (
        <span className="text-green-400 text-xs">{'\u2713'} up to date</span>
      ) : (
        <span className="text-amber-400 text-xs font-medium cursor-help" title={tooltip}>
          {count} pending
        </span>
      )}
      {rebootRequired && (
        <span
          className="inline-block px-1.5 py-0.5 text-[10px] font-semibold rounded bg-orange-900/50 text-orange-400 border border-orange-800/50"
          title="Reboot required (/var/run/reboot-required)"
        >
          reboot
        </span>
      )}
    </div>
  );
}

function OsTypeCell({ guest }: { guest: GuestSummary }) {
  const os = guest.os_type;
  if (!os) return <span className="text-gray-500">{'\u2014'}</span>;
  const label = os.charAt(0).toUpperCase() + os.slice(1);
  return <span className="text-xs text-gray-300">{label}</span>;
}

function AppNameCell({ guest }: { guest: GuestSummary }) {
  if (!guest.app_name) {
    return <span className="text-gray-500">{'\u2014'}</span>;
  }
  const icon = (
    <AppIcon appName={guest.app_name} detectorKey={guest.detector_used} size={18} className="mr-1.5" />
  );
  if (guest.web_url) {
    return (
      <a
        href={guest.web_url}
        target="_blank"
        rel="noopener noreferrer"
        title={guest.web_url}
        aria-label={`Open ${guest.app_name} at ${guest.web_url} (opens in new tab)`}
        className="inline-flex items-center text-blue-400 hover:text-blue-300 hover:underline focus-visible:outline-2 focus-visible:outline-blue-500 focus-visible:outline-offset-2 focus-visible:rounded py-2 -my-2 px-1 -mx-1"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => { if (e.key === 'Enter') e.stopPropagation(); }}
        data-testid="app-link"
      >
        {icon}
        {guest.app_name}
        <svg className="w-3 h-3 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
        </svg>
      </a>
    );
  }
  return (
    <span className="inline-flex items-center text-gray-300">
      {icon}
      {guest.app_name}
    </span>
  );
}

/** Table row for desktop (>= md) */
export function GuestTableRow({ guest, visibleColumns }: GuestRowProps) {
  const navigate = useNavigate();
  const vis = visibleColumns ?? new Set<ColumnKey>();

  const typeBadgeClass = guest.type === 'lxc'
    ? 'border-blue-500 text-blue-400'
    : 'border-purple-500 text-purple-400';

  return (
    <tr
      tabIndex={0}
      className="border-b border-gray-800 hover:bg-gray-800/50 cursor-pointer transition-colors"
      onClick={() => navigate(`/guest/${guest.id}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigate(`/guest/${guest.id}`);
        }
      }}
    >
      {vis.has('name') && (
        <td className="px-3 py-2 text-sm text-gray-200 max-w-[200px]" title={guest.name}>
          <span className="flex items-center gap-1.5 min-w-0">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${guest.status === 'running' ? 'bg-green-500' : 'bg-gray-600'}`}
              title={guest.status}
              aria-label={guest.status}
            />
            <span className="truncate">{guest.name}</span>
          </span>
        </td>
      )}
      {vis.has('type') && (
        <td className="px-3 py-2">
          <span
            className={`inline-block px-1.5 py-0.5 text-[11px] font-semibold rounded border ${typeBadgeClass}`}
            aria-label={`Type: ${guest.type.toUpperCase()}`}
          >
            {guest.type.toUpperCase()}
          </span>
        </td>
      )}
      {vis.has('host_label') && (
        <td className="px-3 py-2 text-sm text-gray-400 truncate max-w-[120px]" title={guest.host_label}>
          {guest.host_label}
        </td>
      )}
      {vis.has('app_name') && (
        <td className="px-3 py-2 text-sm">
          <AppNameCell guest={guest} />
        </td>
      )}
      {vis.has('installed_version') && (
        <td className="px-3 py-2 text-sm text-gray-300 font-mono">
          {guest.installed_version || '\u2014'}
        </td>
      )}
      {vis.has('latest_version') && (
        <td className="px-3 py-2 text-sm text-gray-300 font-mono">
          {guest.latest_version || '\u2014'}
        </td>
      )}
      {vis.has('update_status') && (
        <td className="px-3 py-2">
          <StatusBadge status={guest.update_status} />
        </td>
      )}
      {vis.has('disk') && (
        <td className="px-3 py-2">
          <DiskUsageCell guest={guest} />
        </td>
      )}
      {vis.has('version_detection_method') && (
        <td className="px-3 py-2">
          <VersionSourceCell guest={guest} />
        </td>
      )}
      {vis.has('os_type') && (
        <td className="px-3 py-2">
          <OsTypeCell guest={guest} />
        </td>
      )}
      {vis.has('pending_updates') && (
        <td className="px-3 py-2 text-center">
          <PendingUpdatesCell count={guest.pending_updates} packages={guest.pending_update_packages} rebootRequired={guest.reboot_required} />
        </td>
      )}
      {vis.has('last_checked') && (
        <td className="px-3 py-2 text-xs text-gray-500" title={guest.last_checked || ''}>
          {formatRelativeTime(guest.last_checked)}
        </td>
      )}
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <button
            className="text-xs text-blue-400 hover:text-blue-300"
            aria-label={`View details for ${guest.name}`}
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/guest/${guest.id}`);
            }}
          >
            View
          </button>
          <GuestActions guest={guest} />
        </div>
      </td>
    </tr>
  );
}

/** Card layout for mobile (< md) */
export function GuestCard({ guest }: GuestRowProps) {
  const navigate = useNavigate();

  const typeBadgeClass = guest.type === 'lxc'
    ? 'border-blue-500 text-blue-400'
    : 'border-purple-500 text-purple-400';

  const versionStr = guest.installed_version
    ? guest.update_status === 'outdated' && guest.latest_version
      ? `${guest.installed_version} -> ${guest.latest_version}`
      : guest.installed_version
    : null;

  return (
    <div
      tabIndex={0}
      role="button"
      className="border border-gray-800 rounded px-4 py-3 mb-2 hover:bg-gray-800/50 cursor-pointer transition-colors"
      onClick={() => navigate(`/guest/${guest.id}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigate(`/guest/${guest.id}`);
        }
      }}
      data-testid="guest-card"
    >
      {/* Row 1: name + status */}
      <div className="flex items-center justify-between mb-1">
        <span className="flex items-center gap-1.5 min-w-0 mr-2">
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${guest.status === 'running' ? 'bg-green-500' : 'bg-gray-600'}`}
            title={guest.status}
            aria-label={guest.status}
          />
          <span className="text-sm font-medium text-gray-200 truncate">{guest.name}</span>
        </span>
        <div className="flex items-center gap-2 shrink-0">
          <StatusBadge status={guest.update_status} />
          <GuestActions guest={guest} />
        </div>
      </div>
      {/* Row 2: type + app */}
      <div className="flex items-center gap-2 text-sm text-gray-300 mb-1">
        <span className={`inline-block px-1.5 py-0.5 text-[11px] font-semibold rounded border ${typeBadgeClass}`}>
          {guest.type.toUpperCase()}
        </span>
        <span className="text-gray-600">{'\u00B7'}</span>
        <AppNameCell guest={guest} />
      </div>
      {/* Row 3: version + disk + last checked */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="font-mono truncate max-w-[140px]">{versionStr || '\u2014'}</span>
        <div className="flex items-center gap-3">
          {(guest.pending_updates != null || guest.reboot_required) && (
            <PendingUpdatesCell count={guest.pending_updates} packages={guest.pending_update_packages} rebootRequired={guest.reboot_required} />
          )}
          <DiskUsageCell guest={guest} />
          <span>{formatRelativeTime(guest.last_checked)}</span>
        </div>
      </div>
    </div>
  );
}

/** Default export for backward compatibility */
export default function GuestRow({ guest }: GuestRowProps) {
  return <GuestTableRow guest={guest} />;
}
