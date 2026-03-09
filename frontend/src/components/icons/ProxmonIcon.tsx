interface ProxmonIconProps {
  className?: string;
}

/**
 * Proxmon logo: a stylized server rack with activity pulse line.
 * Uses currentColor so it inherits text color from parent.
 */
export default function ProxmonIcon({ className = 'w-5 h-5' }: ProxmonIconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-testid="proxmon-logo"
    >
      {/* Server rack outline */}
      <rect x="4" y="2" width="16" height="8" rx="1.5" />
      <rect x="4" y="12" width="16" height="8" rx="1.5" />
      {/* Drive indicators - top server */}
      <circle cx="8" cy="6" r="1" fill="currentColor" stroke="none" />
      <line x1="11" y1="6" x2="16" y2="6" />
      {/* Drive indicators - bottom server */}
      <circle cx="8" cy="16" r="1" fill="currentColor" stroke="none" />
      {/* Pulse/activity line - bottom server */}
      <polyline points="11,16 12.5,14 14,18 15.5,16 17,16" strokeWidth={1.5} />
    </svg>
  );
}
