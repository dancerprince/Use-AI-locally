import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { CatalogModel, InstalledModel, PullJob, RuntimeStatus } from '../api/types';
import { Empty, ErrorBanner, PageHeader, Spinner } from '../components/ui';
import { usePullProgress } from '../hooks/usePullProgress';

const fmtSize = (bytes: number) =>
  bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} GB`
    : `${(bytes / 1024 ** 2).toFixed(0)} MB`;

export function ModelsPage({ onChanged }: { onChanged?: () => void }) {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [installed, setInstalled] = useState<InstalledModel[]>([]);
  const [catalog, setCatalog] = useState<CatalogModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [unsupported, setUnsupported] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [custom, setCustom] = useState('');
  const [defaultModel, setDefaultModel] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [rt, settings] = await Promise.all([api.models.runtime(), api.getModelSettings()]);
      setRuntime(rt);
      setDefaultModel(settings.default_model ?? null);
      if (settings.provider !== 'ollama') {
        setUnsupported('Model downloads are only available with the Ollama provider.');
        return;
      }
      setUnsupported(null);
      setCatalog(await api.models.catalog());
      if (rt.running) setInstalled(await api.models.installed());
    } catch (e) {
      if (e instanceof ApiError && e.code === 'unsupported_provider') setUnsupported(e.message);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const onFinished = useCallback(
    (job: PullJob) => {
      if (!job.error) {
        void load();
        onChanged?.();
      }
    },
    [load, onChanged],
  );
  const { jobs, start, cancel, dismiss } = usePullProgress(onFinished);

  useEffect(() => {
    void load();
  }, [load]);

  const download = async (name: string) => {
    setError(null);
    try {
      await start(name);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async (name: string) => {
    if (!confirm(`Delete ${name}? You can download it again later.`)) return;
    try {
      await api.models.remove(name);
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const makeDefault = async (name: string) => {
    try {
      const s = await api.getModelSettings();
      await api.saveModelSettings({ ...s, default_model: name });
      setDefaultModel(name);
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const activeFor = (name: string) => jobs.find((j) => j.model === name && !j.done);

  if (loading)
    return (
      <div className="p-6">
        <Spinner />
      </div>
    );

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      <PageHeader
        title="Models"
        subtitle="Download models to this computer. They run fully offline once installed."
        action={
          <button className="btn-ghost" onClick={() => void load()}>
            ↻ Refresh
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {unsupported && <ErrorBanner message={unsupported} />}

      {runtime && !runtime.installed && (
        <div className="card border-amber-700 bg-amber-950/40 text-sm">
          <p className="font-medium text-amber-200">Ollama is not installed</p>
          <p className="mt-1 text-slate-300">
            Offline AI uses Ollama to run models locally. Install it, then click Refresh:
          </p>
          <pre className="mt-2 rounded bg-slate-950 p-2 font-mono text-xs">
            {runtime.install_hint}
          </pre>
        </div>
      )}
      {runtime?.installed && !runtime.running && (
        <div className="card border-amber-700 bg-amber-950/40 text-sm">
          <p className="font-medium text-amber-200">Ollama is installed but not running</p>
          <p className="mt-1 text-slate-300">
            Start it with <code className="font-mono">ollama serve</code> (or open the Ollama app),
            then click Refresh.
          </p>
        </div>
      )}

      {jobs.length > 0 && (
        <section className="space-y-2">
          <h2 className="font-semibold">Downloads</h2>
          {jobs.map((j) => (
            <div key={j.id} className="card text-sm" data-testid={`job-${j.model}`}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono">{j.model}</span>
                <span className="text-slate-400">
                  {j.error ?? j.status}
                  {j.total > 0 && !j.done && ` · ${fmtSize(j.completed)} / ${fmtSize(j.total)}`}
                </span>
                {j.done ? (
                  <button className="btn-ghost" onClick={() => dismiss(j.id)}>
                    Dismiss
                  </button>
                ) : (
                  <button className="btn-danger" onClick={() => void cancel(j.id)}>
                    Cancel
                  </button>
                )}
              </div>
              <div
                className="mt-2 h-2 overflow-hidden rounded bg-slate-800"
                role="progressbar"
                aria-valuenow={j.done && !j.error ? 100 : j.percent}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className={`h-full ${j.error ? 'bg-red-500' : 'bg-emerald-500'} transition-all`}
                  style={{ width: `${j.done && !j.error ? 100 : j.percent}%` }}
                />
              </div>
            </div>
          ))}
        </section>
      )}

      {!unsupported && (
        <>
          <section>
            <h2 className="mb-3 font-semibold">Installed</h2>
            {installed.length === 0 ? (
              <Empty title="No models installed" hint="Pick one below to get started." />
            ) : (
              <table className="w-full text-sm">
                <thead className="text-left text-slate-400">
                  <tr>
                    <th className="py-2">Name</th>
                    <th>Size</th>
                    <th>Params</th>
                    <th>Quant</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {installed.map((m) => (
                    <tr key={m.name} className="border-t border-slate-800">
                      <td className="py-2 font-mono">
                        {m.name}
                        {defaultModel === m.name && (
                          <span className="ml-2 rounded bg-emerald-900 px-1.5 text-xs">
                            default
                          </span>
                        )}
                      </td>
                      <td>{fmtSize(m.size)}</td>
                      <td>{m.parameter_size ?? '—'}</td>
                      <td>{m.quantization ?? '—'}</td>
                      <td className="space-x-2 text-right">
                        {defaultModel !== m.name && (
                          <button className="btn-ghost" onClick={() => void makeDefault(m.name)}>
                            Set default
                          </button>
                        )}
                        <button
                          className="btn-danger"
                          aria-label={`Delete ${m.name}`}
                          onClick={() => void remove(m.name)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h2 className="mb-3 font-semibold">Recommended</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {catalog.map((c) => {
                const active = activeFor(c.name);
                return (
                  <div key={c.name} className="card flex flex-col gap-2 text-sm">
                    <div className="font-medium">{c.title}</div>
                    <div className="font-mono text-xs text-slate-400">{c.name}</div>
                    <p className="flex-1 text-slate-300">{c.description}</p>
                    <div className="flex flex-wrap gap-1 text-xs">
                      <span className="rounded bg-slate-800 px-1.5">{c.size_gb} GB</span>
                      <span className="rounded bg-slate-800 px-1.5">{c.min_ram_gb} GB RAM</span>
                      {c.tools && <span className="rounded bg-indigo-900 px-1.5">tools</span>}
                      {c.tags.map((t) => (
                        <span key={t} className="rounded bg-slate-800 px-1.5">
                          {t}
                        </span>
                      ))}
                    </div>
                    {c.installed ? (
                      <span className="text-emerald-400">✓ Installed</span>
                    ) : (
                      <button
                        className="btn-primary justify-center"
                        disabled={!!active || !runtime?.running}
                        onClick={() => void download(c.name)}
                        aria-label={`Download ${c.name}`}
                      >
                        {active ? `Downloading… ${active.percent}%` : '⬇️ Download'}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <section>
            <h2 className="mb-3 font-semibold">Custom model</h2>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (custom.trim()) void download(custom.trim()).then(() => setCustom(''));
              }}
            >
              <input
                className="input"
                placeholder="Any Ollama model, e.g. deepseek-r1:7b"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                aria-label="Custom model name"
              />
              <button className="btn-primary" disabled={!custom.trim() || !runtime?.running}>
                Download
              </button>
            </form>
            <p className="mt-2 text-xs text-slate-500">
              Browse models at ollama.com/library. Downloads are saved on this computer.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
