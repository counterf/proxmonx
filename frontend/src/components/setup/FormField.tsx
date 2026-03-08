interface FormFieldProps {
  label: string;
  error?: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
  htmlFor?: string;
}

export default function FormField({ label, error, required, hint, children, htmlFor }: FormFieldProps) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-xs text-gray-400 mb-1">
        {label}
        {required && <span aria-hidden="true" className="text-red-400 ml-0.5">*</span>}
      </label>
      {children}
      {error && (
        <p id={htmlFor ? `${htmlFor}-error` : undefined} role="alert" className="text-xs text-red-400 mt-1">
          {error}
        </p>
      )}
      {!error && hint && (
        <p className="text-xs text-gray-500 mt-1">{hint}</p>
      )}
    </div>
  );
}
