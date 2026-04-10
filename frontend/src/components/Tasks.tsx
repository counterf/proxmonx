import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { TaskRecord, BulkJob } from '../types';
import { fetchTasks, fetchBulkJobs, clearTasks } from '../api/client';

// --- Formatting helpers ---

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  return `${Math.floor(diffHrs / 24)}d ago`;
}

function formatDuration(started: string, finished: string | null): string {
  if (!finished) return 'in progress\u2026';
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  return remSec > 0 ? `${min}m ${remSec}s` : `${min}m`;
}

// --- Badge components ---

const ACTION_STYLES: Record<string, { label: string; bg: string; text: string }> = {
  start:     { label: 'Start',     bg: 'bg-green-900/40',  text: 'text-green-300' },
  stop:      { label: 'Stop',      bg: 'bg-red-900/40',    text: 'text-red-300' },
  shutdown:  { label: 'Shutdown',  bg: 'bg-orange-900/40', text: 'text-orange-300' },
  restart:   { label: 'Restart',   bg: 'bg-yellow-900/40', text: 'text-yellow-300' },
  snapshot:  { label: 'Snapshot',  bg: 'bg-purple-900/40', text: 'text-purple-300' },
  os_update:  { label: 'OS Update',  bg: 'bg-cyan-900/40',  text: 'text-cyan-300' },
  app_update: { label: 'App Update', bg: 'bg-teal-900/40',  text: 'text-teal-300' },
  backup:     { label: 'Backup',     bg: 'bg-indigo-900/40', text: 'text-indigo-300' },
};

