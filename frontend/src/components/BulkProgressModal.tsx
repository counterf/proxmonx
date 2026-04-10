import { useEffect, useRef, useState, useCallback } from 'react';
import type { Guest, BulkJob } from '../types';
import { startBulkJob, fetchBulkJob } from '../api/client';

interface Props {
  action: 'os_update' | 'app_update';
  guests: Guest[];  // all selected; modal determines eligibility
  onClose: () => void;
}

// Must match backend OS_UPDATE_COMMANDS keys in ssh.py
const SUPPORTED_OS_TYPES = [
  'alpine', 'debian', 'ubuntu', 'devuan', 'fedora', 'centos', 'archlinux', 'opensuse',
];

export function isEligible(guest: Guest, action: 'os_update' | 'app_update'): boolean {
  if (guest.type !== 'lxc' || guest.status !== 'running') return false;
  if (action === 'os_update') {
    if (!guest.os_type || !SUPPORTED_OS_TYPES.includes(guest.os_type)) return false;
  }
  if (action === 'app_update' && guest.has_community_script !== true) return false;
  return true;
}

export default function BulkProgressModal({ action, guests, onClose }: Props) {
  const [job, setJob] = useState<BulkJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const eligibleGuests = guests.filter(g => isEligible(g, action));
  const skippedGuests = guests.filter(g => !isEligible(g, action));

  // Start the bulk job on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (eligibleGuests.length === 0) return;
      try {
        const { job_id } = await startBulkJob(action, eligibleGuests.map(g => g.id));
        if (cancelled) return;
        jobIdRef.current = job_id;
        // Fetch initial state
        const initial = await fetchBulkJob(job_id);
        if (!cancelled) setJob(initial);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to start bulk job');
      }
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll for job status
  useEffect(() => {
    if (!jobIdRef.current) return;
    if (job && (job.status === 'completed' || job.status === 'failed')) return;

    pollingRef.current = setInterval(async () => {
      if (!jobIdRef.current) return;
      try {
        const updated = await fetchBulkJob(jobIdRef.current);
        setJob(updated);
        if (updated.status === 'completed' || updated.status === 'failed') {
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      } catch {
        // ignore polling errors
      }
    }, 5000);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Escape key always closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const getGuestStatus = useCallback((guestId: string): string => {
    if (!job) return 'pending';
    const result = job.results[guestId];
    return result?.status ?? 'pending';
  }, [job]);

  const getGuestError = useCallback((guestId: string): string | null => {
    if (!job) return null;
    const result = job.results[guestId];
    return result?.error ?? null;
  }, [job]);

  const isDone = job?.status === 'completed' || job?.status === 'failed';
  const failedCount = job ? job.failed : 0;
  const skippedCount = job ? job.skipped : 0;
  const completedCount = job ? job.completed : 0;
  const successCount = completedCount - failedCount - skippedCount;
  const totalEligible = eligibleGuests.length;

  const title = action === 'os_update' ? 'Bulk OS Update' : 'Bulk App Update';

  return (
    <div
      className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-lg flex flex-col max-h-[70vh]"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-modal-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
          <h2 id="bulk-modal-title" className="text-sm font-semibold text-gray-100">
            {title} — {guests.length} guest{guests.length !== 1 ? 's' : ''}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="px-4 py-2 text-sm text-red-400 bg-red-900/20">{error}</div>
        )}

        {/* Guest list */}
        <div className="overflow-y-auto flex-1 divide-y divide-gray-800">
          {eligibleGuests.map((guest) => {
            const status = getGuestStatus(guest.id);
            const guestError = getGuestError(guest.id);
            return (
              <div key={guest.id} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-sm text-gray-200 truncate mr-4">{guest.name}</span>
                <span className="text-xs shrink-0">
                  {status === 'pending' && <span className="text-gray-500">waiting...</span>}
                  {status === 'running' && (
                    <span className="text-cyan-400 flex items-center gap-1">
                      <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      running...
                    </span>
                  )}
                  {status === 'success' && <span className="text-green-400">done</span>}
                  {status === 'failed' && (
                    <span className="text-red-400" title={guestError ?? undefined}>
                      {(guestError || 'failed').slice(0, 60)}{(guestError || '').length > 60 ? '...' : ''}
                    </span>
                  )}
                  {status === 'skipped' && (
                    <span className="text-gray-500" title={guestError ?? undefined}>-- skipped</span>
                  )}
                </span>
              </div>
            );
          })}
          {skippedGuests.map((guest) => (
            <div key={guest.id} className="flex items-center justify-between px-4 py-2.5">
              <span className="text-sm text-gray-200 truncate mr-4">{guest.name}</span>
              <span className="text-xs shrink-0 text-gray-500">-- skipped</span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-700 shrink-0">
          <span className="text-xs text-gray-400">
            {successCount} done
            {failedCount > 0 && <span className="text-red-400"> · {failedCount} failed</span>}
            {skippedCount > 0 && <span className="text-gray-500"> · {skippedCount} skipped</span>}
            <span className="text-gray-600"> / {totalEligible}</span>
          </span>
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
          >
            {isDone ? 'Done' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  );
}
