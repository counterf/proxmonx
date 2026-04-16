import { useState, useMemo, useCallback, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useGuests } from '../hooks/useGuests';
import { fetchFullSettings } from '../api/client';
import type { UpdateStatus, GuestType, Guest } from '../types';
import FilterBar from './FilterBar';
import { GuestTableRow, GuestCard } from './GuestRow';
import LoadingSpinner from './LoadingSpinner';
import ErrorBanner from './ErrorBanner';
import ColumnToggle from './ColumnToggle';
import BulkActionBar from './BulkActionBar';
import BulkProgressModal from './BulkProgressModal';
import { useColumnVisibility, COLUMN_DEFS, type ColumnKey } from '../hooks/useColumnVisibility';

type SortColumn = ColumnKey;
type SortDirection = 'asc' | 'desc';

const VALID_STATUSES: readonly string[] = ['up-to-date', 'outdated', 'unknown', 'all'];
const VALID_TYPES: readonly string[] = ['lxc', 'vm', 'all'];
const VALID_SORT_COLUMNS: readonly string[] = ['name', 'type', 'host_label', 'app_name', 'installed_version', 'latest_version', 'update_status', 'disk', 'version_detection_method', 'os_type', 'pending_updates', 'last_checked'];
const VALID_SORT_DIRS: readonly string[] = ['asc', 'desc'];

