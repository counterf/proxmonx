/** Shared badge/style constants for guest type and version source. */

/** Returns the Tailwind border+text classes for LXC vs VM type badge. */
export function getTypeBadgeClass(type: string): string {
  return type === 'lxc'
    ? 'border-blue-500 text-blue-400'
    : 'border-purple-500 text-purple-400';
}

/** Version detection method display config. */
export const VERSION_SOURCE_STYLES: Record<string, { label: string; bg: string; text: string }> = {
  http:     { label: 'HTTP API',               bg: 'bg-blue-900/40',   text: 'text-blue-300' },
  ssh:      { label: 'SSH command',            bg: 'bg-yellow-900/40', text: 'text-yellow-300' },
  pct_exec: { label: 'Container exec (pct)',   bg: 'bg-purple-900/40', text: 'text-purple-300' },
};

/** Short labels used in the dashboard table rows. */
export const VERSION_SOURCE_SHORT_LABELS: Record<string, string> = {
  http:     'API',
  ssh:      'SSH',
  pct_exec: 'PCT',
};
