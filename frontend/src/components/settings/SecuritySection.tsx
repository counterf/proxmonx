interface SecuritySectionProps {
  authMode: 'disabled' | 'forms';
  /** Last-saved auth mode (when enabling Forms from Disabled, Current Password is not required). */
  savedAuthMode?: 'disabled' | 'forms';
  authUsername: string;
  authPasswordSet: boolean;
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
  proxmonApiKey: string;
  trustProxyHeaders: boolean;
  onAuthModeChange: (mode: 'disabled' | 'forms') => void;
  onAuthUsernameChange: (username: string) => void;
  onCurrentPasswordChange: (password: string) => void;
  onNewPasswordChange: (password: string) => void;
  onConfirmPasswordChange: (password: string) => void;
  onApiKeyChange: (key: string) => void;
  onTrustProxyHeadersChange: (enabled: boolean) => void;
  disabled?: boolean;
}

export default function SecuritySection({
  authMode,
  savedAuthMode,
  authUsername,
  authPasswordSet,
  currentPassword,
  newPassword,
  confirmPassword,
  proxmonApiKey,
  trustProxyHeaders,
  onAuthModeChange,
  onAuthUsernameChange,
  onCurrentPasswordChange,
  onNewPasswordChange,
  onConfirmPasswordChange,
  onApiKeyChange,
  onTrustProxyHeadersChange,
  disabled = false,
}: SecuritySectionProps) {
  const passwordMismatch = newPassword !== '' && confirmPassword !== '' && newPassword !== confirmPassword;
  const newPasswordTooShort = newPassword !== '' && newPassword.length < 8;
  /** Show Current Password only when saved state was already Forms (change-password flow). Hide when enabling from Disabled or when unknown. */
  const showCurrentPassword = authPasswordSet && savedAuthMode === 'forms';

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
            {(!authPasswordSet || savedAuthMode === 'disabled') && (
              <p className="text-xs text-gray-400 mb-2">
                Set a password below to protect the dashboard. No current password is required.
              </p>
            )}
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

            {showCurrentPassword && (
              <div>
                <label htmlFor="s_current_password" className="block text-xs text-gray-400 mb-1">
                  Current Password
                  <span className="text-gray-600 ml-1">(required to change password)</span>
                </label>
                <input
                  id="s_current_password"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => onCurrentPasswordChange(e.target.value)}
                  disabled={disabled}
                  autoComplete="current-password"
                  className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            )}

            <div>
              <label htmlFor="s_new_password" className="block text-xs text-gray-400 mb-1">
                {showCurrentPassword ? 'New Password' : 'Password'}
                {showCurrentPassword && (
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
                className={`w-full px-3 py-1.5 text-sm bg-surface border rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 ${
                  newPasswordTooShort ? 'border-red-500' : 'border-gray-800'
                }`}
              />
              {newPasswordTooShort && (
                <p className="text-xs text-red-400 mt-1">Password must be at least 8 characters</p>
              )}
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

        <div className="border-t border-gray-800 pt-3 mt-3">
          <p className="text-xs text-gray-500 mb-2">
            Optional API key for authenticating automated scripts and external tools via
            <code className="mx-1 text-gray-400">X-Api-Key</code> header.
          </p>
          <div>
            <label htmlFor="s_proxmon_api_key" className="block text-xs text-gray-400 mb-1">
              API Key
              <span className="text-gray-600 ml-1">(leave blank to disable)</span>
            </label>
            <input
              id="s_proxmon_api_key"
              type="password"
              value={proxmonApiKey}
              onChange={(e) => onApiKeyChange(e.target.value)}
              disabled={disabled}
              autoComplete="off"
              className="w-full px-3 py-1.5 text-sm bg-surface border border-gray-800 rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="flex items-center gap-2 mt-3">
            <input
              id="s_trust_proxy"
              type="checkbox"
              checked={trustProxyHeaders}
              onChange={(e) => onTrustProxyHeadersChange(e.target.checked)}
              disabled={disabled}
              className="accent-blue-500"
            />
            <label htmlFor="s_trust_proxy" className="text-sm text-gray-300 cursor-pointer">
              Trust proxy headers
            </label>
          </div>
          <p className="text-xs text-gray-600 mt-1 ml-5">
            Only enable when behind a trusted reverse proxy (e.g. nginx, Traefik)
            that overwrites X-Forwarded-For with the real client IP.
            Do not enable if clients can send this header directly.
          </p>
        </div>
      </div>
    </div>
  );
}
