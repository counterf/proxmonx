import { useState, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useGuests } from '../hooks/useGuests';
import type { UpdateStatus, GuestType } from '../types';
import FilterBar from './FilterBar';
import { GuestTableRow, GuestCard } from './GuestRow';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';

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

  // Sync filters to URL
  const updateFilter = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams);
    if (value && value !== 'all' && value !== '') {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    setSearchParams(params, { replace: true });
  };

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

  const filtered = useMemo(() => {
    return guests.filter((g) => {
      if (statusFilter !== 'all' && g.update_status !== statusFilter) return false;
      if (typeFilter !== 'all' && g.type !== typeFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        const nameMatch = g.name.toLowerCase().includes(q);
        const appMatch = g.app_name?.toLowerCase().includes(q) || false;
        if (!nameMatch && !appMatch) return false;
      }
      return true;
    });
  }, [guests, statusFilter, typeFilter, search]);

  const outdatedCount = guests.filter((g) => g.update_status === 'outdated').length;
  const unknownCount = guests.filter((g) => g.update_status === 'unknown').length;

  if (loading) {
    return <LoadingSpinner text="Loading guests..." />;
  }

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
        resultCount={filtered.length}
        totalCount={guests.length}
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
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p className="mb-2">No guests match your filters.</p>
          <button
            onClick={() => {
              handleSearchChange('');
              handleStatusChange('all');
              handleTypeChange('all');
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
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '20%' }}>Guest Name</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '6%' }}>Type</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '16%' }}>App</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '12%' }}>Installed</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '12%' }}>Latest</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '10%' }}>Status</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '14%' }}>Last Checked</th>
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: '10%' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((guest) => (
                  <GuestTableRow key={guest.id} guest={guest} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card list (< md) */}
          <div className="md:hidden" data-testid="guest-card-list">
            {filtered.map((guest) => (
              <GuestCard key={guest.id} guest={guest} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
