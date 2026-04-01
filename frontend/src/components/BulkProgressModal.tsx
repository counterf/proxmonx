import { useEffect, useRef, useState } from 'react';
import type { GuestSummary, TaskRecord } from '../types';
import { osUpdateGuest, appUpdateGuest, fetchTask } from '../api/client';

async function pollTask(
  taskId: string,
  onUpdate?: (r: TaskRecord) => void,
): Promise<TaskRecord> {
  const MAX_MS = 10 * 60 * 1000;
  const INTERVAL_MS = 5_000;
  const deadline = Date.now() + MAX_MS;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));
    const record = await fetchTask(taskId);
    onUpdate?.(record);
    if (record.status === 'success' || record.status === 'failed') return record;
  }
  throw new Error('Update timed out after 10 minutes');
}

type OpStatus = 'queued' | 'running' | 'done' | 'failed' | 'skipped';

interface GuestOp {
  guest: GuestSummary;
  status: OpStatus;
  error?: string;
}

interface Props {
  action: 'os_update' | 'app_update';
  guests: GuestSummary[];  // all selected; modal determines eligibility
  onClose: () => void;
}

function isEligible(guest: GuestSummary, action: 'os_update' | 'app_update'): boolean {
  if (guest.type !== 'lxc' || guest.status !== 'running') return false;
  if (action === 'app_update' && guest.has_community_script !== true) return false;
  return true;
}

export default function BulkProgressModal({ action, guests, onClose }: Props) {
  const batchId = useRef(crypto.randomUUID());
  const [ops, setOps] = useState<GuestOp[]>(() =>
    guests.map(g => ({ guest: g, status: isEligible(g, action) ? 'queued' : 'skipped' }))
  );
  const [allDone, setAllDone] = useState(false);

  const doneCount = ops.filter(o => o.status === 'done').length;
  const failedCount = ops.filter(o => o.status === 'failed').length;
  const totalEligible = ops.filter(o => o.status !== 'skipped').length;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (let i = 0; i < ops.length; i++) {
        if (cancelled) break;
        const op = ops[i];
        if (op.status === 'skipped') continue;
        setOps(prev => prev.map((o, idx) => idx === i ? { ...o, status: 'running' } : o));
        try {
          const { task_id } = action === 'os_update'
            ? await osUpdateGuest(op.guest.id, batchId.current)
            : await appUpdateGuest(op.guest.id, batchId.current);
          const record = await pollTask(task_id);
          if (!cancelled) setOps(prev => prev.map((o, idx) =>
            idx === i ? { ...o, status: record.status === 'success' ? 'done' : 'failed', error: record.status !== 'success' ? (record.detail ?? 'Failed') : undefined } : o
          ));
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Failed';
          if (!cancelled) setOps(prev => prev.map((o, idx) => idx === i ? { ...o, status: 'failed', error: msg } : o));
        }
      }
      if (!cancelled) setAllDone(true);
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Close on background click only after all done
  const handleOverlayClick = () => { if (allDone) onClose(); };

  // Escape key: only after done
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape' && allDone) onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [allDone, onClose]);

  const title = action === 'os_update' ? 'Bulk OS Update' : 'Bulk App Update';

  return (
    <div
      className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
      onClick={handleOverlayClick}
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
            disabled={!allDone}
            className="text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Guest list */}
        <div className="overflow-y-auto flex-1 divide-y divide-gray-800">
          {ops.map((op) => (
            <div key={op.guest.id} className="flex items-center justify-between px-4 py-2.5">
              <span className="text-sm text-gray-200 truncate mr-4">{op.guest.name}</span>
              <span className="text-xs shrink-0">
                {op.status === 'queued' && <span className="text-gray-500">waiting...</span>}
                {op.status === 'running' && (
                  <span className="text-cyan-400 flex items-center gap-1">
                    <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    running...
                  </span>
                )}
                {op.status === 'done' && <span className="text-green-400">done</span>}
                {op.status === 'failed' && (
                  <span className="text-red-400" title={op.error}>
                    {(op.error || 'failed').slice(0, 60)}{(op.error || '').length > 60 ? '...' : ''}
                  </span>
                )}
                {op.status === 'skipped' && <span className="text-gray-500">-- skipped</span>}
              </span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-700 shrink-0">
          <span className="text-xs text-gray-400">
            {doneCount} done
            {failedCount > 0 && <span className="text-red-400"> · {failedCount} failed</span>}
            <span className="text-gray-600"> / {totalEligible}</span>
          </span>
          <button
            onClick={onClose}
            disabled={!allDone}
            className="px-3 py-1.5 text-sm rounded bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
