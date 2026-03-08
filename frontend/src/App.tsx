import { useState, useEffect, useCallback } from 'react';
import { Routes, Route, Link, useNavigate, useLocation } from 'react-router-dom';
import Dashboard from './components/Dashboard';
import GuestDetail from './components/GuestDetail';
import Settings from './components/Settings';
import SetupWizard from './components/setup/SetupWizard';
import LoadingSpinner from './components/LoadingSpinner';
import { fetchSetupStatus } from './api/client';

function App() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [checkError, setCheckError] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const checkSetup = useCallback(async () => {
    try {
      const status = await fetchSetupStatus();
      setConfigured(status.configured);
      setCheckError(false);
      if (!status.configured && location.pathname !== '/setup') {
        navigate('/setup', { replace: true });
      }
    } catch {
      // If backend is unreachable, show setup anyway
      setCheckError(true);
      setConfigured(false);
    }
  }, [navigate, location.pathname]);

  useEffect(() => {
    checkSetup();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleWizardComplete = useCallback(() => {
    setConfigured(true);
    navigate('/', { replace: true });
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
          <span className="text-lg font-bold tracking-tight text-white">proxmon</span>
        </nav>
        <SetupWizard onComplete={handleWizardComplete} />
      </div>
    );
  }

  // Configured: normal app
  return (
    <div className="min-h-screen bg-background text-gray-100">
      {/* Navbar */}
      <nav className="sticky top-0 z-50 flex items-center justify-between h-12 px-4 bg-surface border-b border-gray-800">
        <Link to="/" className="text-lg font-bold tracking-tight text-white hover:text-blue-400">
          proxmon
        </Link>
        <Link
          to="/settings"
          className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-white"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          Settings
        </Link>
      </nav>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-4">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/guest/:id" element={<GuestDetail />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
