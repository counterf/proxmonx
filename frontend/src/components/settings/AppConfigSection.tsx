import { useState, useEffect } from 'react';
import type { AppConfigEntry, AppConfigDefault } from '../../types';
import { fetchAppConfigDefaults } from '../../api/client';

interface AppConfigSectionProps {
  appConfigs: Record<string, AppConfigEntry>;
  onChange: (configs: Record<string, AppConfigEntry>) => void;
  changedKeys: React.MutableRefObject<Set<string>>;
  disabled?: boolean;
}

export default function AppConfigSection({
  appConfigs,
  onChange,
  changedKeys,
  disabled = false,
}: AppConfigSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const [defaults, setDefaults] = useState<AppConfigDefault[]>([]);
  const [showApiKey, setShowApiKey] = useState<Record<string, boolean>>({});
  const [fetchError, setFetchError] = useState<boolean>(false);

  useEffect(() => {
    fetchAppConfigDefaults()
      .then(setDefaults)
      .catch(() => setFetchError(true));
  }, []);

  const updateApp = (name: string, field: 'port' | 'api_key' | 'scheme', value: string) => {
    const current = appConfigs[name] || {};
    const updated = { ...current };

    if (field === 'port') {
      const num = parseInt(value, 10);
      updated.port = value === '' || isNaN(num) ? null : num;
    } else if (field === 'scheme') {
      updated.scheme = value === 'http' ? null : value;
      changedKeys.current.add(name);
    } else {
      updated.api_key = value;
      changedKeys.current.add(name);
    }

    onChange({ ...appConfigs, [name]: updated });
  };

  const toggleVisibility = (name: string) => {
    setShowApiKey((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  if (fetchError) {
    return (
      <p className="text-xs text-red-400 mt-1">
        Failed to load app configuration options. Please refresh.
      </p>
    );
  }
  if (defaults.length === 0) return null;

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
                  <th scope="col" className="text-left py-2 w-1/5">App</th>
                  <th scope="col" className="text-left py-2 w-[15%]">Scheme</th>
                  <th scope="col" className="text-left py-2 w-[25%]">Port override</th>
                  <th scope="col" className="text-left py-2 w-[40%]">API Key</th>
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
                      <td className="py-2 text-sm text-gray-300">{app.display_name}</td>
                      <td className="py-2 pr-3">
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
                      <td className="py-2 pr-3">
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
                      <td className="py-2">
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
                              {showApiKey[app.name] ? (
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.11 6.11m3.769 3.769a3 3 0 00-.002 4.248M14.12 14.12l3.768 3.768M6.11 6.11L3 3m3.11 3.11l4.243 4.243" />
                                </svg>
                              ) : (
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                </svg>
                              )}
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
                            {showApiKey[app.name] ? (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.11 6.11m3.769 3.769a3 3 0 00-.002 4.248M14.12 14.12l3.768 3.768M6.11 6.11L3 3m3.11 3.11l4.243 4.243" />
                              </svg>
                            ) : (
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                              </svg>
                            )}
                          </button>
                        </div>
                      </div>
                    )}
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
