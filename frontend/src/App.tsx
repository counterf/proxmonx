import { useState, useEffect, useCallback, useRef } from 'react';
import { Routes, Route, Link, useNavigate, useLocation } from 'react-router-dom';
import Dashboard from './components/Dashboard';
import GuestDetail from './components/GuestDetail';
import Settings from './components/Settings';
import SetupWizard from './components/setup/SetupWizard';
import LoginPage from './components/LoginPage';
import LoadingSpinner from './components/LoadingSpinner';
import ProxmonIcon from './components/icons/ProxmonIcon';
import { fetchSetupStatus, fetchAuthStatus, logout } from './api/client';
import type { AuthStatus } from './types';

function App() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [checkError, setCheckError] = useState(false);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  const checkSetup = useCallback(async () => {
    try {
      const status = await fetchSetupStatus();
      setConfigured(status.configured);
      setCheckError(false);
      if (!status.configured && location.pathname !== '/setup') {
        navigate('/setup', { replace: true });
        return;
      }
      // Check auth status after setup passes
      if (status.configured) {
        const auth = await fetchAuthStatus();
        setAuthStatus(auth);
        if (auth.auth_mode === 'forms' && !auth.authenticated && location.pathname !== '/login') {
          navigate('/login', { replace: true });
        }
      }
    } catch {
      setCheckError(true);
      setConfigured(false);
    }
  }, [navigate, location.pathname]);

  useEffect(() => {
    checkSetup();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Close user menu on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleWizardComplete = useCallback(() => {
    setConfigured(true);
    navigate('/', { replace: true });
  }, [navigate]);

  const handleLoginSuccess = useCallback(async () => {
    const auth = await fetchAuthStatus();
    setAuthStatus(auth);
    navigate('/', { replace: true });
  }, [navigate]);

  const handleLogout = useCallback(async () => {
    await logout();
    setAuthStatus({ auth_mode: 'forms', authenticated: false });
    setShowUserMenu(false);
    navigate('/login', { replace: true });
  }, [navigate]);

  // Loading state
  if (configured === null && !checkError) {
    return (
      <div className="min-h-screen bg-background text-gray-100 flex items-center justify-center">
        <LoadingSpinner text="Connecting to proxmon..." />
      </div>
    );
  }

  // Unconfigured: show wizard
  if (configured === false) {
    return (
      <div className="min-h-screen bg-background text-gray-100">
        <nav className="sticky top-0 z-50 flex items-center h-12 px-4 bg-surface border-b border-gray-800">
          <span className="flex items-center gap-2 text-white" aria-label="proxmon">
            <ProxmonIcon className="w-5 h-5" />
            <span className="text-lg font-bold tracking-tight">proxmon</span>
          </span>
        </nav>
        <SetupWizard onComplete={handleWizardComplete} />
      </div>
    );
  }

  // Auth gate: show login page if needed
  if (authStatus?.auth_mode === 'forms' && !authStatus.authenticated) {
    return <LoginPage onSuccess={handleLoginSuccess} />;
  }

  const showUserIcon = authStatus?.auth_mode === 'forms' && authStatus.authenticated;

  // Configured: normal app
  return (
    <div className="min-h-screen bg-background text-gray-100">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 flex items-center justify-between h-12 px-4 bg-surface border-b border-gray-800">
        <Link
          to="/"
          className="flex items-center gap-2 text-white hover:text-blue-400 transition-colors"
          aria-label="proxmon -- go to dashboard"
        >
          <ProxmonIcon className="w-5 h-5" />
          <span className="text-lg font-bold tracking-tight">proxmon</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link
            to="/settings"
            className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-white"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span className="hidden sm:inline">Settings</span>
          </Link>
          {showUserIcon && (
            <div className="relative" ref={userMenuRef}>
              <button
                type="button"
                onClick={() => setShowUserMenu((prev) => !prev)}
                className="flex items-center text-gray-400 hover:text-white"
                aria-label="User menu"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                </svg>
              </button>
              {showUserMenu && (
                <div className="absolute right-0 mt-2 w-44 rounded bg-surface border border-gray-700 shadow-lg py-1 z-50">
                  <div className="px-3 py-2 text-xs text-gray-400 border-b border-gray-700">
                    {authStatus?.auth_mode === 'forms' ? 'root' : ''}
                  </div>
                  <button
                    type="button"
                    onClick={handleLogout}
                    className="w-full text-left px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white"
                  >
                    Log out
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-4">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/guest/:id" element={<GuestDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/login" element={<LoginPage onSuccess={handleLoginSuccess} />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
