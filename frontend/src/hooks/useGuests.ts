import { useState, useEffect, useCallback, useRef } from 'react';
import type { Guest } from '../types';
import { fetchGuests, triggerRefresh, fetchHealth, HttpError } from '../api/client';

interface UseGuestsResult {
  guests: Guest[];
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  isDiscovering: boolean;
  lastRefreshed: Date | null;
  refresh: () => Promise<void>;
}

const POLL_INTERVAL = 60_000; // 60 seconds

export function useGuests(): UseGuestsResult {
  const [guests, setGuests] = useState<Guest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await fetchGuests();
      if (!mountedRef.current) return;
      setGuests(data);
      setLastRefreshed(new Date());
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof HttpError && err.status === 401) {
        // Session expired — stop polling to avoid log spam.
        // AUTH_UNAUTHORIZED_EVENT dispatched by fetchJson is consumed by App.tsx
        // which handles navigation via React Router.
        stopPolling();
        return;
      }
      if (err instanceof HttpError && err.status === 503) {
        setError('not_configured');
      } else {
        const message = err instanceof Error ? err.message : 'Failed to load guests';
        setError(message);
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [stopPolling]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const { status, snapshot_at } = await triggerRefresh();
      if (status === 'busy') {
        // Discovery already running — just reload current data
        await load();
        return;
      }
      setIsDiscovering(true);
      const deadline = Date.now() + 30_000;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1_500));
        if (!mountedRef.current) return;
        try {
          const health = await fetchHealth();
          if (health.last_poll && (!snapshot_at || health.last_poll > snapshot_at)) break;
        } catch (err) {
          if (err instanceof HttpError && err.status === 401) return;
          // ignore other transient health check errors
        }
      }
      await load();
    } catch (err) {
      if (!mountedRef.current) return;
      const message = err instanceof Error ? err.message : 'Refresh failed';
      setError(message);
    } finally {
      if (mountedRef.current) {
        setRefreshing(false);
        setIsDiscovering(false);
      }
    }
  }, [load]);

  useEffect(() => {
    mountedRef.current = true;
    load();
    intervalRef.current = setInterval(load, POLL_INTERVAL);
    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [load, stopPolling]);

  return { guests, loading, error, refreshing, isDiscovering, lastRefreshed, refresh };
}
