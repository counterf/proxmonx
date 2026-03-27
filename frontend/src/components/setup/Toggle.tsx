interface ToggleProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
  disabled?: boolean;
}

export default function Toggle({ id, label, checked, onChange, hint, disabled }: ToggleProps) {
  const labelId = `${id}-label`;
  return (
    <div className="flex items-center justify-between">
      <div>
        {/* span + aria-labelledby rather than label[htmlFor] on a <button>: the
            HTML spec only links <label> to labelable elements (input, select, etc.),
            not <button>. Using aria-labelledby avoids double-activation on AT. */}
        <span id={labelId} className="text-xs text-gray-400">
          {label}
        </span>
        {hint && <p className="text-xs text-gray-600 mt-0.5">{hint}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        onClick={() => !disabled && onChange(!checked)}
        disabled={disabled}
        className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none disabled:opacity-50 disabled:cursor-not-allowed ${
          checked ? 'bg-blue-600' : 'bg-gray-700'
        }`}
      >
        <span
          className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  );
}
