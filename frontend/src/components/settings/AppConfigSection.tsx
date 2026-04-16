import { useState } from 'react';
import type { AppConfigEntry, AppConfigDefault } from '../../types';
import { EyeIcon, EyeSlashIcon } from '../icons/EyeIcons';
import SshFieldGroup from '../shared/SshFieldGroup';

interface AppConfigSectionProps {
  appConfigs: Record<string, AppConfigEntry>;
  onChange: (configs: Record<string, AppConfigEntry>) => void;
  changedKeys: React.MutableRefObject<Set<string>>;
  defaults: AppConfigDefault[];
  disabled?: boolean;
}

type AppField = 'port' | 'api_key' | 'scheme' | 'github_repo' | 'ssh_version_cmd' | 'ssh_username' | 'ssh_key' | 'ssh_password';

export default function AppConfigSection({
  appConfigs,
  onChange,
  changedKeys,
  defaults,
  disabled = false,
}: AppConfigSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const [showApiKey, setShowApiKey] = useState<Record<string, boolean>>({});
  const [showSshPassword, setShowSshPassword] = useState<Record<string, boolean>>({});
  const [sshExpanded, setSshExpanded] = useState<Record<string, boolean>>({});

  const updateApp = (name: string, field: AppField, value: string) => {
    const current = appConfigs[name] || {};
    const updated = { ...current };

    if (field === 'port') {
      const num = parseInt(value, 10);
      updated.port = value === '' || isNaN(num) ? null : num;
    } else if (field === 'scheme') {
      updated.scheme = value || null;
    } else if (field === 'github_repo') {
      updated.github_repo = value;
    } else if (field === 'api_key') {
      updated.api_key = value;
      changedKeys.current.add(name);
    } else if (field === 'ssh_version_cmd') {
      updated.ssh_version_cmd = value;
    } else if (field === 'ssh_username') {
      updated.ssh_username = value;
    } else if (field === 'ssh_key') {
      updated.ssh_key = value;
      changedKeys.current.add(name);
    } else if (field === 'ssh_password') {
      updated.ssh_password = value;
      changedKeys.current.add(name);
    }

    onChange({ ...appConfigs, [name]: updated });
  };

  const toggleVisibility = (name: string) => {
    setShowApiKey((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const toggleSshPasswordVisibility = (name: string) => {
    setShowSshPassword((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const toggleSshExpanded = (name: string) => {
    setSshExpanded((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  if (defaults.length === 0) return null;

  const sshSection = (app: AppConfigDefault, prefix: string) => {
    const cfg = appConfigs[app.name] || {};
    const isExpanded = sshExpanded[app.name] ?? false;
    return (
      <div className="mt-2">
        <button
          type="button"
          onClick={() => toggleSshExpanded(app.name)}
          className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
          aria-expanded={isExpanded}
          aria-controls={`${prefix}-ssh-panel-${app.name}`}
        >
          <span>{isExpanded ? '\u25BC' : '\u25B6'}</span>
          <span>SSH</span>
        </button>
        {isExpanded && (
          <div id={`${prefix}-ssh-panel-${app.name}`}>
            <SshFieldGroup
              idPrefix={`${prefix}-${app.name}`}
              versionCmd={cfg.ssh_version_cmd ?? ''}
              username={cfg.ssh_username ?? ''}
              sshKey={cfg.ssh_key ?? ''}
              password={cfg.ssh_password ?? ''}
              showPassword={showSshPassword[app.name] ?? false}
              onVersionCmdChange={(v) => updateApp(app.name, 'ssh_version_cmd', v)}
              onUsernameChange={(v) => updateApp(app.name, 'ssh_username', v)}
              onSshKeyChange={(v) => updateApp(app.name, 'ssh_key', v)}
              onPasswordChange={(v) => updateApp(app.name, 'ssh_password', v)}
              onToggleShowPassword={() => toggleSshPasswordVisibility(app.name)}
              ariaContext={`for ${app.display_name}`}
              disabled={disabled}
            />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls="app-config-panel"
        className="w-full flex items-center justify-between text-left"
      >
        <div>
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider">
            App Configuration
          </h2>
          <p className="text-xs text-gray-600 mt-0.5">
            Per-app port and API key overrides (optional)
          </p>
        </div>
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform duration-150 ${
            expanded ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div
          id="app-config-panel"
          className={`mt-3 ${disabled ? 'opacity-50' : ''}`}
          aria-busy={disabled}
        >
          {/* Desktop table */}
          <div className="hidden sm:block">
            <table className="w-full" aria-label="Per-app configuration overrides">
              <thead>
                <tr className="text-xs text-gray-500 uppercase border-b border-gray-800">
                  <th scope="col" className="text-left py-2 w-[15%]">App</th>
                  <th scope="col" className="text-left py-2 w-[10%]">Scheme</th>
                  <th scope="col" className="text-left py-2 w-[15%]">Port override</th>
                  <th scope="col" className="text-left py-2 w-[25%]">GitHub Repo</th>
                  <th scope="col" className="text-left py-2 w-[35%]">API Key</th>
                </tr>
              </thead>
              <tbody>
                {defaults.map((app, idx) => {
                  const cfg = appConfigs[app.name] || {};
                  return (
                    <tr
                      key={app.name}
                      className={
                        idx < defaults.length - 1
                          ? 'border-b border-gray-800/50'
                          : ''
                      }
                    >
                      <td className="py-2 text-sm text-gray-300 align-top">{app.display_name}</td>
                      <td className="py-2 pr-3 align-top">
                        <select
                          id={`app-scheme-${app.name}`}
                          value={cfg.scheme || 'http'}
                          onChange={(e) => updateApp(app.name, 'scheme', e.target.value)}
                          disabled={disabled}
                          aria-label={`Scheme for ${app.display_name}`}
                          className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                        >
                          <option value="http">HTTP</option>
                          <option value="https">HTTPS</option>
                        </select>
                      </td>
                      <td className="py-2 pr-3 align-top">
                        <input
                          id={`app-port-${app.name}`}
                          type="number"
                          min={1}
                          max={65535}
                          value={cfg.port ?? ''}
                          placeholder={String(app.default_port)}
                          onChange={(e) => updateApp(app.name, 'port', e.target.value)}
                          disabled={disabled}
                          aria-label={`Port override for ${app.display_name}`}
                          className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                      </td>
                      <td className="py-2 pr-3 align-top">
                        <div>
                          <input
                            id={`app-github-repo-${app.name}`}
                            type="text"
                            value={cfg.github_repo ?? ''}
                            placeholder={app.github_repo || 'owner/repo'}
                            onChange={(e) => updateApp(app.name, 'github_repo', e.target.value)}
                            disabled={disabled}
                            aria-label={`GitHub repo for ${app.display_name}`}
                            className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                          />
                          {app.github_repo && (
                            <p className="text-xs text-gray-600 mt-0.5">Default: {app.github_repo}</p>
                          )}
                        </div>
                      </td>
                      <td className="py-2 align-top">
                        {app.accepts_api_key ? (
                          <div className="relative">
                            <input
                              id={`app-apikey-${app.name}`}
                              type={showApiKey[app.name] ? 'text' : 'password'}
                              value={cfg.api_key ?? ''}
                              placeholder="API key (optional)"
                              onChange={(e) => updateApp(app.name, 'api_key', e.target.value)}
                              disabled={disabled}
                              aria-label={`API key for ${app.display_name}`}
                              className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-10"
                            />
                            <button
                              type="button"
                              onClick={() => toggleVisibility(app.name)}
                              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                              aria-label={
                                showApiKey[app.name]
                                  ? `Hide API key for ${app.display_name}`
                                  : `Show API key for ${app.display_name}`
                              }
                            >
                              {showApiKey[app.name] ? <EyeSlashIcon /> : <EyeIcon />}
                            </button>
                          </div>
                        ) : (
                          <span
                            className="text-gray-600 text-sm"
                            aria-label={`No API key for ${app.display_name}`}
                          >
                            ---
                          </span>
                        )}
                        {sshSection(app, 'dt')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile card layout */}
          <div className="sm:hidden space-y-2">
            {defaults.map((app) => {
              const cfg = appConfigs[app.name] || {};
              return (
                <div
                  key={app.name}
                  className="bg-gray-800/40 rounded p-3"
                >
                  <p className="text-sm text-gray-300 font-medium mb-2">{app.display_name}</p>
                  <div className="space-y-2">
                    <div>
                      <label htmlFor={`m-app-scheme-${app.name}`} className="text-xs text-gray-500">
                        Scheme
                      </label>
                      <select
                        id={`m-app-scheme-${app.name}`}
                        value={cfg.scheme || 'http'}
                        onChange={(e) => updateApp(app.name, 'scheme', e.target.value)}
                        disabled={disabled}
                        aria-label={`Scheme for ${app.display_name}`}
                        className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                      >
                        <option value="http">HTTP</option>
                        <option value="https">HTTPS</option>
                      </select>
                    </div>
                    <div>
                      <label htmlFor={`m-app-port-${app.name}`} className="text-xs text-gray-500">
                        Port
                      </label>
                      <input
                        id={`m-app-port-${app.name}`}
                        type="number"
                        min={1}
                        max={65535}
                        value={cfg.port ?? ''}
                        placeholder={String(app.default_port)}
                        onChange={(e) => updateApp(app.name, 'port', e.target.value)}
                        disabled={disabled}
                        aria-label={`Port override for ${app.display_name}`}
                        className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label htmlFor={`m-app-github-repo-${app.name}`} className="text-xs text-gray-500">
                        GitHub Repo
                      </label>
                      <input
                        id={`m-app-github-repo-${app.name}`}
                        type="text"
                        value={cfg.github_repo ?? ''}
                        placeholder={app.github_repo || 'owner/repo'}
                        onChange={(e) => updateApp(app.name, 'github_repo', e.target.value)}
                        disabled={disabled}
                        aria-label={`GitHub repo for ${app.display_name}`}
                        className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                      {app.github_repo && (
                        <p className="text-xs text-gray-600 mt-0.5">Default: {app.github_repo}</p>
                      )}
                    </div>
                    {app.accepts_api_key && (
                      <div>
                        <label htmlFor={`m-app-apikey-${app.name}`} className="text-xs text-gray-500">
                          API Key
                        </label>
                        <div className="relative">
                          <input
                            id={`m-app-apikey-${app.name}`}
                            type={showApiKey[app.name] ? 'text' : 'password'}
                            value={cfg.api_key ?? ''}
                            placeholder="API key (optional)"
                            onChange={(e) => updateApp(app.name, 'api_key', e.target.value)}
                            disabled={disabled}
                            aria-label={`API key for ${app.display_name}`}
                            className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-10"
                          />
                          <button
                            type="button"
                            onClick={() => toggleVisibility(app.name)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                            aria-label={
                              showApiKey[app.name]
                                ? `Hide API key for ${app.display_name}`
                                : `Show API key for ${app.display_name}`
                            }
                          >
                            {showApiKey[app.name] ? <EyeSlashIcon /> : <EyeIcon />}
                          </button>
                        </div>
                      </div>
                    )}
                    {sshSection(app, 'm')}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
