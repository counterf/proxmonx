import { useState, useRef, useEffect } from 'react';
import type { GuestSummary } from '../types';
import { guestAction } from '../api/client';

type ActionKey = 'start' | 'stop' | 'shutdown' | 'restart' | 'snapshot';

interface Props {
  guest: GuestSummary;
  onActionComplete?: () => void;
}

export default function GuestActions({ guest, onActionComplete }: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ActionKey | null>(null);
  const [confirm, setConfirm] = useState<ActionKey | null>(null);
  const [snapshotName, setSnapshotName] = useState('');
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setConfirm(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const running = guest.status === 'running';

  const execute = async (action: ActionKey, snapName?: string) => {
    setPending(action);
    setConfirm(null);
    setResult(null);
    try {
      await guestAction(guest.id, action, snapName || undefined);
      const labels: Record<ActionKey, string> = {
        start: 'Started', stop: 'Stopped', shutdown: 'Shutdown triggered',
        restart: 'Restarting', snapshot: 'Snapshot created',
      };
      setResult({ ok: true, msg: labels[action] });
      onActionComplete?.();
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : 'Action failed' });
    } finally {
      setPending(null);
      setTimeout(() => { setOpen(false); setResult(null); setSnapshotName(''); }, 2500);
    }
  };

  const handleAction = (action: ActionKey) => {
    if (action === 'stop' || action === 'shutdown') {
      setConfirm(action);
    } else if (action === 'snapshot') {
      setConfirm('snapshot');
    } else {
      execute(action);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen(p => !p); setConfirm(null); setResult(null); }}
        disabled={pending !== null}
        className="px-2 py-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded disabled:opacity-50"
        aria-label="Guest actions"
        title="Actions"
      >
        {pending ? (
          <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
          </svg>
        ) : (
          <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
            <path d="M10 6a2 2 0 110-4 2 2 0 010 4zm0 6a2 2 0 110-4 2 2 0 010 4zm0 6a2 2 0 110-4 2 2 0 010 4z"/>
          </svg>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 mt-1 w-44 rounded bg-gray-900 border border-gray-700 shadow-lg z-50 py-1"
          onClick={(e) => e.stopPropagation()}
        >
          {result ? (
            <div className={`px-3 py-2 text-xs ${result.ok ? 'text-green-400' : 'text-red-400'}`}>
              {result.msg}
            </div>
          ) : confirm === 'stop' || confirm === 'shutdown' ? (
            <div className="px-3 py-2">
              <p className="text-xs text-gray-300 mb-2">
                {confirm === 'stop' ? 'Hard stop the guest?' : 'Gracefully shut down?'}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => execute(confirm)}
                  className="px-2 py-1 text-xs rounded bg-red-700 hover:bg-red-600 text-white"
                >
                  Confirm
                </button>
                <button
                  onClick={() => setConfirm(null)}
                  className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : confirm === 'snapshot' ? (
            <div className="px-3 py-2">
              <p className="text-xs text-gray-400 mb-1">Snapshot name (optional)</p>
              <input
                type="text"
                value={snapshotName}
                onChange={(e) => setSnapshotName(e.target.value)}
                placeholder="auto"
                className="w-full px-2 py-1 text-xs bg-gray-800 border border-gray-600 rounded text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 mb-2"
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  onClick={() => execute('snapshot', snapshotName)}
                  className="px-2 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white"
                >
                  Create
                </button>
                <button
                  onClick={() => setConfirm(null)}
                  className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              {!running && (
                <ActionItem label="Start" icon="&#9654;" color="text-green-400" onClick={() => handleAction('start')} loading={pending === 'start'} />
              )}
              {running && (
                <>
                  <ActionItem label="Restart" icon="&#8634;" color="text-blue-400" onClick={() => handleAction('restart')} loading={pending === 'restart'} />
                  <ActionItem label="Shutdown" icon="&#9211;" color="text-amber-400" onClick={() => handleAction('shutdown')} loading={pending === 'shutdown'} />
                  <ActionItem label="Stop" icon="&#9632;" color="text-red-400" onClick={() => handleAction('stop')} loading={pending === 'stop'} />
                </>
              )}
              <div className="border-t border-gray-700 my-1" />
              <ActionItem label="Snapshot" icon="&#128247;" color="text-gray-300" onClick={() => handleAction('snapshot')} loading={pending === 'snapshot'} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ActionItem({ label, icon, color, onClick, loading }: {
  label: string; icon: string; color: string; onClick: () => void; loading: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-800 disabled:opacity-50 ${color}`}
    >
      <span className="w-3 text-center" dangerouslySetInnerHTML={{ __html: icon }} />
      {label}
    </button>
  );
}
