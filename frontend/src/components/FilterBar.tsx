import type { UpdateStatus, GuestType } from '../types';

interface FilterBarProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: UpdateStatus | 'all';
  onStatusChange: (value: UpdateStatus | 'all') => void;
  typeFilter: GuestType | 'all';
  onTypeChange: (value: GuestType | 'all') => void;
  resultCount: number;
  totalCount: number;
  hosts?: Map<string, string>;
  hostFilter?: string;
  onHostChange?: (value: string) => void;
}

export default function FilterBar({
  search,
  onSearchChange,
  statusFilter,
  onStatusChange,
  typeFilter,
  onTypeChange,
  resultCount,
  totalCount,
  hosts,
  hostFilter = 'all',
  onHostChange,
}: FilterBarProps) {
  const hasActiveFilters = search !== '' || statusFilter !== 'all' || typeFilter !== 'all' || hostFilter !== 'all';

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search apps or guests..."
          aria-label="Filter guests"
          className="w-full sm:w-auto sm:flex-1 sm:min-w-[200px] px-3 py-1.5 text-sm rounded bg-gray-800 border border-gray-700 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
        <select
          value={statusFilter}
          onChange={(e) => onStatusChange(e.target.value as UpdateStatus | 'all')}
          aria-label="Filter by status"
          className="flex-1 sm:flex-none px-3 py-1.5 text-sm rounded bg-gray-800 border border-gray-700 text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="all">All statuses</option>
          <option value="outdated">Outdated</option>
          <option value="up-to-date">Up to date</option>
          <option value="unknown">Unknown</option>
        </select>
        <select
          value={typeFilter}
          onChange={(e) => onTypeChange(e.target.value as GuestType | 'all')}
          aria-label="Filter by type"
          className="flex-1 sm:flex-none px-3 py-1.5 text-sm rounded bg-gray-800 border border-gray-700 text-gray-200 focus:outline-none focus:border-blue-500"
        >
          <option value="all">All types</option>
          <option value="lxc">LXC</option>
          <option value="vm">VM</option>
        </select>
        {hosts && hosts.size > 1 && onHostChange && (
          <select
            value={hostFilter}
            onChange={(e) => onHostChange(e.target.value)}
            aria-label="Filter by host"
            className="flex-1 sm:flex-none px-3 py-1.5 text-sm rounded bg-gray-800 border border-gray-700 text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value="all">All hosts</option>
            {Array.from(hosts.entries()).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        )}
      </div>

      {hasActiveFilters && (
        <div className="flex items-center gap-2 flex-wrap" aria-live="polite">
          <span className="text-xs text-gray-500">
            Showing {resultCount} of {totalCount} guests
          </span>
          {search && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-gray-800 text-gray-300">
              Search: {search}
              <button onClick={() => onSearchChange('')} className="text-gray-500 hover:text-white" aria-label="Clear search">x</button>
            </span>
          )}
          {statusFilter !== 'all' && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-gray-800 text-gray-300">
              Status: {statusFilter}
              <button onClick={() => onStatusChange('all')} className="text-gray-500 hover:text-white" aria-label="Clear status filter">x</button>
            </span>
          )}
          {typeFilter !== 'all' && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-gray-800 text-gray-300">
              Type: {typeFilter}
              <button onClick={() => onTypeChange('all')} className="text-gray-500 hover:text-white" aria-label="Clear type filter">x</button>
            </span>
          )}
          {hostFilter !== 'all' && onHostChange && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-gray-800 text-gray-300">
              Host: {hosts?.get(hostFilter) || hostFilter}
              <button onClick={() => onHostChange('all')} className="text-gray-500 hover:text-white" aria-label="Clear host filter">x</button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
