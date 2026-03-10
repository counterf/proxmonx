import { useState } from 'react';

const ICON_BASE = 'https://cdn.jsdelivr.net/gh/selfhst/icons/png';

interface AppIconProps {
  appName: string | null;
  size?: number;
  className?: string;
}

export default function AppIcon({ appName, size = 20, className = '' }: AppIconProps) {
  const [failed, setFailed] = useState(false);
  const slug = appName ? appName.toLowerCase() : null;

  if (!slug || failed) return null;

  return (
    <img
      src={`${ICON_BASE}/${slug}.png`}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
      className={`inline-block shrink-0 rounded ${className}`}
    />
  );
}
