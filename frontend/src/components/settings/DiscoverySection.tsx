import FormField from '../setup/FormField';
import Toggle from '../setup/Toggle';

interface DiscoverySectionProps {
  pollInterval: number;
  pendingUpdatesInterval: number;
  discoverVms: boolean;
  verifySsl: boolean;
  versionDetectMethod: string;
  errors: Record<string, string | undefined>;
  onPollIntervalChange: (v: number) => void;
  onPendingUpdatesIntervalChange: (v: number) => void;
  onDiscoverVmsChange: (v: boolean) => void;
  onVerifySslChange: (v: boolean) => void;
  onVersionDetectMethodChange: (v: string) => void;
  disabled?: boolean;
}

const inputClass = (field: string, errors: Record<string, string | undefined>) =>
  `w-full px-3 py-1.5 text-sm bg-surface border rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
    errors[field] ? 'border-red-500' : 'border-gray-800'
  }`;

export default function DiscoverySection({
  pollInterval,
  pendingUpdatesInterval,
  discoverVms,
  verifySsl,
  versionDetectMethod,
  errors,
  onPollIntervalChange,
  onPendingUpdatesIntervalChange,
  onDiscoverVmsChange,
  onVerifySslChange,
  onVersionDetectMethodChange,
  disabled,
}: DiscoverySectionProps) {
  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Discovery</h2>
      <div className="space-y-3">
        <FormField label="Poll Interval (seconds)" required error={errors.poll_interval_seconds} htmlFor="s_poll_interval" hint="How often proxmon re-scans guests and checks for new versions (30 – 86400)">
          <input
            id="s_poll_interval"
            type="number"
            min={30}
            max={86400}
            value={pollInterval}
            onChange={(e) => onPollIntervalChange(parseInt(e.target.value) || 3600)}
            disabled={disabled}
            className={inputClass('poll_interval_seconds', errors)}
          />
        </FormField>

        <FormField label="Package Index Refresh Interval (seconds)" error={errors.pending_updates_interval_seconds} htmlFor="s_pending_updates_interval" hint="How often to run apt-get update / dnf check-update per container (3600 – 86400)">
          <input
            id="s_pending_updates_interval"
            type="number"
            min={3600}
            max={86400}
            value={pendingUpdatesInterval}
            onChange={(e) => onPendingUpdatesIntervalChange(parseInt(e.target.value) || 3600)}
            disabled={disabled}
            className={inputClass('pending_updates_interval_seconds', errors)}
          />
        </FormField>

        <Toggle
          id="s_discover_vms"
          label="Include VMs"
          checked={discoverVms}
          onChange={onDiscoverVmsChange}
          hint="Scan QEMU virtual machines in addition to LXC containers"
          disabled={disabled}
        />

        <Toggle
          id="s_verify_ssl"
          label="Verify SSL"
          checked={verifySsl}
          onChange={onVerifySslChange}
          hint="Validate TLS certificates for GitHub release lookups. Per-host TLS is configured individually in the Proxmox Hosts section."
          disabled={disabled}
        />

        {!verifySsl && (
          <div className="flex items-start gap-2 p-2 rounded bg-amber-900/30 border border-amber-800 text-amber-400 text-xs">
            <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <span>SSL verification is disabled. Proxmox uses self-signed certificates by default.</span>
          </div>
        )}

        <FormField label="Version Detection Method" htmlFor="s_version_detect_method" hint="CLI fallback strategy when an app's HTTP API probe does not return a version">
          <select
            id="s_version_detect_method"
            value={versionDetectMethod}
            onChange={(e) => onVersionDetectMethodChange(e.target.value)}
            disabled={disabled}
            className={inputClass('version_detect_method', errors)}
          >
            <option value="pct_first">pct exec first, fallback to SSH</option>
            <option value="ssh_first">SSH first, fallback to pct exec</option>
            <option value="ssh_only">SSH only</option>
            <option value="pct_only">pct exec only</option>
          </select>
        </FormField>
      </div>
    </div>
  );
}
