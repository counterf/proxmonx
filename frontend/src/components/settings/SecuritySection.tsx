interface SecuritySectionProps {
  authMode: 'disabled' | 'forms';
  authUsername: string;
  authPasswordSet: boolean;
  newPassword: string;
  confirmPassword: string;
  onAuthModeChange: (mode: 'disabled' | 'forms') => void;
  onAuthUsernameChange: (username: string) => void;
  onNewPasswordChange: (password: string) => void;
  onConfirmPasswordChange: (password: string) => void;
  disabled?: boolean;
}

export default function SecuritySection({
  authMode,
  authUsername,
  authPasswordSet,
  newPassword,
  confirmPassword,
  onAuthModeChange,
  onAuthUsernameChange,
  onNewPasswordChange,
  onConfirmPasswordChange,
  disabled = false,
}: SecuritySectionProps) {
  const passwordMismatch = newPassword !== '' && confirmPassword !== '' && newPassword !== confirmPassword;

  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Security</h2>
      <div className="space-y-3">
        <div>
          <label htmlFor="s_auth_mode" className="block text-xs text-gray-400 mb-1">
            Auth Mode
          </label>
          <select
            id="s_auth_mode"
            value={authMode}
            onChange={(e) => onAuthModeChange(e.target.value as 'disabled' | 'forms')}
            disabled={disabled}
            className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="disabled">Disabled</option>
            <option value="forms">Forms (Login Page)</option>
          </select>
        </div>

        {authMode === 'forms' && (
          <>
            <div>
              <label htmlFor="s_auth_username" className="block text-xs text-gray-400 mb-1">
                Username
              </label>
              <input
                id="s_auth_username"
                type="text"
                value={authUsername}
                onChange={(e) => onAuthUsernameChange(e.target.value)}
                disabled={disabled}
                className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div>
              <label htmlFor="s_new_password" className="block text-xs text-gray-400 mb-1">
                New Password
                {authPasswordSet && (
                  <span className="text-gray-600 ml-1">(leave blank to keep current)</span>
                )}
              </label>
              <input
                id="s_new_password"
                type="password"
                value={newPassword}
                onChange={(e) => onNewPasswordChange(e.target.value)}
                disabled={disabled}
                autoComplete="new-password"
                className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            <div>
              <label htmlFor="s_confirm_password" className="block text-xs text-gray-400 mb-1">
                Confirm Password
              </label>
              <input
                id="s_confirm_password"
                type="password"
                value={confirmPassword}
                onChange={(e) => onConfirmPasswordChange(e.target.value)}
                disabled={disabled}
                autoComplete="new-password"
                className={`w-full px-3 py-1.5 text-sm bg-surface border rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                  passwordMismatch ? 'border-red-500' : 'border-gray-800'
                }`}
              />
              {passwordMismatch && (
                <p className="text-xs text-red-400 mt-1">Passwords do not match</p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
