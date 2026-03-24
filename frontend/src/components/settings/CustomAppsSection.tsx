import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import type { CustomAppDef } from '../../types';
import { fetchCustomApps, createCustomApp, updateCustomApp, deleteCustomApp } from '../../api/client';
import { HttpError } from '../../api/client';

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32);
}

function uniqueSlug(base: string, existingNames: string[]): string {
  if (!base) return '';
  // Truncate base to 29 chars to always leave room for "-99" suffix
  const truncated = base.slice(0, 29);
  if (!existingNames.includes(truncated)) return truncated;
  let i = 2;
  while (existingNames.includes(`${truncated}-${i}`)) i++;
  return `${truncated}-${i}`;
}

interface FormData {
  display_name: string;
  default_port: string;
  scheme: string;
  version_path: string;
  github_repo: string;
  accepts_api_key: boolean;
  auth_header: string;
  aliases: string;
  docker_images: string;
  version_keys: string;
  strip_v: boolean;
}

const EMPTY_FORM: FormData = {
  display_name: '',
  default_port: '',
  scheme: 'http',
  version_path: '',
  github_repo: '',
  accepts_api_key: false,
  auth_header: '',
  aliases: '',
  docker_images: '',
  version_keys: 'version',
  strip_v: false,
};

function defToForm(def: CustomAppDef): FormData {
  return {
    display_name: def.display_name,
    default_port: String(def.default_port),
    scheme: def.scheme,
    version_path: def.version_path || '',
    github_repo: def.github_repo || '',
    accepts_api_key: def.accepts_api_key,
    auth_header: def.auth_header || '',
    aliases: def.aliases.join(', '),
    docker_images: def.docker_images.join(', '),
    version_keys: def.version_keys.join(', '),
    strip_v: def.strip_v,
  };
}

interface FormErrors {
  [key: string]: string | undefined;
}

