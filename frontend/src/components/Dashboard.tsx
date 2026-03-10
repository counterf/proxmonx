import { useState, useMemo, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useGuests } from '../hooks/useGuests';
import type { UpdateStatus, GuestType, GuestSummary } from '../types';
import FilterBar from './FilterBar';
import { GuestTableRow, GuestCard } from './GuestRow';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';

type SortColumn = 'name' | 'type' | 'app_name' | 'installed_version' | 'latest_version' | 'update_status' | 'last_checked' | 'host_label';
type SortDirection = 'asc' | 'desc';

function compareSemver(a: string, b: string): number {
  const pa = a.replace(/^v/i, '').split('.').map(Number);
  const pb = b.replace(/^v/i, '').split('.').map(Number);
  if (pa.some(isNaN) || pb.some(isNaN)) {
    return a.localeCompare(b);
  }
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function compareGuests(a: GuestSummary, b: GuestSummary, col: SortColumn, dir: SortDirection): number {
  const getVal = (g: GuestSummary): string | null => {
    switch (col) {
      case 'name': return g.name;
      case 'type': return g.type;
      case 'app_name': return g.app_name;
      case 'installed_version': return g.installed_version;
      case 'latest_version': return g.latest_version;
      case 'update_status': return g.update_status;
      case 'last_checked': return g.last_checked;
      case 'host_label': return g.host_label;
      default: return null;
    }
  };

  const va = getVal(a);
  const vb = getVal(b);

  // Null/empty sort last regardless of direction
  const aEmpty = !va;
  const bEmpty = !vb;
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;

  let cmp: number;
  if (col === 'last_checked') {
    cmp = new Date(va!).getTime() - new Date(vb!).getTime();
  } else if (col === 'installed_version' || col === 'latest_version') {
    cmp = compareSemver(va!, vb!);
  } else {
    cmp = va!.localeCompare(vb!);
  }

  return dir === 'desc' ? -cmp : cmp;
}

function SortIcon({ active, direction }: { active: boolean; direction: SortDirection }) {
  if (!active) return null;
  return (
    <svg className="w-3 h-3 ml-1 inline-block" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      {direction === 'asc' ? (
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
      ) : (
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
      )}
    </svg>
  );
}

export default function Dashboard() {
  const { guests, loading, error, refreshing, lastRefreshed, refresh } = useGuests();
  const [searchParams, setSearchParams] = useSearchParams();

  const [search, setSearch] = useState(searchParams.get('q') || '');
  const [statusFilter, setStatusFilter] = useState<UpdateStatus | 'all'>(
    (searchParams.get('status') as UpdateStatus | 'all') || 'all'
  );
  const [typeFilter, setTypeFilter] = useState<GuestType | 'all'>(
    (searchParams.get('type') as GuestType | 'all') || 'all'
  );
  const [hostFilter, setHostFilter] = useState<string>(
    searchParams.get('host') || 'all'
  );

  const initSort = searchParams.get('sort') as SortColumn | null;
  const initDir = searchParams.get('dir') as SortDirection | null;
  const [sortColumn, setSortColumn] = useState<SortColumn | null>(initSort);
  const [sortDirection, setSortDirection] = useState<SortDirection>(initDir || 'asc');

  // Sync filters to URL
  const updateFilter = useCallback((key: string, value: string) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (value && value !== 'all' && value !== '') {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      return params;
    }, { replace: true });
  }, [setSearchParams]);

  const handleSearchChange = (value: string) => {
    setSearch(value);
    updateFilter('q', value);
  };
  const handleStatusChange = (value: UpdateStatus | 'all') => {
    setStatusFilter(value);
    updateFilter('status', value);
  };
  const handleTypeChange = (value: GuestType | 'all') => {
    setTypeFilter(value);
    updateFilter('type', value);
  };
  const handleHostChange = (value: string) => {
    setHostFilter(value);
    updateFilter('host', value);
  };

  const handleSort = useCallback((col: SortColumn) => {
    if (sortColumn === col) {
      if (sortDirection === 'asc') {
        setSortDirection('desc');
        updateFilter('dir', 'desc');
      } else {
        // Third click: clear sort
        setSortColumn(null);
        setSortDirection('asc');
        updateFilter('sort', '');
        updateFilter('dir', '');
        return;
      }
    } else {
      setSortColumn(col);
      setSortDirection('asc');
      updateFilter('sort', col);
      updateFilter('dir', 'asc');
      return;
    }
    updateFilter('sort', col);
  }, [sortColumn, sortDirection, updateFilter]);

  // Unique host IDs for filter dropdown
  const uniqueHosts = useMemo(() => {
    const map = new Map<string, string>();
    for (const g of guests) {
      if (!map.has(g.host_id)) {
        map.set(g.host_id, g.host_label || g.host_id);
      }
    }
    return map;
  }, [guests]);

  const showHostCol = uniqueHosts.size > 1 || (uniqueHosts.size === 1 && !uniqueHosts.has('default'));

  const filtered = useMemo(() => {
    return guests.filter((g) => {
      if (statusFilter !== 'all' && g.update_status !== statusFilter) return false;
      if (typeFilter !== 'all' && g.type !== typeFilter) return false;
      if (hostFilter !== 'all' && g.host_id !== hostFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        const nameMatch = g.name.toLowerCase().includes(q);
        const appMatch = g.app_name?.toLowerCase().includes(q) || false;
        if (!nameMatch && !appMatch) return false;
      }
      return true;
    });
  }, [guests, statusFilter, typeFilter, hostFilter, search]);

  const sorted = useMemo(() => {
    if (!sortColumn) return filtered;
    return [...filtered].sort((a, b) => compareGuests(a, b, sortColumn, sortDirection));
  }, [filtered, sortColumn, sortDirection]);

  const outdatedCount = guests.filter((g) => g.update_status === 'outdated').length;
  const unknownCount = guests.filter((g) => g.update_status === 'unknown').length;

  if (loading) {
    return <LoadingSpinner text="Loading guests..." />;
  }

  const sortableColumns: { key: SortColumn; label: string; width: string }[] = [
    { key: 'name', label: 'Guest Name', width: showHostCol ? '18%' : '20%' },
    { key: 'type', label: 'Type', width: '6%' },
    ...(showHostCol ? [{ key: 'host_label' as SortColumn, label: 'Host', width: '10%' }] : []),
    { key: 'app_name', label: 'App', width: showHostCol ? '14%' : '16%' },
    { key: 'installed_version', label: 'Installed', width: '12%' },
    { key: 'latest_version', label: 'Latest', width: '12%' },
    { key: 'update_status', label: 'Status', width: '10%' },
    { key: 'last_checked', label: 'Last Checked', width: showHostCol ? '10%' : '14%' },
  ];

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} onRetry={refresh} />}

      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="text-sm text-gray-500">
          Last refreshed:{' '}
          {lastRefreshed ? lastRefreshed.toLocaleString() : '\u2014'}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={refresh}
            disabled={refreshing}
            aria-disabled={refreshing}
            aria-label={refreshing ? 'Refreshing...' : 'Refresh'}
            className="inline-flex items-center gap-1.5 px-3 py-2.5 sm:py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
          >
            {refreshing && (
              <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>

          {/* Health badges */}
          {outdatedCount > 0 && (
            <span className="px-2 py-0.5 text-xs font-semibold rounded bg-red-900 text-red-400">
              {outdatedCount} outdated
            </span>
          )}
          {unknownCount > 0 && (
            <span className="px-2 py-0.5 text-xs font-semibold rounded bg-gray-800 text-gray-400">
              {unknownCount} unknown
            </span>
          )}
          {outdatedCount === 0 && unknownCount === 0 && guests.length > 0 && (
            <span className="px-2 py-0.5 text-xs font-semibold rounded bg-green-900 text-green-500">
              All OK
            </span>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <FilterBar
        search={search}
        onSearchChange={handleSearchChange}
        statusFilter={statusFilter}
        onStatusChange={handleStatusChange}
        typeFilter={typeFilter}
        onTypeChange={handleTypeChange}
        resultCount={sorted.length}
        totalCount={guests.length}
        hosts={uniqueHosts.size > 1 ? uniqueHosts : undefined}
        hostFilter={hostFilter}
        onHostChange={handleHostChange}
      />

      {/* Guest list */}
      {guests.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg font-medium mb-2">No guests found.</p>
          <p className="text-sm mb-4">
            proxmon has not discovered any Proxmox guests yet.
            <br />
            Check your Proxmox connection in Settings, then click Refresh.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Link to="/settings" className="px-3 py-1.5 text-sm rounded bg-gray-800 hover:bg-gray-700 text-gray-300">
              Go to Settings
            </Link>
            <button onClick={refresh} className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 text-white">
              Refresh
            </button>
          </div>
        </div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="mb-2">No guests match your filters.</p>
          <button
            onClick={() => {
              handleSearchChange('');
              handleStatusChange('all');
              handleTypeChange('all');
              handleHostChange('all');
            }}
            className="text-sm text-blue-400 hover:text-blue-300"
          >
            Clear all filters
          </button>
        </div>
      ) : (
        <>
          {/* Desktop table (>= md) */}
          <div className="hidden md:block overflow-x-auto rounded border border-gray-800">
            <table className="w-full text-left">
              <caption className="sr-only">Proxmox guests</caption>
              <thead className="bg-surface border-b border-gray-800">
                <tr>
                  {sortableColumns.map((col) => (
                    <th
                      key={col.key}
                      scope="col"
                      className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider cursor-pointer select-none hover:text-gray-200 transition-colors"
                      style={{ width: col.width }}
                      onClick={() => handleSort(col.key)}
                      aria-sort={sortColumn === col.key ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {col.label}
                      <SortIcon active={sortColumn === col.key} direction={sortDirection} />
                    </th>
                  ))}
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '8%' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((guest) => (
                  <GuestTableRow key={guest.id} guest={guest} showHostCol={showHostCol} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card list (< md) */}
          <div className="md:hidden" data-testid="guest-card-list">
            {sorted.map((guest) => (
              <GuestCard key={guest.id} guest={guest} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
