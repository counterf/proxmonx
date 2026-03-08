import { useNavigate } from 'react-router-dom';
import type { GuestSummary } from '../types';
import StatusBadge from './StatusBadge';

interface GuestRowProps {
  guest: GuestSummary;
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

export default function GuestRow({ guest }: GuestRowProps) {
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
        if (e.key === 'Enter') navigate(`/guest/${guest.id}`);
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
      <td className="px-3 py-2 text-sm text-gray-300">
        {guest.app_name || '\u2014'}
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
