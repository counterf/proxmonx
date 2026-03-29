import { useState, useEffect, useCallback, useRef } from 'react';
import type { GuestSummary } from '../types';
import { fetchGuests, triggerRefresh, HttpError } from '../api/client';

interface UseGuestsResult {
  guests: GuestSummary[];
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  lastRefreshed: Date | null;
  refresh: () => Promise<void>;
}

const POLL_INTERVAL = 60_000; // 60 seconds

export function useGuests(): UseGuestsResult {
  const [guests, setGuests] = useState<GuestSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
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
      await triggerRefresh();
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await load();
    } catch (err) {
      if (!mountedRef.current) return;
      const message = err instanceof Error ? err.message : 'Refresh failed';
      setError(message);
    } finally {
      if (mountedRef.current) {
        setRefreshing(false);
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

  return { guests, loading, error, refreshing, lastRefreshed, refresh };
}
