import { useState, useEffect } from 'react';

const ICON_BASE = 'https://cdn.jsdelivr.net/gh/selfhst/icons/png';

/** When detector id does not match a selfhst/icons PNG basename. */
const DETECTOR_ICON_ALIASES: Record<string, string> = {
  'librespeed-rust': 'librespeed',
  'truenas': 'truenas-core',
  'homeassistant': 'home-assistant',
  'pbs': 'proxmox',
};

interface AppIconProps {
  appName: string | null;
  /** Stable detector id from API (preferred for CDN slug). */
  detectorKey?: string | null;
  size?: number;
  className?: string;
}

function resolveIconSlug(appName: string | null, detectorKey: string | null | undefined): string | null {
  const dk = detectorKey?.trim().toLowerCase();
  if (dk) {
    return DETECTOR_ICON_ALIASES[dk] ?? dk;
  }
  if (!appName) return null;
  let s = appName.toLowerCase().trim();
  s = s.replace(/\s*\([^)]*\)/g, ' ').trim();
  s = s.replace(/\s+/g, '-');
  s = s.replace(/[^a-z0-9-]/g, '');
  return s || null;
}

export default function AppIcon({
  appName,
  detectorKey = null,
  size = 20,
  className = '',
}: AppIconProps) {
  const [failed, setFailed] = useState(false);
  const slug = resolveIconSlug(appName, detectorKey);
  useEffect(() => { setFailed(false); }, [slug]);

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
