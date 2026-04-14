import { EyeIcon, EyeSlashIcon } from '../icons/EyeIcons';

interface SshFieldGroupProps {
  /** HTML id prefix for form elements. */
  idPrefix: string;
  /** Current field values. */
  versionCmd: string;
  username: string;
  sshKey: string;
  password: string;
  /** Whether to show the password in plain text. */
  showPassword: boolean;
  /** Callbacks. */
  onVersionCmdChange: (v: string) => void;
  onUsernameChange: (v: string) => void;
  onSshKeyChange: (v: string) => void;
  onPasswordChange: (v: string) => void;
  onToggleShowPassword: () => void;
  /** Optional per-field placeholder overrides. */
  versionCmdPlaceholder?: string;
  usernamePlaceholder?: string;
  sshKeyPlaceholder?: string;
  passwordPlaceholder?: string;
  /** Optional aria-label suffix for context (e.g. "for Sonarr"). */
  ariaContext?: string;
  disabled?: boolean;
}

const inputClass =
  'w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-white placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500';

export default function SshFieldGroup({
  idPrefix,
  versionCmd,
  username,
  sshKey,
  password,
  showPassword,
  onVersionCmdChange,
  onUsernameChange,
  onSshKeyChange,
  onPasswordChange,
  onToggleShowPassword,
  versionCmdPlaceholder = 'e.g. myapp --version | head -1',
  usernamePlaceholder = 'root (uses global default)',
  sshKeyPlaceholder = '-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----',
  passwordPlaceholder = 'leave blank to keep',
  ariaContext,
  disabled,
}: SshFieldGroupProps) {
  const suffix = ariaContext ? ` ${ariaContext}` : '';
  return (
    <div className="mt-2 space-y-2 pl-2 border-l border-gray-700">
      <div>
        <label htmlFor={`${idPrefix}-ssh-cmd`} className="text-xs text-gray-500">
          Version Command
        </label>
        <textarea
          id={`${idPrefix}-ssh-cmd`}
          rows={2}
          value={versionCmd}
          placeholder={versionCmdPlaceholder}
          onChange={(e) => onVersionCmdChange(e.target.value)}
          disabled={disabled}
          aria-label={`SSH version command${suffix}`}
          className={`${inputClass} resize-none`}
        />
      </div>
      <div>
        <label htmlFor={`${idPrefix}-ssh-user`} className="text-xs text-gray-500">
          SSH Username
        </label>
        <input
          id={`${idPrefix}-ssh-user`}
          type="text"
          value={username}
          placeholder={usernamePlaceholder}
          onChange={(e) => onUsernameChange(e.target.value)}
          disabled={disabled}
          aria-label={`SSH username${suffix}`}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor={`${idPrefix}-ssh-key`} className="text-xs text-gray-500">
          SSH Private Key
        </label>
        <textarea
          id={`${idPrefix}-ssh-key`}
          rows={4}
          value={sshKey}
          placeholder={sshKeyPlaceholder}
          onChange={(e) => onSshKeyChange(e.target.value)}
          disabled={disabled}
          aria-label={`SSH private key${suffix}`}
          className={`${inputClass} resize-y text-xs`}
        />
      </div>
      <div>
        <label htmlFor={`${idPrefix}-ssh-pass`} className="text-xs text-gray-500">
          SSH Password
        </label>
        <div className="relative">
          <input
            id={`${idPrefix}-ssh-pass`}
            type={showPassword ? 'text' : 'password'}
            value={password}
            placeholder={passwordPlaceholder}
            onChange={(e) => onPasswordChange(e.target.value)}
            disabled={disabled}
            aria-label={`SSH password${suffix}`}
            className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-10"
          />
          <button
            type="button"
            onClick={onToggleShowPassword}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
            aria-label={showPassword ? `Hide SSH password${suffix}` : `Show SSH password${suffix}`}
          >
            {showPassword ? <EyeSlashIcon /> : <EyeIcon />}
          </button>
        </div>
      </div>
    </div>
  );
}
