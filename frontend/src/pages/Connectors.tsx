import { useState } from 'react';
import { MASK, api } from '../api/client';
import type { Connector, ConnectorIn, ConnectorType } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import {
  Empty,
  ErrorBanner,
  KeyValueEditor,
  Modal,
  PageHeader,
  Spinner,
  Toggle,
} from '../components/ui';

type Field = {
  key: string;
  label: string;
  kind: 'text' | 'number' | 'bool' | 'kv' | 'secret' | 'methods';
  placeholder?: string;
  required?: boolean;
};

/** UI form definitions per connector type (mirrors backend Config models). */
export const CONNECTOR_FIELDS: Record<
  ConnectorType,
  { label: string; help: string; fields: Field[]; defaults: Record<string, unknown> }
> = {
  http: {
    label: 'REST API',
    help: 'Lets the model call a REST API under a fixed base URL.',
    defaults: { base_url: '', headers: {}, allowed_methods: ['GET'], timeout_s: 20 },
    fields: [
      {
        key: 'base_url',
        label: 'Base URL',
        kind: 'text',
        placeholder: 'https://api.example.com',
        required: true,
      },
      { key: 'allowed_methods', label: 'Allowed methods', kind: 'methods' },
      { key: 'headers', label: 'Headers (encrypted)', kind: 'kv' },
      { key: 'timeout_s', label: 'Timeout (s)', kind: 'number' },
    ],
  },
  filesystem: {
    label: 'Local folder',
    help: 'Read (optionally write) files inside one sandboxed folder.',
    defaults: { root: '', allow_write: false, max_file_bytes: 1_000_000 },
    fields: [
      {
        key: 'root',
        label: 'Root folder (absolute path)',
        kind: 'text',
        placeholder: '/home/me/notes',
        required: true,
      },
      { key: 'allow_write', label: 'Allow writes', kind: 'bool' },
      { key: 'max_file_bytes', label: 'Max file size (bytes)', kind: 'number' },
    ],
  },
  sqlite: {
    label: 'SQLite (read-only)',
    help: 'Run read-only SELECT queries against a SQLite file.',
    defaults: { path: '', max_rows: 200, timeout_s: 10 },
    fields: [
      {
        key: 'path',
        label: 'Database file',
        kind: 'text',
        placeholder: '/home/me/app.db',
        required: true,
      },
      { key: 'max_rows', label: 'Max rows', kind: 'number' },
    ],
  },
  postgres: {
    label: 'PostgreSQL (read-only)',
    help: 'Read-only transaction with a statement timeout. Requires the backend "postgres" extra.',
    defaults: { dsn: '', max_rows: 200, statement_timeout_ms: 10_000 },
    fields: [
      {
        key: 'dsn',
        label: 'DSN (encrypted)',
        kind: 'secret',
        placeholder: 'postgresql://user:pass@localhost/db',
        required: true,
      },
      { key: 'max_rows', label: 'Max rows', kind: 'number' },
      { key: 'statement_timeout_ms', label: 'Statement timeout (ms)', kind: 'number' },
    ],
  },
  webhook: {
    label: 'Webhook',
    help: 'Lets the model POST a JSON payload to a URL (e.g. n8n, Home Assistant).',
    defaults: { url: '', headers: {}, description: 'Send a JSON payload to a webhook.' },
    fields: [
      { key: 'url', label: 'Webhook URL', kind: 'text', required: true },
      { key: 'description', label: 'Tool description shown to the model', kind: 'text' },
      { key: 'headers', label: 'Headers (encrypted)', kind: 'kv' },
    ],
  },
};

