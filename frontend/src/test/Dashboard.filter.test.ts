import { describe, it, expect } from 'vitest';
import { compareSemver, compareGuests, diskPercent } from '../components/Dashboard';
import type { Guest } from '../types';

function makeGuest(overrides: Partial<Guest> = {}): Guest {
  return {
    id: '100',
    name: 'test-guest',
    type: 'lxc',
    status: 'running',
    app_name: null,
    installed_version: null,
    latest_version: null,
    update_status: 'unknown',
    last_checked: null,
    tags: [],
    web_url: null,
    host_id: 'default',
    host_label: 'node1',
    ip: null,
    detection_method: null,
    detector_used: null,
    raw_detection_output: null,
    version_history: [],
    version_detection_method: null,
    github_repo_queried: null,
    github_lookup_status: null,
    latest_version_source: null,
    disk_used: null,
    disk_total: null,
    os_type: null,
    probe_url: null,
    probe_error: null,
    ...overrides,
  };
}

// --- compareSemver ---
describe('compareSemver', () => {
  it('1.10.0 > 1.9.0', () => {
    expect(compareSemver('1.10.0', '1.9.0')).toBeGreaterThan(0);
  });

  it('1.0.0 < 2.0.0', () => {
    expect(compareSemver('1.0.0', '2.0.0')).toBeLessThan(0);
  });

  it('equal versions return 0', () => {
    expect(compareSemver('3.2.1', '3.2.1')).toBe(0);
  });

  it('strips v prefix', () => {
    expect(compareSemver('v1.2.3', '1.2.3')).toBe(0);
  });

  it('strips V prefix (uppercase)', () => {
    expect(compareSemver('V1.2.3', '1.2.3')).toBe(0);
  });

  it('handles different segment counts', () => {
    expect(compareSemver('1.0', '1.0.1')).toBeLessThan(0);
  });

  it('falls back to localeCompare for non-numeric', () => {
    const result = compareSemver('alpha', 'beta');
    expect(typeof result).toBe('number');
    expect(result).toBeLessThan(0);
  });
});

// --- diskPercent ---
describe('diskPercent', () => {
  it('returns ratio when both values present', () => {
    expect(diskPercent(makeGuest({ disk_used: 5, disk_total: 10 }))).toBe(0.5);
  });

  it('returns null when disk_used is null', () => {
    expect(diskPercent(makeGuest({ disk_used: null, disk_total: 10 }))).toBeNull();
  });

  it('returns null when disk_total is 0', () => {
    expect(diskPercent(makeGuest({ disk_used: 5, disk_total: 0 }))).toBeNull();
  });
});

// --- compareGuests ---
describe('compareGuests', () => {
  it('sorts by name ascending', () => {
    const a = makeGuest({ name: 'alpha' });
    const b = makeGuest({ name: 'beta' });
    expect(compareGuests(a, b, 'name', 'asc')).toBeLessThan(0);
  });

  it('sorts by name descending', () => {
    const a = makeGuest({ name: 'alpha' });
    const b = makeGuest({ name: 'beta' });
    expect(compareGuests(a, b, 'name', 'desc')).toBeGreaterThan(0);
  });

  it('sorts by installed_version using semver', () => {
    const a = makeGuest({ installed_version: '1.10.0' });
    const b = makeGuest({ installed_version: '1.9.0' });
    expect(compareGuests(a, b, 'installed_version', 'asc')).toBeGreaterThan(0);
  });

  it('sorts by type (lxc vs vm)', () => {
    const a = makeGuest({ type: 'lxc' });
    const b = makeGuest({ type: 'vm' });
    expect(compareGuests(a, b, 'type', 'asc')).toBeLessThan(0);
  });

  it('null values sort last regardless of direction', () => {
    const a = makeGuest({ installed_version: null });
    const b = makeGuest({ installed_version: '1.0.0' });
    // null sorts last in asc
    expect(compareGuests(a, b, 'installed_version', 'asc')).toBe(1);
    // null still sorts last in desc
    expect(compareGuests(a, b, 'installed_version', 'desc')).toBe(1);
  });

  it('both null returns 0', () => {
    const a = makeGuest({ installed_version: null });
    const b = makeGuest({ installed_version: null });
    expect(compareGuests(a, b, 'installed_version', 'asc')).toBe(0);
  });

  it('sorts by disk (percent)', () => {
    const a = makeGuest({ disk_used: 3, disk_total: 10 }); // 30%
    const b = makeGuest({ disk_used: 7, disk_total: 10 }); // 70%
    expect(compareGuests(a, b, 'disk', 'asc')).toBeLessThan(0);
    expect(compareGuests(a, b, 'disk', 'desc')).toBeGreaterThan(0);
  });

  it('disk null sorts last', () => {
    const a = makeGuest({ disk_used: null, disk_total: null });
    const b = makeGuest({ disk_used: 5, disk_total: 10 });
    expect(compareGuests(a, b, 'disk', 'asc')).toBe(1);
  });

  it('sorts by last_checked as date', () => {
    const a = makeGuest({ last_checked: '2024-01-01T00:00:00Z' });
    const b = makeGuest({ last_checked: '2024-06-01T00:00:00Z' });
    expect(compareGuests(a, b, 'last_checked', 'asc')).toBeLessThan(0);
  });
});

