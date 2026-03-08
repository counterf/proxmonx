import { useState } from 'react';
import type { ConnectionTestResult } from '../../types';

type TestStatus = 'idle' | 'loading' | 'success' | 'error';

interface ConnectionTestButtonProps {
  onTest: () => Promise<ConnectionTestResult>;
  disabled?: boolean;
}

export default function ConnectionTestButton({ onTest, disabled }: ConnectionTestButtonProps) {
  const [status, setStatus] = useState<TestStatus>('idle');
  const [message, setMessage] = useState('');

  const handleTest = async () => {
    setStatus('loading');
    setMessage('');
    try {
      const result = await onTest();
      if (result.success) {
        setStatus('success');
        setMessage(result.message);
      } else {
        setStatus('error');
        setMessage(result.message);
      }
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Connection test failed');
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={handleTest}
        disabled={disabled || status === 'loading'}
        className="px-3 py-1.5 text-sm border border-gray-700 text-gray-300 rounded hover:border-blue-500 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {status === 'loading' ? (
          <span className="flex items-center gap-2">
            <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Testing...
          </span>
        ) : (
          'Test Connection'
        )}
      </button>

      {status === 'success' && (
        <div role="status" className="flex items-center gap-1.5 mt-2 text-xs text-green-400">
          <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          {message}
        </div>
      )}

      {status === 'error' && (
        <div role="alert" className="flex items-start gap-1.5 mt-2 text-xs text-red-400">
          <svg className="w-3.5 h-3.5 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span>
            {message}
            <button
              type="button"
              onClick={handleTest}
              className="ml-2 text-blue-400 hover:text-blue-300 underline"
            >
              Try again
            </button>
          </span>
        </div>
      )}
    </div>
  );
}

export type { TestStatus };
