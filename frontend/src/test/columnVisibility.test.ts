import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { ColumnKey } from '../hooks/useColumnVisibility';

const STORAGE_KEY = 'proxmon:visible-columns';

// Mock localStorage since jsdom in vitest 4.x does not provide a real one
const store: Record<string, string> = {};
const mockLocalStorage = {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
  removeItem: vi.fn((key: string) => { delete store[key]; }),
  clear: vi.fn(() => { Object.keys(store).forEach((k) => delete store[k]); }),
  get length() { return Object.keys(store).length; },
  key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
};

vi.stubGlobal('localStorage', mockLocalStorage);

beforeEach(() => {
  mockLocalStorage.clear();
  vi.clearAllMocks();
});

// Dynamic import to ensure the module reads fresh localStorage per test
async function loadModule() {
  // Force re-evaluation of the module
  const mod = await import('../hooks/useColumnVisibility');
  return mod;
}

describe('useColumnVisibility', () => {
  it('returns default visible columns on first load', async () => {
    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    const defaults = COLUMN_DEFS.filter((c) => c.defaultVisible).map((c) => c.key);
    for (const key of defaults) {
      expect(result.current.visibleColumns.has(key)).toBe(true);
    }
  });

  it('non-default columns are not visible initially', async () => {
    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    const hidden = COLUMN_DEFS.filter((c) => !c.defaultVisible).map((c) => c.key);
    for (const key of hidden) {
      expect(result.current.visibleColumns.has(key)).toBe(false);
    }
  });

  it('alwaysVisible columns cannot be hidden via toggleColumn', async () => {
    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    const alwaysVisible = COLUMN_DEFS.filter((c) => c.alwaysVisible).map((c) => c.key);
    expect(alwaysVisible.length).toBeGreaterThan(0);

    for (const key of alwaysVisible) {
      act(() => result.current.toggleColumn(key));
      expect(result.current.visibleColumns.has(key)).toBe(true);
    }
  });

  it('toggleColumn hides a visible column', async () => {
    const { useColumnVisibility } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    expect(result.current.visibleColumns.has('type')).toBe(true);

    act(() => result.current.toggleColumn('type'));
    expect(result.current.visibleColumns.has('type')).toBe(false);
  });

  it('toggleColumn shows a hidden column', async () => {
    const { useColumnVisibility } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    expect(result.current.visibleColumns.has('os_type')).toBe(false);

    act(() => result.current.toggleColumn('os_type'));
    expect(result.current.visibleColumns.has('os_type')).toBe(true);
  });

  it('persists to localStorage on toggle', async () => {
    const { useColumnVisibility } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());

    act(() => result.current.toggleColumn('type'));

    const stored = JSON.parse(store[STORAGE_KEY]) as ColumnKey[];
    expect(stored).not.toContain('type');
  });

  it('loads from localStorage on mount', async () => {
    // Pre-set localStorage with only 'app_name' visible
    store[STORAGE_KEY] = JSON.stringify(['app_name']);

    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());

    expect(result.current.visibleColumns.has('app_name')).toBe(true);
    // 'type' was not in saved list and is not alwaysVisible
    expect(result.current.visibleColumns.has('type')).toBe(false);
    // alwaysVisible columns should still be present
    const alwaysVisible = COLUMN_DEFS.filter((c) => c.alwaysVisible).map((c) => c.key);
    for (const key of alwaysVisible) {
      expect(result.current.visibleColumns.has(key)).toBe(true);
    }
  });

  it('falls back to defaults on invalid localStorage data', async () => {
    store[STORAGE_KEY] = 'not-json';

    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    const defaults = COLUMN_DEFS.filter((c) => c.defaultVisible).map((c) => c.key);
    for (const key of defaults) {
      expect(result.current.visibleColumns.has(key)).toBe(true);
    }
  });

  it('falls back to defaults on empty array in localStorage', async () => {
    store[STORAGE_KEY] = JSON.stringify([]);

    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());
    const defaults = COLUMN_DEFS.filter((c) => c.defaultVisible).map((c) => c.key);
    for (const key of defaults) {
      expect(result.current.visibleColumns.has(key)).toBe(true);
    }
  });

  it('resetToDefaults restores default visibility', async () => {
    const { useColumnVisibility, COLUMN_DEFS } = await loadModule();
    const { result } = renderHook(() => useColumnVisibility());

    act(() => result.current.toggleColumn('type'));
    act(() => result.current.toggleColumn('os_type'));
    expect(result.current.visibleColumns.has('type')).toBe(false);
    expect(result.current.visibleColumns.has('os_type')).toBe(true);

    act(() => result.current.resetToDefaults());

    const defaults = COLUMN_DEFS.filter((c) => c.defaultVisible).map((c) => c.key);
    for (const key of defaults) {
      expect(result.current.visibleColumns.has(key)).toBe(true);
    }
    const hidden = COLUMN_DEFS.filter((c) => !c.defaultVisible).map((c) => c.key);
    for (const key of hidden) {
      expect(result.current.visibleColumns.has(key)).toBe(false);
    }
  });
});
