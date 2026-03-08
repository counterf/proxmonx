import { useState } from 'react';

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex items-center justify-between gap-3 px-4 py-2.5 mb-4 rounded bg-red-900/60 border border-red-800 text-red-200 text-sm"
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">Error:</span>
        <span>{message}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-2 py-1 text-xs rounded bg-red-800 hover:bg-red-700 text-red-100"
          >
            Retry
          </button>
        )}
        <button
          onClick={() => setDismissed(true)}
          className="text-red-400 hover:text-red-200"
          aria-label="Dismiss error"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
