import type { UpdateStatus } from '../types';

interface StatusBadgeProps {
  status: UpdateStatus;
}

const STATUS_STYLES: Record<UpdateStatus, { label: string; className: string }> = {
  'up-to-date': {
    label: 'OK',
    className: 'bg-green-900 text-green-500',
  },
  'outdated': {
    label: 'OUTDATED',
    className: 'bg-red-900 text-red-400',
  },
  'unknown': {
    label: 'UNKNOWN',
    className: 'bg-gray-800 text-gray-400',
  },
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold ${style.className}`}
      aria-label={`Status: ${style.label}`}
    >
      {style.label}
    </span>
  );
}