export function ConnectorsPage() {
  const { data, error, loading, reload } = useAsync(() => api.connectors.list());
  const [editing, setEditing] = useState<Connector | 'new' | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; msg: string } | null>(null);

  return (
    <div className="p-6">
      <PageHeader
        title="Connectors"
        subtitle="Built-in integrations that expose safe, sandboxed tools to the model."
        action={
          <button className="btn-primary" onClick={() => setEditing('new')}>
            + Add connector
          </button>
        }
      />
      {notice && (
        <p className={`mb-3 text-sm ${notice.ok ? 'text-emerald-300' : 'text-red-300'}`}>
          {notice.msg}
        </p>
      )}
      {loading && !data && <Spinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {data?.length === 0 && (
        <Empty title="No connectors yet" hint="Add a local folder, database or REST API." />
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map((c) => (
          <div key={c.id} className="card">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-slate-400">{CONNECTOR_FIELDS[c.type].label}</div>
              </div>
              <Toggle
                label="Enabled"
                checked={c.enabled}
                onChange={async (v) => {
                  await api.connectors.toggle(c.id, v);
                  void reload();
                }}
              />
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {c.tools.map((t) => (
                <span
                  key={t}
                  className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-xs text-indigo-300"
                >
                  {t}
                </span>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <button
                className="btn-ghost"
                onClick={async () => {
                  const r = await api.connectors.test(c.id);
                  setNotice({ ok: r.ok, msg: `${c.name}: ${r.message}` });
                }}
              >
                Test
              </button>
              <button className="btn-ghost" onClick={() => setEditing(c)}>
                Edit
              </button>
              <button
                className="btn-danger"
                onClick={async () => {
                  if (confirm(`Delete connector "${c.name}"?`)) {
                    await api.connectors.remove(c.id);
                    void reload();
                  }
                }}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
      {editing && (
        <ConnectorForm
          initial={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}
    </div>
  );
}

function ConnectorForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Connector | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [f, setF] = useState<ConnectorIn>(
    initial ?? {
      name: '',
      type: 'filesystem',
      config: { ...CONNECTOR_FIELDS.filesystem.defaults },
      enabled: true,
    },
  );
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const def = CONNECTOR_FIELDS[f.type];
  const setCfg = (k: string, v: unknown) =>
    setF((p) => ({ ...p, config: { ...p.config, [k]: v } }));

  const save = async () => {
    setErr(null);
    setSaving(true);
    try {
      if (initial) await api.connectors.update(initial.id, f);
      else await api.connectors.create(f);
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={initial ? `Edit ${initial.name}` : 'Add connector'} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="c-name">
              Name
            </label>
            <input
              id="c-name"
              className="input"
              required
              pattern="[a-z0-9]([a-z0-9\-]{0,30}[a-z0-9])?"
              value={f.name}
              onChange={(e) => setF({ ...f, name: e.target.value.toLowerCase() })}
            />
          </div>
          <div>
            <label className="label" htmlFor="c-type">
              Type
            </label>
            <select
              id="c-type"
              className="input"
              value={f.type}
              disabled={!!initial}
              onChange={(e) => {
                const t = e.target.value as ConnectorType;
                setF({ ...f, type: t, config: { ...CONNECTOR_FIELDS[t].defaults } });
              }}
            >
              {Object.entries(CONNECTOR_FIELDS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-sm text-slate-400">{def.help}</p>
        {def.fields.map((fd) => {
          const v = f.config[fd.key];
          const id = `cf-${fd.key}`;
          return (
            <div key={fd.key}>
              {fd.kind !== 'bool' && (
                <label className="label" htmlFor={id}>
                  {fd.label}
                </label>
              )}
              {fd.kind === 'text' && (
                <input
                  id={id}
                  className="input"
                  required={fd.required}
                  placeholder={fd.placeholder}
                  value={String(v ?? '')}
                  onChange={(e) => setCfg(fd.key, e.target.value)}
                />
              )}
              {fd.kind === 'secret' && (
                <input
                  id={id}
                  className="input"
                  type="password"
                  required={fd.required}
                  placeholder={fd.placeholder}
                  value={String(v ?? '')}
                  onFocus={() => v === MASK && setCfg(fd.key, '')}
                  onChange={(e) => setCfg(fd.key, e.target.value)}
                />
              )}
              {fd.kind === 'number' && (
                <input
                  id={id}
                  className="input"
                  type="number"
                  value={Number(v ?? 0)}
                  onChange={(e) => setCfg(fd.key, Number(e.target.value))}
                />
              )}
              {fd.kind === 'bool' && (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(v)}
                    onChange={(e) => setCfg(fd.key, e.target.checked)}
                  />{' '}
                  {fd.label}
                </label>
              )}
              {fd.kind === 'kv' && (
                <KeyValueEditor
                  secret
                  keyPlaceholder="Header"
                  value={(v as Record<string, string>) ?? {}}
                  onChange={(nv) => setCfg(fd.key, nv)}
                />
              )}
              {fd.kind === 'methods' && (
                <div className="flex gap-3 text-sm">
                  {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => {
                    const list = (v as string[]) ?? [];
                    return (
                      <label key={m} className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          checked={list.includes(m)}
                          onChange={(e) =>
                            setCfg(
                              fd.key,
                              e.target.checked ? [...list, m] : list.filter((x) => x !== m),
                            )
                          }
                        />{' '}
                        {m}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        {err && <ErrorBanner message={err} />}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={saving}>
            {saving && <Spinner />} Save
          </button>
        </div>
      </form>
    </Modal>
  );
}
