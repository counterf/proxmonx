import { useState, useEffect } from 'react';
import type { ProxmoxHost, ConnectionTestResult } from '../../types';
import { testConnection, fetchBackupStorages } from '../../api/client';
import type { BackupStorage } from '../../api/client';
import { EyeIcon, EyeSlashIcon } from '../icons/EyeIcons';

interface ProxmoxHostsSectionProps {
  hosts: ProxmoxHost[];
  onChange: (hosts: ProxmoxHost[]) => void;
  disabled?: boolean;
}

const MAX_HOSTS = 10;

function emptyHost(): ProxmoxHost {
  return {
    id: (crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)),
    label: 'New Host',
    host: '',
    token_id: '',
    token_secret: '',
    node: '',
    ssh_username: 'root',
    ssh_password: null,
    ssh_key: null,
    pct_exec_enabled: false,
    backup_storage: null,
  };
}

const inputClass = 'w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500';

export default function ProxmoxHostsSection({ hosts, onChange, disabled = false }: ProxmoxHostsSectionProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [showSshPass, setShowSshPass] = useState<Record<string, boolean>>({});
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [testResult, setTestResult] = useState<Record<string, ConnectionTestResult>>({});
  const [storages, setStorages] = useState<Record<string, BackupStorage[] | null>>({});
  const [storagesLoading, setStoragesLoading] = useState<Record<string, boolean>>({});
  const [storagesError, setStoragesError] = useState<Record<string, string | null>>({});
  useEffect(() => {
    if (!expandedId) return;
    if (storages[expandedId] !== undefined) return; // already loaded
    const host = hosts.find((h) => h.id === expandedId);
    if (!host || !host.host || !host.token_id || !host.node) return;
    setStoragesLoading((p) => ({ ...p, [expandedId]: true }));
    setStoragesError((p) => ({ ...p, [expandedId]: null }));
    fetchBackupStorages(expandedId).then((result) => {
      if ('error' in result) {
        setStoragesError((p) => ({ ...p, [expandedId]: result.error }));
        setStorages((p) => ({ ...p, [expandedId]: null }));
      } else {
        setStorages((p) => ({ ...p, [expandedId]: result }));
      }
    }).catch((err) => {
      setStoragesError((p) => ({ ...p, [expandedId]: err instanceof Error ? err.message : 'Failed to load storages' }));
      setStorages((p) => ({ ...p, [expandedId]: null }));
    }).finally(() => {
      setStoragesLoading((p) => ({ ...p, [expandedId]: false }));
    });
  }, [expandedId]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateHost = (id: string, patch: Partial<ProxmoxHost>) => {
    // B8: Invalidate cached storages when credential-related fields change
    if ('host' in patch || 'token_id' in patch || 'token_secret' in patch || 'node' in patch) {
      setStorages((p) => { const next = { ...p }; delete next[id]; return next; });
      setStoragesError((p) => { const next = { ...p }; delete next[id]; return next; });
    }
    onChange(hosts.map((h) => (h.id === id ? { ...h, ...patch } : h)));
  };

  const addHost = () => {
    if (hosts.length >= MAX_HOSTS) return;
    const h = emptyHost();
    onChange([...hosts, h]);
    setExpandedId(h.id);
  };

  const removeHost = (id: string) => {
    if (hosts.length <= 1) return;
    const updated = hosts.filter((h) => h.id !== id);
    onChange(updated);
    if (expandedId === id) {
      setExpandedId(updated[0]?.id || null);
    }
  };

  const refreshStorages = (hostId: string) => {
    const host = hosts.find((h) => h.id === hostId);
    if (!host || !host.host || !host.token_id || !host.node) return;
    setStorages((p) => { const next = { ...p }; delete next[hostId]; return next; });
    setStoragesError((p) => { const next = { ...p }; delete next[hostId]; return next; });
    setStoragesLoading((p) => ({ ...p, [hostId]: true }));
    fetchBackupStorages(hostId).then((result) => {
      if ('error' in result) {
        setStoragesError((p) => ({ ...p, [hostId]: result.error }));
        setStorages((p) => ({ ...p, [hostId]: null }));
      } else {
        setStorages((p) => ({ ...p, [hostId]: result }));
      }
    }).catch((err) => {
      setStoragesError((p) => ({ ...p, [hostId]: err instanceof Error ? err.message : 'Failed to load storages' }));
      setStorages((p) => ({ ...p, [hostId]: null }));
    }).finally(() => {
      setStoragesLoading((p) => ({ ...p, [hostId]: false }));
    });
  };

  const handleTest = async (host: ProxmoxHost) => {
    setTesting((prev) => ({ ...prev, [host.id]: true }));
    try {
      const result = await testConnection({
        host: host.host,
        token_id: host.token_id,
        token_secret: host.token_secret || '',
        node: host.node,
        host_id: host.id,
      });
      setTestResult((prev) => ({ ...prev, [host.id]: result }));
    } catch {
      setTestResult((prev) => ({
        ...prev,
        [host.id]: { success: false, message: 'Connection test failed', node_info: null },
      }));
    } finally {
      setTesting((prev) => ({ ...prev, [host.id]: false }));
    }
  };

  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider">Proxmox Hosts</h2>
        <button
          type="button"
          onClick={addHost}
          disabled={disabled || hosts.length >= MAX_HOSTS}
          className="text-xs px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
        >
          + Add Host
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Connect to one or more Proxmox VE hosts. Each host needs an API token with at least PVEAuditor permissions.
      </p>

      <div className="space-y-2">
        {hosts.map((host, idx) => {
          const isExpanded = expandedId === host.id;
          const result = testResult[host.id];
          return (
            <div key={host.id} className="border border-gray-700 rounded">
              {/* Accordion header */}
              <button
                type="button"
                onClick={() => setExpandedId(isExpanded ? null : host.id)}
                className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-800/50"
                aria-expanded={isExpanded}
              >
                <span className="text-sm text-gray-200">
                  {host.label || `Host ${idx + 1}`}
                  {host.host && (
                    <span className="text-gray-500 text-xs ml-2">{host.host}</span>
                  )}
                </span>
                <svg
                  className={`w-4 h-4 text-gray-500 transition-transform duration-150 ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {isExpanded && (
                <div className="px-3 pb-3 space-y-3 border-t border-gray-700 pt-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label htmlFor={`host-label-${host.id}`} className="block text-xs text-gray-400 mb-1">Label</label>
                      <input
                        id={`host-label-${host.id}`}
                        type="text"
                        value={host.label}
                        onChange={(e) => updateHost(host.id, { label: e.target.value })}
                        placeholder="My PVE"
                        disabled={disabled}
                        className={inputClass}
                      />
                      <p className="text-xs text-gray-600 mt-0.5">Friendly name shown in the dashboard</p>
                    </div>
                    <div>
                      <label htmlFor={`host-url-${host.id}`} className="block text-xs text-gray-400 mb-1">
                        Host URL <span className="text-red-400">*</span>
                      </label>
                      <input
                        id={`host-url-${host.id}`}
                        type="text"
                        value={host.host}
                        onChange={(e) => updateHost(host.id, { host: e.target.value })}
                        placeholder="https://192.168.1.10:8006"
                        disabled={disabled}
                        className={inputClass}
                      />
                      <p className="text-xs text-gray-600 mt-0.5">Full URL including port, e.g. https://192.168.1.10:8006</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label htmlFor={`host-tokenid-${host.id}`} className="block text-xs text-gray-400 mb-1">
                        Token ID <span className="text-red-400">*</span>
                      </label>
                      <input
                        id={`host-tokenid-${host.id}`}
                        type="text"
                        value={host.token_id}
                        onChange={(e) => updateHost(host.id, { token_id: e.target.value })}
                        placeholder="root@pam!proxmon"
                        disabled={disabled}
                        className={inputClass}
                      />
                      <p className="text-xs text-gray-600 mt-0.5">API token in user@realm!tokenname format</p>
                    </div>
                    <div>
                      <label htmlFor={`host-secret-${host.id}`} className="block text-xs text-gray-400 mb-1">
                        Token Secret <span className="text-red-400">*</span>
                      </label>
                      <div className="relative">
                        <input
                          id={`host-secret-${host.id}`}
                          type={showSecret[host.id] ? 'text' : 'password'}
                          value={host.token_secret || ''}
                          onChange={(e) => updateHost(host.id, { token_secret: e.target.value })}
                          disabled={disabled}
                          className={`${inputClass} pr-10`}
                        />
                        <button
                          type="button"
                          onClick={() => setShowSecret((p) => ({ ...p, [host.id]: !p[host.id] }))}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                          aria-label={showSecret[host.id] ? 'Hide token secret' : 'Show token secret'}
                        >
                          {showSecret[host.id] ? <EyeSlashIcon /> : <EyeIcon />}
                        </button>
                      </div>
                      <p className="text-xs text-gray-600 mt-0.5">UUID secret generated when creating the API token in Proxmox</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label htmlFor={`host-node-${host.id}`} className="block text-xs text-gray-400 mb-1">
                        Node <span className="text-red-400">*</span>
                      </label>
                      <input
                        id={`host-node-${host.id}`}
                        type="text"
                        value={host.node}
                        onChange={(e) => updateHost(host.id, { node: e.target.value })}
                        placeholder="pve"
                        disabled={disabled}
                        className={inputClass}
                      />
                      <p className="text-xs text-gray-600 mt-0.5">Node name as shown in the Proxmox VE sidebar</p>
                    </div>
                    <div>
                      <label htmlFor={`host-ssh-user-${host.id}`} className="block text-xs text-gray-400 mb-1">SSH Username</label>
                      <input
                        id={`host-ssh-user-${host.id}`}
                        type="text"
                        value={host.ssh_username}
                        onChange={(e) => updateHost(host.id, { ssh_username: e.target.value })}
                        placeholder="root"
                        disabled={disabled}
                        className={inputClass}
                      />
                      <p className="text-xs text-gray-600 mt-0.5">User for SSH/pct exec connections to this Proxmox host</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label htmlFor={`host-ssh-key-${host.id}`} className="block text-xs text-gray-400 mb-1">SSH Private Key</label>
                      <textarea
                        id={`host-ssh-key-${host.id}`}
                        rows={4}
                        value={host.ssh_key || ''}
                        onChange={(e) => updateHost(host.id, { ssh_key: e.target.value || null })}
                        placeholder={'-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----'}
                        disabled={disabled}
                        className={`${inputClass} resize-y font-mono text-xs`}
                      />
                      <p className="text-xs text-gray-600 mt-0.5">Paste your SSH private key (PEM format)</p>
                    </div>
                    <div>
                      <label htmlFor={`host-ssh-pass-${host.id}`} className="block text-xs text-gray-400 mb-1">SSH Password</label>
                      <div className="relative">
                        <input
                          id={`host-ssh-pass-${host.id}`}
                          type={showSshPass[host.id] ? 'text' : 'password'}
                          value={host.ssh_password || ''}
                          onChange={(e) => updateHost(host.id, { ssh_password: e.target.value })}
                          placeholder="leave blank to keep"
                          disabled={disabled}
                          className={`${inputClass} pr-10`}
                        />
                        <button
                          type="button"
                          onClick={() => setShowSshPass((p) => ({ ...p, [host.id]: !p[host.id] }))}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                          aria-label={showSshPass[host.id] ? 'Hide SSH password' : 'Show SSH password'}
                        >
                          {showSshPass[host.id] ? <EyeSlashIcon /> : <EyeIcon />}
                        </button>
                      </div>
                      <p className="text-xs text-gray-600 mt-0.5">Password for SSH authentication to this Proxmox host</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-start gap-2">
                      <input
                        id={`host-pct-${host.id}`}
                        type="checkbox"
                        checked={host.pct_exec_enabled}
                        onChange={(e) => updateHost(host.id, { pct_exec_enabled: e.target.checked })}
                        disabled={disabled}
                        className="accent-blue-500 mt-0.5"
                      />
                      <div>
                        <label htmlFor={`host-pct-${host.id}`} className="text-xs text-gray-400">Enable pct exec</label>
                        <p className="text-xs text-gray-600">Run version commands inside LXC containers via the Proxmox host over SSH</p>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <label htmlFor={`host-backup-storage-${host.id}`} className="block text-xs text-gray-400">Backup Storage</label>
                      {storages[host.id] !== undefined && !storagesLoading[host.id] && (
                        <button
                          type="button"
                          onClick={() => refreshStorages(host.id)}
                          disabled={disabled}
                          className="text-[10px] text-blue-400 hover:text-blue-300 disabled:opacity-50"
                          aria-label="Refresh backup storages"
                        >
                          Refresh
                        </button>
                      )}
                    </div>
                    {storagesLoading[host.id] ? (
                      <select disabled className={`${inputClass} opacity-60`}>
                        <option>Loading storages…</option>
                      </select>
                    ) : storages[host.id] ? (
                      <select
                        id={`host-backup-storage-${host.id}`}
                        value={host.backup_storage || ''}
                        onChange={(e) => updateHost(host.id, { backup_storage: e.target.value || null })}
                        disabled={disabled}
                        className={inputClass}
                      >
                        <option value="">None — disable backup</option>
                        {storages[host.id]!.map((s) => (
                          <option key={s.storage} value={s.storage}>
                            {s.storage} ({s.type}{s.avail != null ? `, ${(s.avail / 1024 / 1024 / 1024).toFixed(1)} GB free` : ''})
                          </option>
                        ))}
                      </select>
                    ) : (
                      <>
                        <input
                          id={`host-backup-storage-${host.id}`}
                          type="text"
                          value={host.backup_storage || ''}
                          onChange={(e) => updateHost(host.id, { backup_storage: e.target.value || null })}
                          placeholder="e.g. local"
                          disabled={disabled}
                          className={inputClass}
                        />
                        {storagesError[host.id] && (
                          <p className="text-xs text-amber-500 mt-0.5">Could not load storages — enter manually. ({storagesError[host.id]})</p>
                        )}
                      </>
                    )}
                    <p className="text-xs text-gray-600 mt-0.5">Proxmox storage for vzdump backups (only backup-capable storages listed)</p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-3 pt-1">
                    <button
                      type="button"
                      onClick={() => handleTest(host)}
                      disabled={disabled || testing[host.id] || !host.host || !host.token_id || !host.node}
                      className="text-xs px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {testing[host.id] ? 'Testing...' : 'Test Connection'}
                    </button>
                    {hosts.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeHost(host.id)}
                        disabled={disabled}
                        className="text-xs px-3 py-1.5 rounded bg-red-900/50 hover:bg-red-900 text-red-400 disabled:opacity-50"
                      >
                        Remove
                      </button>
                    )}
                  </div>

                  {result && (
                    <div className={`text-xs p-2 rounded ${result.success ? 'bg-green-900/30 text-green-400 border border-green-800' : 'bg-red-900/30 text-red-400 border border-red-800'}`}>
                      {result.message}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
