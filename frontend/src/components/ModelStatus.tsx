import type { ModelHealth } from '../api/types';
import { Spinner, StatusDot } from './ui';

export function ModelStatus({
  health,
  checking,
  onRefresh,
}: {
  health: ModelHealth | null;
  checking: boolean;
  onRefresh: () => void;
}) {
  const state = health === null ? 'unknown' : health.online ? 'online' : 'offline';
  return (
    <div className="card space-y-1 p-3 text-xs" data-testid="model-status">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 font-medium">
          <StatusDot status={state} />
          {state === 'online'
            ? 'Model online'
            : state === 'offline'
              ? 'Model offline'
              : 'Checking…'}
        </span>
        <button
          className="text-slate-400 hover:text-white"
          onClick={onRefresh}
          aria-label="Ping model"
          title="Ping now"
        >
          {checking ? <Spinner /> : '↻'}
        </button>
      </div>
      {health && (
        <div className="text-slate-400">
          <div className="truncate" title={health.base_url}>
            {health.provider} · {health.base_url}
          </div>
          {health.online ? (
            <div>
              {health.latency_ms} ms · {health.models.length} model
              {health.models.length === 1 ? '' : 's'}
            </div>
          ) : (
            <div className="line-clamp-2 text-red-300" title={health.error ?? ''}>
              {health.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
