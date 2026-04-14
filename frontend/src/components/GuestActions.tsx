import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import type { Guest, TaskRecord } from '../types';
import { SUPPORTED_OS_TYPES } from '../types';
import { guestAction, refreshGuest, osUpdateGuest, appUpdateGuest, backupGuest, fetchTask } from '../api/client';

async function pollTask(
  taskId: string,
  onUpdate?: (r: TaskRecord) => void,
): Promise<TaskRecord> {
  const MAX_MS = 10 * 60 * 1000;
  const INTERVAL_MS = 5_000;
  const deadline = Date.now() + MAX_MS;
  let lastRecord: TaskRecord | null = null;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, INTERVAL_MS));
    const record = await fetchTask(taskId);
    lastRecord = record;
    onUpdate?.(record);
    if (record.status === 'success' || record.status === 'failed') return record;
  }
  // Timed out — return last known record with status 'running' so the UI
  // shows a neutral state rather than a failure (the task may still succeed).
  if (lastRecord) return { ...lastRecord, status: 'running' };
  throw new Error('Update timed out after 10 minutes');
}

type ActionKey = 'start' | 'stop' | 'shutdown' | 'restart' | 'snapshot' | 'refresh' | 'os_update' | 'app_update' | 'backup';

interface Props {
  guest: Guest;
  onActionComplete?: () => void;
  backupEnabled?: boolean;
}

export default function GuestActions({ guest, onActionComplete, backupEnabled = false }: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<ActionKey | null>(null);
  const [confirm, setConfirm] = useState<ActionKey | null>(null);
  const [snapshotName, setSnapshotName] = useState('');
  const [result, setResult] = useState<{ ok: boolean | null; msg: string } | null>(null);
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
        setResult(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const canOsUpdate = guest.type === 'lxc' && guest.status === 'running' && (SUPPORTED_OS_TYPES as readonly string[]).includes(guest.os_type ?? '');
  const running = guest.status === 'running';

  const execute = async (action: ActionKey, snapName?: string) => {
    setPending(action);
    setConfirm(null);
    setResult(null);
    try {
      if (action === 'refresh') {
        await refreshGuest(guest.id);
        setResult({ ok: true, msg: 'Refresh started' });
        onActionComplete?.();
      } else if (action === 'os_update') {
        const { task_id } = await osUpdateGuest(guest.id);
        setResult({ ok: true, msg: 'Update running...' });
        const record = await pollTask(task_id);
        if (record.status === 'running') {
          setResult({ ok: null, msg: 'Task is still running — check the Tasks panel for results' });
        } else {
          setResult({
            ok: record.status === 'success',
            msg: record.status === 'success' ? 'Update complete' : (record.detail ?? 'Update failed'),
          });
          setTimeout(() => onActionComplete?.(), 2000);
        }
      } else if (action === 'app_update') {
        const { task_id } = await appUpdateGuest(guest.id);
        setResult({ ok: true, msg: 'Update running...' });
        const record = await pollTask(task_id);
        if (record.status === 'running') {
          setResult({ ok: null, msg: 'Task is still running — check the Tasks panel for results' });
        } else {
          setResult({
            ok: record.status === 'success',
            msg: record.status === 'success' ? 'App update complete' : (record.detail ?? 'App update failed'),
          });
          setTimeout(() => onActionComplete?.(), 2000);
        }
      } else if (action === 'backup') {
        await backupGuest(guest.id);
        setResult({ ok: true, msg: 'Task queued: backup' });
        onActionComplete?.();
      } else {
        await guestAction(guest.id, action, snapName || undefined);
        const labels: Record<string, string> = {
          start: 'Task queued: start', stop: 'Task queued: stop', shutdown: 'Task queued: shutdown',
          restart: 'Task queued: restart', snapshot: 'Task queued: snapshot',
        };
        setResult({ ok: true, msg: labels[action] ?? 'Done' });
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
            <div className={`px-3 py-2 text-xs ${result.ok === null ? 'text-amber-400' : result.ok ? 'text-green-400' : 'text-red-400'}`}>
              {result.msg}
            </div>
          ) : pending === 'os_update' || pending === 'app_update' ? (
            <div className="px-3 py-2 text-xs text-cyan-400">
              {pending === 'app_update' ? 'Updating app... (this may take several minutes)' : 'Updating OS... (this may take several minutes)'}
            </div>
          ) : confirm === 'stop' || confirm === 'shutdown' ? (
            <ConfirmDialog
              message={confirm === 'stop' ? 'Hard stop the guest?' : 'Gracefully shut down?'}
              confirmLabel="Confirm"
              confirmColor="bg-red-700 hover:bg-red-600"
              onConfirm={() => execute(confirm)}
              onCancel={() => setConfirm(null)}
            />
          ) : confirm === 'os_update' ? (
            <ConfirmDialog
              message={<>Update all system packages in <span className="text-white">{guest.name}</span>? Running services may restart.</>}
              confirmLabel="Update"
              confirmColor="bg-cyan-700 hover:bg-cyan-600"
              onConfirm={() => execute('os_update')}
              onCancel={() => setConfirm(null)}
            />
          ) : confirm === 'app_update' ? (
            <ConfirmDialog
              message={<>Run community-script updater in <span className="text-white">{guest.name}</span>?</>}
              confirmLabel="Update"
              confirmColor="bg-teal-700 hover:bg-teal-600"
              onConfirm={() => execute('app_update')}
              onCancel={() => setConfirm(null)}
            />
          ) : confirm === 'backup' ? (
            <ConfirmDialog
              message={<>Create a vzdump backup of <span className="text-white">{guest.name}</span>?</>}
              confirmLabel="Backup"
              confirmColor="bg-indigo-700 hover:bg-indigo-600"
              onConfirm={() => execute('backup')}
              onCancel={() => setConfirm(null)}
            />
          ) : confirm === 'snapshot' ? (
            <ConfirmDialog
              message=""
              confirmLabel="Create"
              confirmColor="bg-blue-700 hover:bg-blue-600"
              onConfirm={() => execute('snapshot', snapshotName)}
              onCancel={() => setConfirm(null)}
            >
              <p className="text-xs text-gray-400 mb-1">Snapshot name (optional)</p>
              <input
                type="text"
                value={snapshotName}
                onChange={(e) => setSnapshotName(e.target.value)}
                placeholder="auto"
                className="w-full px-2 py-1 text-xs bg-gray-800 border border-gray-600 rounded text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 mb-2"
                autoFocus
              />
            </ConfirmDialog>
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
              {canOsUpdate && (
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
              {backupEnabled && (
                <>
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
            </>
          )}
        </div>,
        document.body
      )}
    </div>
  );
}

function ConfirmDialog({ message, confirmLabel, confirmColor, onConfirm, onCancel, children }: {
  message: React.ReactNode; confirmLabel: string; confirmColor: string; onConfirm: () => void; onCancel: () => void; children?: React.ReactNode;
}) {
  return (
    <div className="px-3 py-2">
      {children ?? <p className="text-xs text-gray-300 mb-2">{message}</p>}
      <div className="flex gap-2">
        <button onClick={onConfirm} className={`px-2 py-1 text-xs rounded ${confirmColor} text-white`}>
          {confirmLabel}
        </button>
        <button onClick={onCancel} className="px-2 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300">
          Cancel
        </button>
      </div>
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
