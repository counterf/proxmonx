import { useState, useRef, useEffect } from 'react';
import { COLUMN_DEFS, type ColumnKey } from '../hooks/useColumnVisibility';

interface ColumnToggleProps {
  visibleColumns: Set<ColumnKey>;
  onToggle: (key: ColumnKey) => void;
  onReset: () => void;
}

export default function ColumnToggle({ visibleColumns, onToggle, onReset }: ColumnToggleProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open]);

  const toggleable = COLUMN_DEFS.filter((c) => !c.alwaysVisible);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-3 py-2.5 sm:py-1.5 text-sm rounded bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors border border-gray-700"
        aria-expanded={open}
        aria-haspopup="true"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 4h6m-6 4h6m-6 4h6m-6 4h6M4 4h.01M4 8h.01M4 12h.01M4 16h.01" />
        </svg>
        Columns
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-56 rounded border border-gray-700 bg-gray-800 shadow-lg py-1">
          {toggleable.map((col) => (
            <label
              key={col.key}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700/50 cursor-pointer select-none"
            >
              <input
                type="checkbox"
                checked={visibleColumns.has(col.key)}
                onChange={() => onToggle(col.key)}
                className="accent-blue-500 rounded"
              />
              {col.label}
            </label>
          ))}
          <div className="border-t border-gray-700 mt-1 pt-1 px-3 pb-1">
            <button
              onClick={onReset}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              Reset to defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
