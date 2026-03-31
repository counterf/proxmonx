import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { GuestSummary } from '../types';
import { guestAction, refreshGuest, osUpdateGuest, appUpdateGuest, backupGuest } from '../api/client';

type ActionKey = 'start' | 'stop' | 'shutdown' | 'restart' | 'snapshot' | 'refresh' | 'os_update' | 'app_update' | 'backup';

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
  const [dropdownPos, setDropdownPos] = useState<{ top?: number; bottom?: number; right: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const portalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        ref.current && !ref.current.contains(e.target as Node) &&
        portalRef.current && !portalRef.current.contains(e.target as Node)
      ) {
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
      if (action === 'refresh') {
        await refreshGuest(guest.id);
      } else if (action === 'os_update') {
        await osUpdateGuest(guest.id);
      } else if (action === 'app_update') {
        await appUpdateGuest(guest.id);
      } else if (action === 'backup') {
        await backupGuest(guest.id);
      } else {
        await guestAction(guest.id, action, snapName || undefined);
      }
      const labels: Record<ActionKey, string> = {
        start: 'Task queued: start', stop: 'Task queued: stop', shutdown: 'Task queued: shutdown',
        restart: 'Task queued: restart', snapshot: 'Task queued: snapshot',
        refresh: 'Refresh started', os_update: 'Update complete', app_update: 'App update ran — check output', backup: 'Task queued: backup',
      };
      setResult({ ok: true, msg: labels[action] });
      if (action === 'os_update' || action === 'app_update') {
        // Delay re-fetch to give the backend refresh pipeline time to complete
        setTimeout(() => onActionComplete?.(), 4000);
      } else {
        onActionComplete?.();
      }
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : 'Action failed' });
    } finally {
      setPending(null);
      // os_update is long-running — keep result visible until user dismisses manually
      if (action !== 'os_update' && action !== 'app_update') {
        setTimeout(() => { setOpen(false); setResult(null); setSnapshotName(''); }, 2500);
      }
    }
  };

  const handleAction = (action: ActionKey) => {
    if (action === 'stop' || action === 'shutdown' || action === 'os_update' || action === 'app_update' || action === 'backup') {
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
        ref={buttonRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (!open && buttonRef.current) {
            const rect = buttonRef.current.getBoundingClientRect();
            const spaceBelow = window.innerHeight - rect.bottom;
            if (spaceBelow < 220) {
              setDropdownPos({ bottom: window.innerHeight - rect.top + 4, right: window.innerWidth - rect.right });
            } else {
              setDropdownPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
            }
          }
          setOpen(p => !p);
          setConfirm(null);
          setResult(null);
        }}
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

      {open && dropdownPos && createPortal(
        <div
          ref={portalRef}
          style={{ position: 'fixed', top: dropdownPos.top, bottom: dropdownPos.bottom, right: dropdownPos.right, zIndex: 9999, maxHeight: '80vh', overflowY: 'auto' }}
          className="w-44 rounded bg-gray-900 border border-gray-700 shadow-lg py-1"
          onClick={(e) => e.stopPropagation()}
        >
          {result ? (
            <div className={`px-3 py-2 text-xs ${result.ok ? 'text-green-400' : 'text-red-400'}`}>
              {result.msg}
            </div>
          ) : pending === 'os_update' || pending === 'app_update' ? (
            <div className="px-3 py-2 text-xs text-cyan-400">
              {pending === 'app_update' ? 'Updating app... (this may take several minutes)' : 'Updating OS... (this may take several minutes)'}
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
          ) : confirm === 'os_update' ? (
            <div className="px-3 py-2">
              <p className="text-xs text-gray-300 mb-2">
                Update all system packages in <span className="text-white">{guest.name}</span>? Running services may restart.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => execute('os_update')}
                  className="px-2 py-1 text-xs rounded bg-cyan-700 hover:bg-cyan-600 text-white"
                >
                  Update
                </button>
                <button
                  onClick={() => setConfirm(null)}
                  className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : confirm === 'app_update' ? (
            <div className="px-3 py-2">
              <p className="text-xs text-gray-300 mb-2">
                Run community-script updater in <span className="text-white">{guest.name}</span>?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => execute('app_update')}
                  className="px-2 py-1 text-xs rounded bg-teal-700 hover:bg-teal-600 text-white"
                >
                  Update
                </button>
                <button
                  onClick={() => setConfirm(null)}
                  className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : confirm === 'backup' ? (
            <div className="px-3 py-2">
              <p className="text-xs text-gray-300 mb-2">
                Create a vzdump backup of <span className="text-white">{guest.name}</span>?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => execute('backup')}
                  className="px-2 py-1 text-xs rounded bg-indigo-700 hover:bg-indigo-600 text-white"
                >
                  Backup
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
                <ActionItem label="Start" icon="▶" color="text-green-400" onClick={() => handleAction('start')} loading={pending === 'start'} />
              )}
              {running && (
                <>
                  <ActionItem label="Restart" icon="↺" color="text-blue-400" onClick={() => handleAction('restart')} loading={pending === 'restart'} />
                  <ActionItem label="Shutdown" icon="⏻" color="text-amber-400" onClick={() => handleAction('shutdown')} loading={pending === 'shutdown'} />
                  <ActionItem label="Stop" icon="■" color="text-red-400" onClick={() => handleAction('stop')} loading={pending === 'stop'} />
                </>
              )}
              <div className="border-t border-gray-700 my-1" />
              <ActionItem label="Snapshot" icon="📷" color="text-gray-300" onClick={() => handleAction('snapshot')} loading={pending === 'snapshot'} />
              <ActionItem label="Refresh info" icon="↻" color="text-gray-300" onClick={() => execute('refresh')} loading={pending === 'refresh'} />
              {guest.type === 'lxc' && guest.status === 'running' && (
                <>
                  <div className="border-t border-gray-700 my-1" />
                  <ActionItem
                    label={guest.pending_updates != null && guest.pending_updates > 0 ? `Update OS (${guest.pending_updates})` : 'Update OS'}
                    icon="↑"
                    color="text-cyan-400"
                    onClick={() => handleAction('os_update')}
                    loading={false}
                  />
                  {guest.has_community_script === true && (
                    <ActionItem
                      label="Update App"
                      icon="⬆"
                      color="text-teal-400"
                      onClick={() => handleAction('app_update')}
                      loading={false}
                    />
                  )}
                </>
              )}
              <div className="border-t border-gray-700 my-1" />
              <ActionItem
                label="Backup"
                icon="▣"
                color="text-indigo-400"
                onClick={() => handleAction('backup')}
                loading={false}
              />
            </>
          )}
        </div>,
        document.body
      )}
    </div>
  );
}

function ActionItem({ label, icon, color, onClick, loading, disabled }: {
  label: string; icon: string; color: string; onClick: () => void; loading: boolean; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading || !!disabled}
      className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-800 disabled:opacity-50 ${color}`}
    >
      <span className="w-3 text-center">{icon}</span>
      {label}
    </button>
  );
}
