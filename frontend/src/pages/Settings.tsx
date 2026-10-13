import { useState } from 'react';
import { api, getToken, setToken } from '../api/client';
import type { ModelHealth, ModelSettings } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { ErrorBanner, PageHeader, Spinner } from '../components/ui';

const PRESETS: Record<string, Pick<ModelSettings, 'provider' | 'base_url'>> = {
  Ollama: { provider: 'ollama', base_url: 'http://localhost:11434' },
  'LM Studio': { provider: 'openai', base_url: 'http://localhost:1234/v1' },
  'llama.cpp server': { provider: 'openai', base_url: 'http://localhost:8080/v1' },
  vLLM: { provider: 'openai', base_url: 'http://localhost:8001/v1' },
};

export function SettingsPage({ onSaved }: { onSaved: () => void }) {
  const { data, error, loading, reload, setData } = useAsync(() => api.getModelSettings());
  const [test, setTest] = useState<ModelHealth | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [token, setTok] = useState(getToken());

  if (loading && !data)
    return (
      <div className="p-6">
        <Spinner />
      </div>
    );
  if (error || !data)
    return (
      <div className="p-6">
        <ErrorBanner message={error ?? 'Failed to load'} onRetry={reload} />
      </div>
    );
  const set = <K extends keyof ModelSettings>(k: K, v: ModelSettings[K]) =>
    setData({ ...data, [k]: v });

  return (
    <div className="max-w-2xl p-6">
      <PageHeader
        title="Settings"
        subtitle="Configure which local model runtime the app talks to."
      />
      <form
        className="card space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setErr(null);
          try {
            setData(await api.saveModelSettings(data));
            setMsg('Saved');
            onSaved();
          } catch (x) {
            setErr((x as Error).message);
          }
        }}
      >
        <div className="flex flex-wrap gap-2">
          {Object.entries(PRESETS).map(([k, p]) => (
            <button
              type="button"
              key={k}
              className="btn-ghost"
              onClick={() => setData({ ...data, ...p })}
            >
              {k}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="label" htmlFor="st-provider">
              API type
            </label>
            <select
              id="st-provider"
              className="input"
              value={data.provider}
              onChange={(e) => set('provider', e.target.value as ModelSettings['provider'])}
            >
              <option value="ollama">Ollama native</option>
              <option value="openai">OpenAI-compatible</option>
            </select>
          </div>
          <div className="col-span-2">
            <label className="label" htmlFor="st-url">
              Base URL
            </label>
            <input
              id="st-url"
              className="input font-mono"
              value={data.base_url}
              onChange={(e) => set('base_url', e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="st-key">
              API key (optional, encrypted)
            </label>
            <input
              id="st-key"
              className="input"
              type="password"
              value={data.api_key ?? ''}
              onChange={(e) => set('api_key', e.target.value || null)}
            />
          </div>
          <div>
            <label className="label" htmlFor="st-model">
              Default model
            </label>
            <input
              id="st-model"
              className="input font-mono"
              list="models"
              value={data.default_model ?? ''}
              onChange={(e) => set('default_model', e.target.value || null)}
            />
            <datalist id="models">
              {test?.models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="st-temp">
            Temperature: {data.temperature}
          </label>
          <input
            id="st-temp"
            type="range"
            min={0}
            max={2}
            step={0.1}
            className="w-full"
            value={data.temperature}
            onChange={(e) => set('temperature', Number(e.target.value))}
          />
        </div>
        <div>
          <label className="label" htmlFor="st-sys">
            Base system prompt
          </label>
          <textarea
            id="st-sys"
            className="input"
            rows={4}
            value={data.system_prompt}
            onChange={(e) => set('system_prompt', e.target.value)}
          />
        </div>
        {test && (
          <p className={`text-sm ${test.online ? 'text-emerald-300' : 'text-red-300'}`}>
            {test.online
              ? `✅ Reachable in ${test.latency_ms} ms — ${test.models.length} models`
              : `❌ ${test.error}`}
          </p>
        )}
        {err && <ErrorBanner message={err} />}
        {msg && <p className="text-sm text-emerald-300">{msg}</p>}
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-ghost"
            onClick={async () => {
              setErr(null);
              try {
                setTest(await api.testModelSettings(data));
              } catch (x) {
                setErr((x as Error).message);
              }
            }}
          >
            Test connection
          </button>
          <button className="btn-primary">Save</button>
        </div>
      </form>

      <div className="card mt-6 space-y-2">
        <label className="label" htmlFor="st-token">
          API token (only if the backend sets OAI_API_TOKEN)
        </label>
        <div className="flex gap-2">
          <input
            id="st-token"
            className="input"
            type="password"
            value={token}
            onChange={(e) => setTok(e.target.value)}
          />
          <button
            className="btn-ghost"
            onClick={() => {
              setToken(token);
              setMsg('Token stored in this browser');
              onSaved();
            }}
          >
            Store
          </button>
        </div>
      </div>
    </div>
  );
}