export default function CustomAppsSection() {
  const [expanded, setExpanded] = useState(false);
  const [apps, setApps] = useState<CustomAppDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  // Form state
  const [showForm, setShowForm] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>({ ...EMPTY_FORM });
  const [errors, setErrors] = useState<FormErrors>({});
  const [warnings, setWarnings] = useState<FormErrors>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Delete confirmation
  const [deletingName, setDeletingName] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Advanced section
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // How it works
  const [howItWorksOpen, setHowItWorksOpen] = useState(false);

  useEffect(() => {
    fetchCustomApps()
      .then((data) => { setApps(data); setLoading(false); })
      .catch(() => { setFetchError(true); setLoading(false); });
  }, []);

  const reload = async () => {
    try {
      const data = await fetchCustomApps();
      setApps(data);
    } catch {
      // ignore
    }
  };

  const setField = (key: keyof FormData, value: string | boolean) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
    setSaveError(null);
  };

  const validate = (): boolean => {
    const errs: FormErrors = {};
    const warns: FormErrors = {};

    if (!form.display_name.trim()) {
      errs.display_name = 'Display name is required.';
    } else {
      const dup = apps.find(
        (a) => a.display_name.toLowerCase() === form.display_name.trim().toLowerCase()
          && a.name !== editingName
      );
      if (dup) warns.display_name = 'Another custom app has this display name. Consider a more specific name.';
    }

    const port = parseInt(form.default_port, 10);
    if (!form.default_port || isNaN(port) || port < 1 || port > 65535) {
      errs.default_port = 'Port must be a number between 1 and 65535.';
    }

    if (form.version_path && !form.version_path.startsWith('/')) {
      errs.version_path = 'Path must start with /. Example: /api/version';
    }

    if (form.github_repo) {
      const repo = form.github_repo.trim();
      // Backend accepts full GitHub URLs (normalizes to owner/repo); only reject garbage
      if (!repo.includes('github.com') && !repo.startsWith('http') && !/^[^\s/]+\/[^\s/]+$/.test(repo)) {
        errs.github_repo = "Use owner/repo format or a full GitHub URL. Example: mealie-recipes/mealie";
      }
    }

    if (form.accepts_api_key && !form.auth_header.trim()) {
      errs.auth_header = 'Enter the header name, or uncheck the checkbox.';
    }

    setErrors(errs);
    setWarnings(warns);
    return Object.keys(errs).length === 0;
  };

  const handleCreate = () => {
    setForm({ ...EMPTY_FORM });
    setErrors({});
    setWarnings({});
    setSaveError(null);
    setSuccessMessage(null);
    setEditingName(null);
    setShowForm(true);
    setAdvancedOpen(false);
  };

  const handleEdit = (app: CustomAppDef) => {
    setForm(defToForm(app));
    setErrors({});
    setWarnings({});
    setSaveError(null);
    setSuccessMessage(null);
    setEditingName(app.name);
    setShowForm(false);
    setAdvancedOpen(false);
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingName(null);
    setForm({ ...EMPTY_FORM });
    setErrors({});
    setWarnings({});
    setSaveError(null);
  };

  const buildPayload = (name: string): CustomAppDef => {
    const splitTrim = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean);
    return {
      name,
      display_name: form.display_name.trim(),
      default_port: parseInt(form.default_port, 10),
      scheme: form.scheme,
      version_path: form.version_path.trim() || null,
      github_repo: form.github_repo.trim() || null,
      aliases: splitTrim(form.aliases),
      docker_images: splitTrim(form.docker_images),
      accepts_api_key: form.accepts_api_key,
      auth_header: form.accepts_api_key ? form.auth_header.trim() || null : null,
      version_keys: splitTrim(form.version_keys).length > 0 ? splitTrim(form.version_keys) : ['version'],
      strip_v: form.strip_v,
    };
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (editingName) {
        // Update
        const payload = buildPayload(editingName);
        await updateCustomApp(editingName, payload);
        await reload();
        setEditingName(null);
      } else {
        // Create
        const baseSlug = slugify(form.display_name.trim());
        const existingNames = apps.map((a) => a.name);
        const name = uniqueSlug(baseSlug, existingNames);
        if (!name || !/^[a-z][a-z0-9-]{1,31}$/.test(name)) {
          setSaveError('Could not generate a valid app ID from the display name. Start with a letter (a–z).');
          setSaving(false);
          return;
        }
        const payload = buildPayload(name);
        await createCustomApp(payload);
        await reload();
        setShowForm(false);
        setForm({ ...EMPTY_FORM });
        setSuccessMessage(`${payload.display_name} added. Now assign it to a guest from their detail page.`);
      }
    } catch (err) {
      if (err instanceof HttpError && err.status === 409) {
        setSaveError('A custom app with this name already exists.');
      } else {
        setSaveError(err instanceof Error ? err.message : 'Save failed');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (name: string) => {
    setDeleting(true);
    try {
      await deleteCustomApp(name);
      await reload();
      setDeletingName(null);
      if (editingName === name) {
        setEditingName(null);
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeleting(false);
    }
  };

  const renderForm = (isEdit: boolean) => (
    <div className="space-y-3 p-3 rounded bg-gray-800/40 border border-gray-700">
      {/* Tier 1 fields */}
      <div>
        <label htmlFor="cad-display-name" className="text-xs text-gray-500">
          Display Name {!isEdit && <span className="text-red-400">*</span>}
        </label>
        <input
          id="cad-display-name"
          type="text"
          value={form.display_name}
          onChange={(e) => setField('display_name', e.target.value)}
          disabled={saving}
          placeholder="e.g. Mealie"
          className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
        />
        {errors.display_name && <p className="text-xs text-red-400 mt-0.5">{errors.display_name}</p>}
        {warnings.display_name && <p className="text-xs text-amber-400 mt-0.5">{warnings.display_name}</p>}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor="cad-port" className="text-xs text-gray-500">
            Default Port <span className="text-red-400">*</span>
          </label>
          <input
            id="cad-port"
            type="number"
            min={1}
            max={65535}
            value={form.default_port}
            onChange={(e) => setField('default_port', e.target.value)}
            disabled={saving}
            placeholder="e.g. 9925"
            className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {errors.default_port && <p className="text-xs text-red-400 mt-0.5">{errors.default_port}</p>}
        </div>
        <div>
          <label htmlFor="cad-scheme" className="text-xs text-gray-500">Scheme</label>
          <select
            id="cad-scheme"
            value={form.scheme}
            onChange={(e) => setField('scheme', e.target.value)}
            disabled={saving}
            className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="http">HTTP</option>
            <option value="https">HTTPS</option>
          </select>
        </div>
      </div>

      <div>
        <label htmlFor="cad-version-path" className="text-xs text-gray-500">Version endpoint path</label>
        <input
          id="cad-version-path"
          type="text"
          value={form.version_path}
          onChange={(e) => setField('version_path', e.target.value)}
          disabled={saving}
          placeholder="/api/version"
          className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <p className="text-xs text-gray-600 mt-0.5">
          The HTTP path proxmon will query to find the installed version. Leave blank to skip version detection.
        </p>
        {errors.version_path && <p className="text-xs text-red-400 mt-0.5">{errors.version_path}</p>}
      </div>

      <div>
        <label htmlFor="cad-github-repo" className="text-xs text-gray-500">GitHub repository</label>
        <input
          id="cad-github-repo"
          type="text"
          value={form.github_repo}
          onChange={(e) => setField('github_repo', e.target.value)}
          disabled={saving}
          placeholder="owner/repo"
          className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <p className="text-xs text-gray-600 mt-0.5">
          Used to fetch the latest release and compare against the installed version.
        </p>
        {errors.github_repo && <p className="text-xs text-red-400 mt-0.5">{errors.github_repo}</p>}
      </div>

      {/* Tier 2 -- Advanced */}
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setAdvancedOpen(!advancedOpen)}
          className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
        >
          <span>{advancedOpen ? '\u25BC' : '\u25B6'}</span>
          <span>Advanced</span>
        </button>
        {advancedOpen && (
          <div className="mt-2 space-y-3 pl-2 border-l border-gray-700">
            <div>
              <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.accepts_api_key}
                  onChange={(e) => setField('accepts_api_key', e.target.checked)}
                  disabled={saving}
                  className="rounded border-gray-600 bg-surface text-blue-500 focus:ring-blue-500"
                />
                Requires API key to query version endpoint
              </label>
              {form.accepts_api_key && (
                <div className="mt-2 ml-6">
                  <label htmlFor="cad-auth-header" className="text-xs text-gray-500">Auth header name</label>
                  <input
                    id="cad-auth-header"
                    type="text"
                    value={form.auth_header}
                    onChange={(e) => setField('auth_header', e.target.value)}
                    disabled={saving}
                    placeholder="X-Api-Key"
                    className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p className="text-xs text-gray-600 mt-0.5">
                    Common values: X-Api-Key, Authorization, X-API-KEY
                  </p>
                  <p className="text-xs text-gray-600">
                    After saving, set the API key for this app in App Configuration above.
                  </p>
                  {errors.auth_header && <p className="text-xs text-red-400 mt-0.5">{errors.auth_header}</p>}
                </div>
              )}
            </div>

            <div>
              <label htmlFor="cad-aliases" className="text-xs text-gray-500">
                Auto-detect if guest name contains
              </label>
              <input
                id="cad-aliases"
                type="text"
                value={form.aliases}
                onChange={(e) => setField('aliases', e.target.value)}
                disabled={saving}
                placeholder="mealie, meal-planner"
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-600 mt-0.5">
                Matched against LXC/VM names and Docker container tags. Leave blank to assign manually from the guest detail page.
              </p>
            </div>

            <div>
              <label htmlFor="cad-docker-images" className="text-xs text-gray-500">
                Auto-detect if Docker image matches
              </label>
              <input
                id="cad-docker-images"
                type="text"
                value={form.docker_images}
                onChange={(e) => setField('docker_images', e.target.value)}
                disabled={saving}
                placeholder="ghcr.io/mealie-recipes/mealie"
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div>
              <label htmlFor="cad-version-keys" className="text-xs text-gray-500">
                JSON key path(s)
              </label>
              <input
                id="cad-version-keys"
                type="text"
                value={form.version_keys}
                onChange={(e) => setField('version_keys', e.target.value)}
                disabled={saving}
                placeholder="version"
                className="w-full mt-0.5 px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-600 mt-0.5">
                Dot-separated path to version in JSON response. Example: info.version
              </p>
            </div>

            <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={form.strip_v}
                onChange={(e) => setField('strip_v', e.target.checked)}
                disabled={saving}
                className="rounded border-gray-600 bg-surface text-blue-500 focus:ring-blue-500"
              />
              Strip leading 'v' from version
            </label>
          </div>
        )}
      </div>

      {/* Save / Cancel */}
      {saveError && <p className="text-xs text-red-400">{saveError}</p>}
      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-colors"
        >
          {saving ? 'Saving...' : isEdit ? 'Save changes' : 'Save'}
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={saving}
          className="px-3 py-1.5 text-sm rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );

  if (fetchError) {
    return (
      <p className="text-xs text-red-400 mt-1">
        Failed to load custom apps. Please refresh.
      </p>
    );
  }

  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls="custom-apps-panel"
        className="w-full flex items-center justify-between text-left"
      >
        <div>
          <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider">
            Custom Apps
          </h2>
          <p className="text-xs text-gray-600 mt-0.5">
            Define your own apps for version monitoring
          </p>
        </div>
        <svg
          className={`w-4 h-4 text-gray-500 transition-transform duration-150 ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div id="custom-apps-panel" className="mt-3">
          {loading ? (
            <p className="text-xs text-gray-500">Loading...</p>
          ) : apps.length === 0 && !showForm ? (
            <div className="space-y-3">
              <p className="text-sm text-gray-500">
                No custom apps defined yet. proxmon can monitor any app that exposes its version via HTTP -- not just built-in ones.
              </p>
              <button
                type="button"
                onClick={handleCreate}
                className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              >
                + Add custom app
              </button>
              <div>
                <button
                  type="button"
                  onClick={() => setHowItWorksOpen(!howItWorksOpen)}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  {howItWorksOpen ? 'Hide' : 'How does this work?'}
                </button>
                {howItWorksOpen && (
                  <ol className="mt-2 text-xs text-gray-500 space-y-1 list-decimal list-inside">
                    <li>Define the app here with its name, port, and version endpoint.</li>
                    <li>proxmon registers it as a detector alongside built-in apps.</li>
                    <li>Assign it to a guest from the guest detail page, or set up auto-detection via name/Docker image patterns.</li>
                    <li>proxmon probes the version endpoint and compares against GitHub releases.</li>
                  </ol>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {/* List existing apps */}
              {apps.map((app) => (
                <div key={app.name}>
                  {deletingName === app.name ? (
                    <div className="p-3 rounded bg-red-900/20 border border-red-800/50 space-y-2">
                      <p className="text-sm text-gray-300">
                        Delete "{app.display_name}"? This will remove it from all guests where it's assigned.
                      </p>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleDelete(app.name)}
                          disabled={deleting}
                          className="px-3 py-1.5 text-sm rounded bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white transition-colors"
                        >
                          {deleting ? 'Deleting...' : 'Delete'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeletingName(null)}
                          disabled={deleting}
                          className="px-3 py-1.5 text-sm rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 disabled:opacity-50 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : editingName === app.name ? (
                    renderForm(true)
                  ) : (
                    <div className="flex items-center justify-between py-2 px-3 rounded bg-gray-800/40 text-sm">
                      <div className="text-gray-300 min-w-0">
                        <span className="font-medium">{app.display_name}</span>
                        <span className="text-gray-500 ml-2">port {app.default_port}</span>
                        <span className="text-gray-600 ml-2">{app.version_path || 'no version probe'}</span>
                        <span className="text-gray-600 ml-2">{app.github_repo || '\u2014'}</span>
                      </div>
                      <div className="flex items-center gap-1 ml-2 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleEdit(app)}
                          className="px-2 py-1 text-xs rounded text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeletingName(app.name)}
                          className="px-2 py-1 text-xs rounded text-gray-400 hover:text-red-400 hover:bg-gray-700 transition-colors"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {/* Success message after create */}
              {successMessage && (
                <div className="p-3 rounded bg-green-900/20 border border-green-800/50 text-sm text-green-400 flex items-center justify-between">
                  <span>{successMessage}</span>
                  <Link to="/" className="text-xs text-blue-400 hover:text-blue-300 ml-2 shrink-0">
                    View all guests &rarr;
                  </Link>
                </div>
              )}

              {/* Add form */}
              {showForm && renderForm(false)}

              {/* Add button */}
              {!showForm && !editingName && (
                <button
                  type="button"
                  onClick={handleCreate}
                  className="px-3 py-1.5 text-sm rounded border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
                >
                  + Add custom app
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
