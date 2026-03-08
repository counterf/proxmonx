import { useEffect, useRef, useState } from 'react';

interface SuccessToastProps {
  message: string;
  onDismiss: () => void;
  duration?: number;
}

export default function SuccessToast({ message, onDismiss, duration = 4000 }: SuccessToastProps) {
  const [visible, setVisible] = useState(true);
  // Keep a ref so the timer effect doesn't re-run when the parent re-renders
  // with a new inline onDismiss function reference.
  const onDismissRef = useRef(onDismiss);
  useEffect(() => { onDismissRef.current = onDismiss; });

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      onDismissRef.current();
    }, duration);
    return () => clearTimeout(timer);
  }, [duration]); // intentionally omits onDismiss — captured via ref above

  if (!visible) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-4 py-2.5 text-sm rounded bg-green-900 border border-green-800 text-green-200"
    >
      <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      <span>{message}</span>
      <button
        onClick={() => { setVisible(false); onDismiss(); }}
        className="ml-2 text-green-400 hover:text-green-200"
        aria-label="Dismiss"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
