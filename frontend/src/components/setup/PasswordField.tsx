import { useState } from 'react';
import { EyeIcon, EyeSlashIcon } from '../icons/EyeIcons';
import FormField from './FormField';

interface PasswordFieldProps {
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  error?: string;
  label: string;
  required?: boolean;
  hint?: string;
  disabled?: boolean;
}

export default function PasswordField({
  id,
  value,
  onChange,
  placeholder,
  error,
  label,
  required,
  hint,
  disabled,
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <FormField label={label} error={error} required={required} hint={hint} htmlFor={id}>
      <div className="relative">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          aria-required={required}
          aria-describedby={error ? `${id}-error` : undefined}
          className={`w-full px-3 py-1.5 text-sm bg-surface border rounded font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500 pr-10 disabled:opacity-50 disabled:cursor-not-allowed ${
            error ? 'border-red-500' : 'border-gray-800'
          }`}
        />
        <button
          type="button"
          onClick={() => setVisible(!visible)}
          disabled={disabled}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={visible ? `Hide ${label}` : `Show ${label}`}
        >
          {visible ? <EyeSlashIcon /> : <EyeIcon />}
        </button>
      </div>
    </FormField>
  );
}