export function compareSemver(a: string, b: string): number {
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

export function diskPercent(g: Guest): number | null {
  if (g.disk_used == null || g.disk_total == null || g.disk_total === 0) return null;
  return g.disk_used / g.disk_total;
}

export function compareGuests(a: Guest, b: Guest, col: SortColumn, dir: SortDirection): number {
  if (col === 'pending_updates') {
    const pa = a.pending_updates ?? -1;
    const pb = b.pending_updates ?? -1;
    const cmp = pa - pb;
    return dir === 'desc' ? -cmp : cmp;
  }

  if (col === 'disk') {
    const da = diskPercent(a);
    const db = diskPercent(b);
    if (da == null && db == null) return 0;
    if (da == null) return 1;
    if (db == null) return -1;
    const cmp = da - db;
    return dir === 'desc' ? -cmp : cmp;
  }

  const getVal = (g: Guest): string | null => {
    switch (col) {
      case 'name': return g.name;
      case 'type': return g.type;
      case 'app_name': return g.app_name;
      case 'installed_version': return g.installed_version;
      case 'latest_version': return g.latest_version;
      case 'update_status': return g.update_status;
      case 'last_checked': return g.last_checked;
      case 'host_label': return g.host_label;
      case 'version_detection_method': return g.version_detection_method;
      case 'os_type': return g.os_type;
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

export default function Dashboard({ configured }: { configured: boolean }) {
  const { guests, loading, error, refreshing, isDiscovering, lastRefreshed, refresh } = useGuests();
  const [searchParams, setSearchParams] = useSearchParams();

  const search = useMemo(() => searchParams.get('q') || '', [searchParams]);
  const statusFilter = useMemo<UpdateStatus | 'all'>(() => {
    const raw = searchParams.get('status');
    return VALID_STATUSES.includes(raw ?? '') ? raw as UpdateStatus | 'all' : 'all';
  }, [searchParams]);
  const typeFilter = useMemo<GuestType | 'all'>(() => {
    const raw = searchParams.get('type');
    return VALID_TYPES.includes(raw ?? '') ? raw as GuestType | 'all' : 'all';
  }, [searchParams]);
  const hostFilter = useMemo(() => searchParams.get('host') || 'all', [searchParams]);

  const sortColumn = useMemo<SortColumn | null>(() => {
    const raw = searchParams.get('sort');
    return raw && VALID_SORT_COLUMNS.includes(raw) ? raw as SortColumn : null;
  }, [searchParams]);
  const sortDirection = useMemo<SortDirection>(() => {
    const raw = searchParams.get('dir');
    return raw && VALID_SORT_DIRS.includes(raw) ? raw as SortDirection : 'asc';
  }, [searchParams]);

  const [bulkMode, setBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pendingBulkAction, setPendingBulkAction] = useState<'os_update' | 'app_update' | null>(null);
  const [showBulkConfirm, setShowBulkConfirm] = useState<'os_update' | 'app_update' | null>(null);
  const [backupEnabledHosts, setBackupEnabledHosts] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchFullSettings()
      .then((s) => {
        const hosts = new Set(
          s.proxmox_hosts.filter((h) => !!h.backup_storage).map((h) => h.id),
        );
        setBackupEnabledHosts(hosts);
      })
      .catch(() => { /* backup button won't appear — acceptable degradation */ });
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && bulkMode && !pendingBulkAction) {
        setBulkMode(false);
        setSelectedIds(new Set());
        setShowBulkConfirm(null);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [bulkMode, pendingBulkAction]);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

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
    updateFilter('q', value);
  };
  const handleStatusChange = (value: UpdateStatus | 'all') => {
    updateFilter('status', value);
  };
  const handleTypeChange = (value: GuestType | 'all') => {
    updateFilter('type', value);
  };
  const handleHostChange = (value: string) => {
    updateFilter('host', value);
  };

  const handleSort = useCallback((col: SortColumn) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (sortColumn === col) {
        if (sortDirection === 'asc') {
          params.set('sort', col);
          params.set('dir', 'desc');
        } else {
          // Third click: clear sort
          params.delete('sort');
          params.delete('dir');
        }
      } else {
        params.set('sort', col);
        params.set('dir', 'asc');
      }
      return params;
    }, { replace: true });
  }, [sortColumn, sortDirection, setSearchParams]);

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

  const hasMultipleHosts = uniqueHosts.size > 1 || (uniqueHosts.size === 1 && !uniqueHosts.has('default'));

  const { visibleColumns, toggleColumn, resetToDefaults } = useColumnVisibility();

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

  const activeColumns = useMemo(() => {
    const cols = COLUMN_DEFS.filter((c) => {
      if (!visibleColumns.has(c.key)) return false;
      if (c.key === 'host_label' && !hasMultipleHosts) return false;
      return true;
    });
    const actionsWeight = 1.2;
    const totalWeight = cols.reduce((sum, c) => sum + c.weight, 0) + actionsWeight;
    return {
      cols: cols.map((c) => ({
        key: c.key as SortColumn,
        label: c.label,
        width: `${((c.weight / totalWeight) * 100).toFixed(1)}%`,
      })),
      actionsWidth: `${((actionsWeight / totalWeight) * 100).toFixed(1)}%`,
    };
  }, [visibleColumns, hasMultipleHosts]);

  if (loading) {
    return <LoadingSpinner text="Loading guests..." />;
  }

  return (
    <div className="space-y-4">
      {!configured && (
        <div className="flex items-start gap-3 p-4 rounded bg-amber-900/30 border border-amber-800 text-amber-300">
          <svg className="w-5 h-5 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          <div>
            <p className="text-sm font-medium">No Proxmox hosts configured</p>
            <p className="text-xs text-amber-400/80 mt-0.5">
              Go to <strong>Settings → Connection</strong> and add at least one Proxmox host to start monitoring your guests.
            </p>
            <Link
              to="/settings"
              className="inline-block mt-2 px-3 py-1 text-xs rounded bg-amber-800/60 hover:bg-amber-800 text-amber-200 border border-amber-700"
            >
              Open Settings
            </Link>
          </div>
        </div>
      )}

      {error && <ErrorBanner key={error} message={error} onRetry={refresh} />}

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
            aria-label={isDiscovering ? 'Discovering...' : refreshing ? 'Refreshing...' : 'Refresh'}
            className="inline-flex items-center gap-1.5 px-3 py-2.5 sm:py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white transition-colors"
          >
            {refreshing && (
              <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {isDiscovering ? 'Discovering...' : refreshing ? 'Refreshing...' : 'Refresh'}
          </button>

          <ColumnToggle visibleColumns={visibleColumns} onToggle={toggleColumn} onReset={resetToDefaults} />

          <button
            type="button"
            onClick={() => { setBulkMode(p => !p); setSelectedIds(new Set()); setShowBulkConfirm(null); }}
            className="px-3 py-1.5 text-sm rounded bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200"
          >
            {bulkMode ? 'Done' : 'Select'}
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

      {bulkMode && selectedIds.size > 0 && (() => {
        const visibleSelected = sorted.filter(g => selectedIds.has(g.id)).length;
        const hiddenSelected = selectedIds.size - visibleSelected;
        return hiddenSelected > 0 ? (
          <p className="text-xs text-gray-500">
            {selectedIds.size} selected ({hiddenSelected} not visible in current filter)
          </p>
        ) : null;
      })()}

      {showBulkConfirm && (
        <div className="p-3 rounded bg-gray-800 border border-gray-700 flex items-center gap-3 flex-wrap">
          <span className="text-sm text-gray-300">
            {showBulkConfirm === 'os_update'
              ? `Update OS on ${selectedIds.size} guests? Running services may restart.`
              : `Run app updater on ${selectedIds.size} guests?`}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => { setPendingBulkAction(showBulkConfirm); setShowBulkConfirm(null); }}
              className="px-3 py-1 text-xs rounded bg-cyan-700 hover:bg-cyan-600 text-white"
            >
              Confirm
            </button>
            <button
              type="button"
              onClick={() => setShowBulkConfirm(null)}
              className="px-3 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

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
                  {bulkMode && (
                    <th scope="col" style={{ width: '36px' }} className="px-2 py-2">
                      <input
                        type="checkbox"
                        aria-label="Select all visible guests"
                        checked={sorted.length > 0 && sorted.every(g => selectedIds.has(g.id))}
                        ref={(el) => {
                          if (el) el.indeterminate =
                            sorted.some(g => selectedIds.has(g.id)) &&
                            !sorted.every(g => selectedIds.has(g.id));
                        }}
                        onChange={() => {
                          if (sorted.every(g => selectedIds.has(g.id))) {
                            // Deselect only currently visible guests; preserve selections outside current filter
                            setSelectedIds(prev => {
                              const next = new Set(prev);
                              sorted.forEach(g => next.delete(g.id));
                              return next;
                            });
                          } else {
                            // Add all visible guests to existing selection
                            setSelectedIds(prev => new Set([...prev, ...sorted.map(g => g.id)]));
                          }
                        }}
                        className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 cursor-pointer"
                      />
                    </th>
                  )}
                  {activeColumns.cols.map((col) => (
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
                  <th scope="col" className="px-3 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider" style={{ width: activeColumns.actionsWidth }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((guest) => (
                  <GuestTableRow
                    key={guest.id}
                    guest={guest}
                    visibleColumns={visibleColumns}
                    bulkMode={bulkMode}
                    selected={selectedIds.has(guest.id)}
                    onToggleSelect={toggleSelect}
                    backupEnabled={backupEnabledHosts.has(guest.host_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card list (< md) */}
          <div className="md:hidden" data-testid="guest-card-list">
            {sorted.map((guest) => (
              <GuestCard
                key={guest.id}
                guest={guest}
                bulkMode={bulkMode}
                selected={selectedIds.has(guest.id)}
                onToggleSelect={toggleSelect}
                backupEnabled={backupEnabledHosts.has(guest.host_id)}
              />
            ))}
          </div>
        </>
      )}
      {bulkMode && selectedIds.size > 0 && !pendingBulkAction && (
        <BulkActionBar
          selectionSize={selectedIds.size}
          selectedGuests={guests.filter(g => selectedIds.has(g.id))}
          onOsUpdate={() => setShowBulkConfirm('os_update')}
          onAppUpdate={() => setShowBulkConfirm('app_update')}
          onClear={() => setSelectedIds(new Set())}
        />
      )}
      {pendingBulkAction && (
        <BulkProgressModal
          action={pendingBulkAction}
          guests={guests.filter(g => selectedIds.has(g.id))}
          onClose={() => {
            setPendingBulkAction(null);
            setBulkMode(false);
            setSelectedIds(new Set());
            setTimeout(() => refresh(), 4000);
          }}
        />
      )}
    </div>
  );
}
