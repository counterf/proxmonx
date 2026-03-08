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

  const load = useCallback(async () => {
    try {
      const data = await fetchGuests();
      setGuests(data);
      setLastRefreshed(new Date());
      setError(null);
    } catch (err) {
      if (err instanceof HttpError && err.status === 503) {
        setError('not_configured');
      } else {
        const message = err instanceof Error ? err.message : 'Failed to load guests';
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await triggerRefresh();
      // Wait briefly for the backend to start processing, then poll
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await load();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Refresh failed';
      setError(message);
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, POLL_INTERVAL);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [load]);

  return { guests, loading, error, refreshing, lastRefreshed, refresh };
}
