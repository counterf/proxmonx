import { useState } from 'react';
import FormField from '../setup/FormField';
import PasswordField from '../setup/PasswordField';
import Toggle from '../setup/Toggle';
import { sendTestNotification } from '../../api/client';

interface NotificationsSectionProps {
  enabled: boolean;
  ntfyUrl: string;
  ntfyToken: string;
  ntfyPriority: number;
  diskThreshold: number;
  diskCooldown: number;
  notifyOnOutdated: boolean;
  onEnabledChange: (v: boolean) => void;
  onNtfyUrlChange: (v: string) => void;
  onNtfyTokenChange: (v: string) => void;
  onNtfyPriorityChange: (v: number) => void;
  onDiskThresholdChange: (v: number) => void;
  onDiskCooldownChange: (v: number) => void;
  onNotifyOnOutdatedChange: (v: boolean) => void;
  disabled?: boolean;
}

const inputClass =
  'w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500';

export default function NotificationsSection({
  enabled,
  ntfyUrl,
  ntfyToken,
  ntfyPriority,
  diskThreshold,
  diskCooldown,
  notifyOnOutdated,
  onEnabledChange,
  onNtfyUrlChange,
  onNtfyTokenChange,
  onNtfyPriorityChange,
  onDiskThresholdChange,
  onDiskCooldownChange,
  onNotifyOnOutdatedChange,
  disabled,
}: NotificationsSectionProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await sendTestNotification();
      setTestResult(res.success ? res.message : `Failed: ${res.message}`);
    } catch (err) {
      setTestResult(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Notifications</h2>
      <p className="text-xs text-gray-500 mb-3">
        Push alerts to an ntfy server when disk usage or version thresholds are exceeded.
      </p>
      <div className="space-y-3">
        <Toggle
          id="s_notifications_enabled"
          label="Enable Notifications"
          checked={enabled}
          onChange={onEnabledChange}
          hint="Activate push notifications after each discovery cycle"
          disabled={disabled}
        />

        {enabled && (
          <>
            <FormField label="ntfy URL" required htmlFor="s_ntfy_url" hint="Full URL including the topic name, e.g. https://ntfy.sh/my-proxmon-alerts">
              <input
                id="s_ntfy_url"
                type="text"
                value={ntfyUrl}
                onChange={(e) => onNtfyUrlChange(e.target.value)}
                placeholder="https://ntfy.sh/my-proxmon-alerts"
                disabled={disabled}
                className={inputClass}
              />
            </FormField>

            <PasswordField
              id="s_ntfy_token"
              label="ntfy Access Token"
              value={ntfyToken}
              onChange={onNtfyTokenChange}
              hint="Required only if the ntfy topic uses access control"
              disabled={disabled}
            />

            <FormField label="Priority" htmlFor="s_ntfy_priority" hint="Default priority for notifications (disk alerts always use High)">
              <select
                id="s_ntfy_priority"
                value={ntfyPriority}
                onChange={(e) => onNtfyPriorityChange(parseInt(e.target.value))}
                disabled={disabled}
                className={inputClass}
              >
                <option value={1}>1 - Min</option>
                <option value={2}>2 - Low</option>
                <option value={3}>3 - Default</option>
                <option value={4}>4 - High</option>
                <option value={5}>5 - Urgent</option>
              </select>
            </FormField>

            <FormField label="Disk Usage Threshold (%)" htmlFor="s_disk_threshold" hint="Send an alert when a guest's disk usage reaches or exceeds this percentage (50 -- 100)">
              <input
                id="s_disk_threshold"
                type="number"
                min={50}
                max={100}
                value={diskThreshold}
                onChange={(e) => onDiskThresholdChange(parseInt(e.target.value) || 95)}
                disabled={disabled}
                className={inputClass}
              />
            </FormField>

            <FormField label="Disk Alert Cooldown (minutes)" htmlFor="s_disk_cooldown" hint="Minimum wait time before re-sending a disk alert for the same guest (15 -- 1440)">
              <input
                id="s_disk_cooldown"
                type="number"
                min={15}
                max={1440}
                value={diskCooldown}
                onChange={(e) => onDiskCooldownChange(parseInt(e.target.value) || 60)}
                disabled={disabled}
                className={inputClass}
              />
            </FormField>

            <Toggle
              id="s_notify_outdated"
              label="Notify on Outdated"
              checked={notifyOnOutdated}
              onChange={onNotifyOnOutdatedChange}
              hint="Send a one-time alert when an app transitions from up-to-date to outdated"
              disabled={disabled}
            />

            <div className="pt-2">
              <button
                type="button"
                onClick={handleTest}
                disabled={disabled || testing || !ntfyUrl}
                className="px-4 py-1.5 text-sm font-medium rounded bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {testing ? 'Sending...' : 'Send Test Notification'}
              </button>
              {testResult && (
                <p className={`text-xs mt-2 ${testResult.startsWith('Failed') ? 'text-red-400' : 'text-green-400'}`}>
                  {testResult}
                </p>
              )}
              {!ntfyUrl && (
                <p className="text-xs text-gray-500 mt-2">Save settings with a valid ntfy URL first to test notifications</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
