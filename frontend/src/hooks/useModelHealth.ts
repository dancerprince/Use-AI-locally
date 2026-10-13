import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { ModelHealth } from '../api/types';

/** Polls the local model through the backend every ``intervalMs``. */
export function useModelHealth(intervalMs = 10_000) {
  const [health, setHealth] = useState<ModelHealth | null>(null);
  const [checking, setChecking] = useState(false);
  const tick = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    let cancelled = false;
    let ctrl: AbortController | null = null;
    tick.current = async () => {
      ctrl?.abort();
      ctrl = new AbortController();
      setChecking(true);
      try {
        const h = await api.health(ctrl.signal);
        if (!cancelled) setHealth(h);
      } catch (e) {
        if (!cancelled && !(e instanceof DOMException && e.name === 'AbortError')) {
          setHealth({
            online: false,
            provider: '?',
            base_url: '',
            latency_ms: null,
            models: [],
            error: e instanceof Error ? e.message : 'Backend unreachable',
          });
        }
      } finally {
        if (!cancelled) setChecking(false);
      }
    };
    void tick.current();
    const id = setInterval(() => void tick.current(), intervalMs);
    const onVis = () => document.visibilityState === 'visible' && void tick.current();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      cancelled = true;
      ctrl?.abort();
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [intervalMs]);

  return { health, checking, refresh: () => tick.current() };
}