// --- filtering logic (pure function test) ---
describe('filtering guests', () => {
  const guests: Guest[] = [
    makeGuest({ id: '1', name: 'plex-server', type: 'lxc', update_status: 'up-to-date', host_id: 'h1', app_name: 'Plex' }),
    makeGuest({ id: '2', name: 'sonarr-vm', type: 'vm', update_status: 'outdated', host_id: 'h1', app_name: 'Sonarr' }),
    makeGuest({ id: '3', name: 'radarr-ct', type: 'lxc', update_status: 'outdated', host_id: 'h2', app_name: 'Radarr' }),
    makeGuest({ id: '4', name: 'homeassistant', type: 'vm', update_status: 'unknown', host_id: 'h2', app_name: 'Home Assistant' }),
  ];

  // Replicate the filter logic from Dashboard.tsx
  function filterGuests(
    all: Guest[],
    opts: { status?: string; type?: string; host?: string; search?: string },
  ): Guest[] {
    return all.filter((g) => {
      if (opts.status && opts.status !== 'all' && g.update_status !== opts.status) return false;
      if (opts.type && opts.type !== 'all' && g.type !== opts.type) return false;
      if (opts.host && opts.host !== 'all' && g.host_id !== opts.host) return false;
      if (opts.search) {
        const q = opts.search.toLowerCase();
        const nameMatch = g.name.toLowerCase().includes(q);
        const appMatch = g.app_name?.toLowerCase().includes(q) || false;
        if (!nameMatch && !appMatch) return false;
      }
      return true;
    });
  }

  it('filters by status outdated', () => {
    const result = filterGuests(guests, { status: 'outdated' });
    expect(result).toHaveLength(2);
    expect(result.every((g) => g.update_status === 'outdated')).toBe(true);
  });

  it('status "all" returns everything', () => {
    expect(filterGuests(guests, { status: 'all' })).toHaveLength(4);
  });

  it('filters by type lxc', () => {
    const result = filterGuests(guests, { type: 'lxc' });
    expect(result).toHaveLength(2);
    expect(result.every((g) => g.type === 'lxc')).toBe(true);
  });

  it('filters by type vm', () => {
    const result = filterGuests(guests, { type: 'vm' });
    expect(result).toHaveLength(2);
    expect(result.every((g) => g.type === 'vm')).toBe(true);
  });

  it('filters by host', () => {
    const result = filterGuests(guests, { host: 'h2' });
    expect(result).toHaveLength(2);
    expect(result.every((g) => g.host_id === 'h2')).toBe(true);
  });

  it('search matches name', () => {
    const result = filterGuests(guests, { search: 'plex' });
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe('plex-server');
  });

  it('search matches app_name', () => {
    const result = filterGuests(guests, { search: 'Home Assistant' });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('4');
  });

  it('search is case insensitive', () => {
    const result = filterGuests(guests, { search: 'SONARR' });
    expect(result).toHaveLength(1);
  });

  it('combines filters', () => {
    const result = filterGuests(guests, { status: 'outdated', type: 'lxc' });
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe('radarr-ct');
  });

  it('hides up-to-date when filter is outdated', () => {
    const result = filterGuests(guests, { status: 'outdated' });
    expect(result.some((g) => g.update_status === 'up-to-date')).toBe(false);
  });
});
