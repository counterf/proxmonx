import FormField from '../setup/FormField';
import PasswordField from '../setup/PasswordField';
import Toggle from '../setup/Toggle';

type AuthMethod = 'key' | 'password';

interface SSHSectionProps {
  sshEnabled: boolean;
  sshUsername: string;
  sshKeyPath: string;
  sshPassword: string;
  authMethod: AuthMethod;
  onSshEnabledChange: (v: boolean) => void;
  onSshUsernameChange: (v: string) => void;
  onSshKeyPathChange: (v: string) => void;
  onSshPasswordChange: (v: string) => void;
  onAuthMethodChange: (v: AuthMethod) => void;
  disabled?: boolean;
}

const inputClass =
  'w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500';

export default function SSHSection({
  sshEnabled,
  sshUsername,
  sshKeyPath,
  sshPassword,
  authMethod,
  onSshEnabledChange,
  onSshUsernameChange,
  onSshKeyPathChange,
  onSshPasswordChange,
  onAuthMethodChange,
  disabled,
}: SSHSectionProps) {
  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">SSH</h2>
      <p className="text-xs text-gray-500 mb-3">
        Global SSH defaults used for direct connections to guests. Per-host and per-app overrides take priority.
      </p>
      <div className="space-y-3">
        <Toggle
          id="s_ssh_enabled"
          label="Enable SSH"
          checked={sshEnabled}
          onChange={onSshEnabledChange}
          hint="Allow SSH and pct exec for CLI-based version detection"
          disabled={disabled}
        />

        {sshEnabled && (
          <>
            <FormField label="SSH Username" required htmlFor="s_ssh_username" hint="Default username for SSH connections to guest containers">
              <input
                id="s_ssh_username"
                type="text"
                value={sshUsername}
                onChange={(e) => onSshUsernameChange(e.target.value)}
                disabled={disabled}
                className={inputClass}
              />
            </FormField>

            <div>
              <p className="text-xs text-gray-400 mb-1">Authentication</p>
              <p className="text-xs text-gray-600 mb-2">Choose how proxmon authenticates when connecting via SSH</p>
              <div className="flex gap-4">
                <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                  <input
                    type="radio"
                    name="s_auth_method"
                    checked={authMethod === 'key'}
                    onChange={() => onAuthMethodChange('key')}
                    disabled={disabled}
                    className="accent-blue-500"
                  />
                  Key file
                </label>
                <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                  <input
                    type="radio"
                    name="s_auth_method"
                    checked={authMethod === 'password'}
                    onChange={() => onAuthMethodChange('password')}
                    disabled={disabled}
                    className="accent-blue-500"
                  />
                  Password
                </label>
              </div>
            </div>

            {authMethod === 'key' && (
              <FormField label="Private Key Path" htmlFor="s_ssh_key_path" hint="Absolute path to the SSH private key inside the proxmon container">
                <input
                  id="s_ssh_key_path"
                  type="text"
                  value={sshKeyPath}
                  onChange={(e) => onSshKeyPathChange(e.target.value)}
                  placeholder="/root/.ssh/id_ed25519"
                  disabled={disabled}
                  className={inputClass}
                />
              </FormField>
            )}

            {authMethod === 'password' && (
              <PasswordField
                id="s_ssh_password"
                label="SSH Password"
                value={sshPassword}
                onChange={onSshPasswordChange}
                hint="Fallback password when no key is configured"
                disabled={disabled}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
