import { useState, useCallback } from 'react';

export type ColumnKey =
  | 'name'
  | 'type'
  | 'host_label'
  | 'app_name'
  | 'installed_version'
  | 'latest_version'
  | 'update_status'
  | 'disk'
  | 'version_detection_method'
  | 'os_type'
  | 'last_checked';

export interface ColumnDef {
  key: ColumnKey;
  label: string;
  defaultVisible: boolean;
  alwaysVisible?: boolean;
  weight: number;
}

export const COLUMN_DEFS: ColumnDef[] = [
  { key: 'name', label: 'Guest Name', defaultVisible: true, alwaysVisible: true, weight: 3 },
  { key: 'type', label: 'Type', defaultVisible: true, weight: 1 },
  { key: 'host_label', label: 'Host', defaultVisible: true, weight: 2 },
  { key: 'app_name', label: 'App', defaultVisible: true, weight: 2.5 },
  { key: 'installed_version', label: 'Installed', defaultVisible: true, weight: 2 },
  { key: 'latest_version', label: 'Latest', defaultVisible: true, weight: 2 },
  { key: 'update_status', label: 'Status', defaultVisible: true, weight: 1.5 },
  { key: 'disk', label: 'Disk', defaultVisible: true, weight: 1.8 },
  { key: 'version_detection_method', label: 'Version Source', defaultVisible: false, weight: 1.5 },
  { key: 'os_type', label: 'OS', defaultVisible: false, weight: 1.2 },
  { key: 'last_checked', label: 'Last Checked', defaultVisible: true, weight: 2 },
];

const STORAGE_KEY = 'proxmon:visible-columns';

function loadDefaults(): ColumnKey[] {
  return COLUMN_DEFS.filter((c) => c.defaultVisible).map((c) => c.key);
}

function loadFromStorage(): Set<ColumnKey> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed: ColumnKey[] = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        const always = COLUMN_DEFS.filter((c) => c.alwaysVisible).map((c) => c.key);
        return new Set([...always, ...parsed]);
      }
    }
  } catch {
    // corrupted value -- fall through to defaults
  }
  return new Set(loadDefaults());
}

function saveToStorage(cols: Set<ColumnKey>) {
  const always = new Set(COLUMN_DEFS.filter((c) => c.alwaysVisible).map((c) => c.key));
  const toSave = [...cols].filter((k) => !always.has(k));
  localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
}

export function useColumnVisibility() {
  const [visibleColumns, setVisibleColumns] = useState<Set<ColumnKey>>(loadFromStorage);

  const toggleColumn = useCallback((key: ColumnKey) => {
    const def = COLUMN_DEFS.find((c) => c.key === key);
    if (def?.alwaysVisible) return;

    setVisibleColumns((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      saveToStorage(next);
      return next;
    });
  }, []);

  const resetToDefaults = useCallback(() => {
    const defaults = new Set(loadDefaults());
    saveToStorage(defaults);
    setVisibleColumns(defaults);
  }, []);

  return { visibleColumns, toggleColumn, resetToDefaults };
}
