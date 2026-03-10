import { useNavigate } from 'react-router-dom';
import type { GuestSummary } from '../types';
import StatusBadge from './StatusBadge';

interface GuestRowProps {
  guest: GuestSummary;
  showHostCol?: boolean;
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

function AppNameCell({ guest }: { guest: GuestSummary }) {
  if (!guest.app_name) {
    return <span className="text-gray-500">{'\u2014'}</span>;
  }
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
        {guest.app_name}
        <svg className="w-3 h-3 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
        </svg>
      </a>
    );
  }
  return <span className="text-gray-300">{guest.app_name}</span>;
}

/** Table row for desktop (>= md) */
export function GuestTableRow({ guest, showHostCol = false }: GuestRowProps) {
  const navigate = useNavigate();

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
      <td className="px-3 py-2 text-sm text-gray-200 truncate max-w-[200px]" title={guest.name}>
        {guest.name}
      </td>
      <td className="px-3 py-2">
        <span
          className={`inline-block px-1.5 py-0.5 text-[11px] font-semibold rounded border ${typeBadgeClass}`}
          aria-label={`Type: ${guest.type.toUpperCase()}`}
        >
          {guest.type.toUpperCase()}
        </span>
      </td>
      {showHostCol && (
        <td className="px-3 py-2 text-sm text-gray-400 truncate max-w-[120px]" title={guest.host_label}>
          {guest.host_label}
        </td>
      )}
      <td className="px-3 py-2 text-sm">
        <AppNameCell guest={guest} />
      </td>
      <td className="px-3 py-2 text-sm text-gray-300 font-mono">
        {guest.installed_version || '\u2014'}
      </td>
      <td className="px-3 py-2 text-sm text-gray-300 font-mono">
        {guest.latest_version || '\u2014'}
      </td>
      <td className="px-3 py-2">
        <StatusBadge status={guest.update_status} />
      </td>
      <td className="px-3 py-2 text-xs text-gray-500" title={guest.last_checked || ''}>
        {formatRelativeTime(guest.last_checked)}
      </td>
      <td className="px-3 py-2">
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
        <span className="text-sm font-medium text-gray-200 truncate mr-2">{guest.name}</span>
        <StatusBadge status={guest.update_status} />
      </div>
      {/* Row 2: type + app */}
      <div className="flex items-center gap-2 text-sm text-gray-300 mb-1">
        <span className={`inline-block px-1.5 py-0.5 text-[11px] font-semibold rounded border ${typeBadgeClass}`}>
          {guest.type.toUpperCase()}
        </span>
        <span className="text-gray-600">{'\u00B7'}</span>
        <AppNameCell guest={guest} />
      </div>
      {/* Row 3: version + last checked */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="font-mono truncate max-w-[200px]">{versionStr || '\u2014'}</span>
        <span>{formatRelativeTime(guest.last_checked)}</span>
      </div>
    </div>
  );
}

/** Default export for backward compatibility */
export default function GuestRow({ guest }: GuestRowProps) {
  return <GuestTableRow guest={guest} />;
}