function ActionBadge({ action }: { action: string }) {
  const s = ACTION_STYLES[action] ?? { label: action, bg: 'bg-gray-800', text: 'text-gray-300' };
  return (
    <span className={`inline-block px-1.5 py-0.5 text-[11px] font-medium rounded ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  );
}

const STATUS_STYLES: Record<string, { label: string; bg: string; text: string; pulse?: boolean }> = {
  pending: { label: 'Pending', bg: 'bg-yellow-900/40', text: 'text-yellow-300', pulse: true },
  running: { label: 'Running', bg: 'bg-blue-900/40',   text: 'text-blue-300',   pulse: true },
  success: { label: 'Success', bg: 'bg-green-900/40',  text: 'text-green-300' },
  failed:  { label: 'Failed',  bg: 'bg-red-900/40',    text: 'text-red-400' },
  skipped: { label: 'Skipped', bg: 'bg-gray-800/40',   text: 'text-gray-400' },
  partial: { label: 'Partial', bg: 'bg-amber-900/40',  text: 'text-amber-300' },
};

function StatusBadge({ status }: { status: TaskRecord['status'] }) {
  const s = STATUS_STYLES[status] ?? { label: status, bg: 'bg-gray-800', text: 'text-gray-300' };
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-medium rounded ${s.bg} ${s.text}`}>
      {s.pulse && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {s.label}
    </span>
  );
}

// --- Info cell: shows error inline for failures, UPID for running, output toggle for os_update success ---

function InfoCell({ task }: { task: TaskRecord }) {
  const [expanded, setExpanded] = useState(false);

  // Running: show UPID
  if (task.status === 'running' && task.detail) {
    return (
      <span className="text-[10px] font-mono text-gray-600 break-all" title="Proxmox task ID">
        {task.detail}
      </span>
    );
  }

  // Success or failed with output: unified summary + toggle
  if ((task.status === 'success' || task.status === 'failed') && task.output) {
    return (
      <div>
        <button
          onClick={() => setExpanded(p => !p)}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {expanded ? 'Hide output' : 'View output'}
        </button>
        {expanded && (
          <pre className="text-xs text-gray-400 whitespace-pre-wrap mt-2 max-h-64 overflow-y-auto bg-gray-900 p-2 rounded border border-gray-800">
            {task.output}
          </pre>
        )}
      </div>
    );
  }

  // Failed without output: inline detail only (SSH exception path)
  if (task.status === 'failed' && task.detail) {
    return <p className="text-xs text-red-400 break-words">{task.detail}</p>;
  }

  // Success without output: detail only
  if (task.status === 'success' && task.detail) {
    return <span className="text-xs text-gray-400">{task.detail}</span>;
  }

  return <span className="text-gray-700">{'\u2014'}</span>;
}

// --- Batch group components ---

type TaskGroupBatch = { type: 'batch'; batchId: string; tasks: TaskRecord[]; bulkJob?: BulkJob };

function batchAggregateStatus(tasks: TaskRecord[]): string {
  if (tasks.some(t => t.status === 'running' || t.status === 'pending')) return 'running';
  const failed = tasks.filter(t => t.status === 'failed').length;
  const success = tasks.filter(t => t.status === 'success').length;
  if (failed > 0 && success > 0) return 'partial';
  if (failed > 0) return 'failed';
  if (success > 0) return 'success';
  return 'skipped';
}

function BatchGroupRows({ group }: { group: TaskGroupBatch }) {
  const hasActive = group.tasks.some(t => t.status === 'pending' || t.status === 'running');
  const [expanded, setExpanded] = useState(hasActive);
  const doneCount = group.bulkJob
    ? Math.max(0, group.bulkJob.completed - group.bulkJob.failed - group.bulkJob.skipped)
    : group.tasks.filter(t => t.status === 'success').length;
  const failedCount = group.bulkJob?.failed ?? group.tasks.filter(t => t.status === 'failed').length;
  const action = group.tasks[0]?.action;

  const earliestStart = group.bulkJob?.created_at ?? group.tasks.reduce((a, b) => a.started_at < b.started_at ? a : b).started_at;
  const latestFinish = group.bulkJob?.finished_at ?? (group.tasks.every(t => t.finished_at)
    ? group.tasks.reduce((a, b) => a.finished_at! > b.finished_at! ? a : b).finished_at
    : null);

  return (
    <>
      <tr
        className="border-b border-gray-800 hover:bg-gray-800/30 cursor-pointer select-none"
        onClick={() => setExpanded(p => !p)}
      >
        <td className="px-3 py-2">
          <div className="flex items-center gap-2 text-xs">
            <button
              aria-expanded={expanded}
              aria-label="Toggle bulk job details"
              className="text-gray-500 hover:text-gray-300"
              onClick={e => { e.stopPropagation(); setExpanded(p => !p); }}
            >
              {expanded ? '\u25BC' : '\u25B6'}
            </button>
            <span className="text-gray-400">Bulk Job ({group.tasks.length} guest{group.tasks.length !== 1 ? 's' : ''})</span>
          </div>
        </td>
        <td className="px-3 py-2">
          {action && <ActionBadge action={action} />}
        </td>
        <td className="px-3 py-2">
          <StatusBadge status={batchAggregateStatus(group.tasks) as TaskRecord['status']} />
        </td>
        <td className="px-3 py-2 text-xs text-gray-500" title={earliestStart}>
          {formatRelativeTime(earliestStart)}
        </td>
        <td className="px-3 py-2 text-xs text-gray-500 tabular-nums">
          {formatDuration(earliestStart, latestFinish)}
        </td>
        <td className="px-3 py-2 text-xs">
          {hasActive ? (
            <span className="text-gray-400">{doneCount} / {group.tasks.length}</span>
          ) : (
            <>
              {doneCount > 0 && <span className="text-green-400">{doneCount} done</span>}
              {failedCount > 0 && <span className="text-red-400 ml-1">{doneCount > 0 ? '\u00B7 ' : ''}{failedCount} failed</span>}
            </>
          )}
        </td>
      </tr>
      {expanded && group.tasks.map(task => (
        <tr key={task.id} className="border-b border-gray-800 last:border-0 hover:bg-gray-800/30">
          <td className="pl-8 pr-3 py-2">
            <Link to={`/guest/${encodeURIComponent(task.guest_id)}`} className="text-blue-400 hover:text-blue-300 hover:underline">
              {task.guest_name}
            </Link>
          </td>
          <td className="px-3 py-2"><ActionBadge action={task.action} /></td>
          <td className="px-3 py-2"><StatusBadge status={task.status} /></td>
          <td className="px-3 py-2 text-xs text-gray-500" title={task.started_at}>{formatRelativeTime(task.started_at)}</td>
          <td className="px-3 py-2 text-xs text-gray-500 tabular-nums">{formatDuration(task.started_at, task.finished_at)}</td>
          <td className="px-3 py-2 max-w-xs"><InfoCell task={task} /></td>
        </tr>
      ))}
    </>
  );
}

function BatchGroupCard({ group }: { group: TaskGroupBatch }) {
  const hasActive = group.tasks.some(t => t.status === 'pending' || t.status === 'running');
  const [expanded, setExpanded] = useState(hasActive);
  const doneCount = group.bulkJob
    ? Math.max(0, group.bulkJob.completed - group.bulkJob.failed - group.bulkJob.skipped)
    : group.tasks.filter(t => t.status === 'success').length;
  const failedCount = group.bulkJob?.failed ?? group.tasks.filter(t => t.status === 'failed').length;
  const action = group.tasks[0]?.action;
  const earliestStart = group.bulkJob?.created_at ?? group.tasks.reduce((a, b) => a.started_at < b.started_at ? a : b).started_at;

  return (
    <div className="border border-gray-800 rounded px-4 py-3 cursor-pointer" onClick={() => setExpanded(p => !p)}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium text-gray-300">Bulk Job ({group.tasks.length} guest{group.tasks.length !== 1 ? 's' : ''})</span>
        <span className="text-xs text-gray-500">{expanded ? '\u25BC' : '\u25B6'}</span>
      </div>
      <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
        {action && <ActionBadge action={action} />}
        <StatusBadge status={batchAggregateStatus(group.tasks) as TaskRecord['status']} />
        <span className="text-gray-600">{'\u00B7'}</span>
        <span>{formatRelativeTime(earliestStart)}</span>
        {!hasActive && doneCount > 0 && <span className="text-green-400">{'\u00B7'} {doneCount} done</span>}
        {!hasActive && failedCount > 0 && <span className="text-red-400">{'\u00B7'} {failedCount} failed</span>}
        {hasActive && <span className="text-gray-400">{doneCount} / {group.tasks.length}</span>}
      </div>
      {expanded && (
        <div className="mt-2 space-y-2">
          {group.tasks.map(task => (
            <div key={task.id} className="border border-gray-800 rounded px-3 py-2">
              <div className="flex items-center justify-between mb-1">
                <Link to={`/guest/${encodeURIComponent(task.guest_id)}`} className="text-sm font-medium text-blue-400 hover:text-blue-300">{task.guest_name}</Link>
                <StatusBadge status={task.status} />
              </div>
              <InfoCell task={task} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Types ---

type TaskGroup =
  | { type: 'single'; task: TaskRecord }
  | TaskGroupBatch;

// --- Main component ---

export default function Tasks() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [bulkJobs, setBulkJobs] = useState<BulkJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [tasksResult, bulkJobsResult] = await Promise.allSettled([fetchTasks(), fetchBulkJobs()]);
      if (tasksResult.status === 'fulfilled') setTasks(tasksResult.value);
      else throw tasksResult.reason;
      if (bulkJobsResult.status === 'fulfilled') setBulkJobs(bulkJobsResult.value);
      else setBulkJobs([]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  };

  // Mount: initial load only
  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Reactive polling: re-runs whenever tasks changes; polls only while active tasks exist
  useEffect(() => {
    const hasActive = tasks.some(t => t.status === 'pending' || t.status === 'running');
    if (!hasActive) return;
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [tasks]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const handleClear = async () => {
    if (!confirmClear) { setConfirmClear(true); return; }
    setClearing(true);
    setConfirmClear(false);
    try {
      await clearTasks();
      setTasks([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear tasks');
    } finally {
      setClearing(false);
    }
  };

  const groups = useMemo((): TaskGroup[] => {
    const bulkJobMap = new Map(bulkJobs.map(j => [j.id, j]));
    const batchMap = new Map<string, TaskGroupBatch>();
    const result: TaskGroup[] = [];
    for (const task of tasks) {
      if (!task.batch_id) {
        result.push({ type: 'single', task });
      } else if (batchMap.has(task.batch_id)) {
        batchMap.get(task.batch_id)!.tasks.push(task);
      } else {
        const group: TaskGroupBatch = { type: 'batch', batchId: task.batch_id, tasks: [task], bulkJob: bulkJobMap.get(task.batch_id) };
        batchMap.set(task.batch_id, group);
        result.push(group);
      }
    }
    return result;
  }, [tasks, bulkJobs]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-100">Task History</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50"
            title="Refresh"
          >
            <svg
              className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span className="hidden sm:inline">Refresh</span>
          </button>
          {tasks.length > 0 && (
            <button
              type="button"
              onClick={handleClear}
              disabled={clearing}
              className={`text-xs px-3 py-1.5 rounded disabled:opacity-50 ${
                confirmClear
                  ? 'bg-red-700 hover:bg-red-600 text-white'
                  : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
              }`}
            >
              {clearing ? 'Clearing\u2026' : confirmClear ? 'Click again to confirm' : 'Clear all'}
            </button>
          )}
        </div>
      </div>

      {confirmClear && (
        <button
          type="button"
          onClick={() => setConfirmClear(false)}
          className="text-xs text-gray-500 hover:text-gray-400"
        >
          Cancel
        </button>
      )}

      {error && (
        <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="text-sm text-gray-500">Loading\u2026</div>
      )}

      {!loading && tasks.length === 0 && (
        <div className="p-8 text-center text-gray-600 text-sm border border-gray-800 rounded">
          No task history yet. Actions you trigger (backup, OS update, app update, start/stop/snapshot) will appear here.
        </div>
      )}

      {/* Desktop table */}
      {tasks.length > 0 && (
        <div className="hidden md:block rounded border border-gray-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/50">
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Guest</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Action</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Started</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Duration</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Info</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) =>
                group.type === 'single' ? (
                  <tr key={group.task.id} className="border-b border-gray-800 last:border-0 hover:bg-gray-800/30">
                    <td className="px-3 py-2">
                      <Link
                        to={`/guest/${encodeURIComponent(group.task.guest_id)}`}
                        className="text-blue-400 hover:text-blue-300 hover:underline"
                      >
                        {group.task.guest_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2"><ActionBadge action={group.task.action} /></td>
                    <td className="px-3 py-2"><StatusBadge status={group.task.status} /></td>
                    <td className="px-3 py-2 text-xs text-gray-500" title={group.task.started_at}>
                      {formatRelativeTime(group.task.started_at)}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500 tabular-nums">
                      {formatDuration(group.task.started_at, group.task.finished_at)}
                    </td>
                    <td className="px-3 py-2 max-w-xs"><InfoCell task={group.task} /></td>
                  </tr>
                ) : (
                  <BatchGroupRows key={group.batchId} group={group} />
                )
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Mobile cards */}
      {tasks.length > 0 && (
        <div className="md:hidden space-y-2">
          {groups.map((group) =>
            group.type === 'single' ? (
              <div key={group.task.id} className="border border-gray-800 rounded px-4 py-3">
                <div className="flex items-center justify-between mb-1">
                  <Link
                    to={`/guest/${encodeURIComponent(group.task.guest_id)}`}
                    className="text-sm font-medium text-blue-400 hover:text-blue-300"
                  >
                    {group.task.guest_name}
                  </Link>
                  <StatusBadge status={group.task.status} />
                </div>
                <div className="flex items-center gap-2 mb-1">
                  <ActionBadge action={group.task.action} />
                  <span className="text-xs text-gray-600">{'\u00B7'}</span>
                  <span className="text-xs text-gray-500" title={group.task.started_at}>
                    {formatRelativeTime(group.task.started_at)}
                  </span>
                  <span className="text-xs text-gray-600">{'\u00B7'}</span>
                  <span className="text-xs text-gray-500 tabular-nums">
                    {formatDuration(group.task.started_at, group.task.finished_at)}
                  </span>
                </div>
                <InfoCell task={group.task} />
              </div>
            ) : (
              <BatchGroupCard key={group.batchId} group={group} />
            )
          )}
        </div>
      )}
    </div>
  );
}
