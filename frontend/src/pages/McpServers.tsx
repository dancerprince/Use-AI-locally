import { useState } from 'react';
import { ApiError, api } from '../api/client';
import type { McpServer, McpServerIn, Transport } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import {
  Empty,
  ErrorBanner,
  KeyValueEditor,
  Modal,
  PageHeader,
  Spinner,
  StatusDot,
  Toggle,
} from '../components/ui';

const blank: McpServerIn = {
  name: '',
  transport: 'stdio',
  command: 'npx',
  args: [],
  env: {},
  url: '',
  headers: {},
  enabled: true,
};

export function McpServersPage() {
  const { data, error, loading, reload } = useAsync(() => api.mcp.list());
  const [editing, setEditing] = useState<McpServer | 'new' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError((e as Error).message);
    }
    void reload();
  };

  return (
    <div className="p-6">
      <PageHeader
        title="MCP servers"
        subtitle="Model Context Protocol servers expose tools to your local model (stdio, SSE or streamable HTTP)."
        action={
          <button className="btn-primary" onClick={() => setEditing('new')}>
            + Add server
          </button>
        }
      />
      {notice && <p className="mb-3 text-sm text-emerald-300">{notice}</p>}
      {actionError && (
        <div className="mb-3">
          <ErrorBanner message={actionError} />
        </div>
      )}
      {loading && !data && <Spinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {data?.length === 0 && (
        <Empty
          title="No MCP servers yet"
          hint="Try: npx -y @modelcontextprotocol/server-filesystem /path/to/folder"
        />
      )}
      <div className="space-y-3">
        {data?.map((s) => (
          <div key={s.id} className="card">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 font-medium">
                  <StatusDot status={s.status} /> {s.name}
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-400">
                    {s.transport}
                  </span>
                  <span className="text-xs text-slate-500">{s.status}</span>
                </div>
                <div className="mt-1 truncate font-mono text-xs text-slate-400">
                  {s.transport === 'stdio' ? `${s.command} ${s.args.join(' ')}` : s.url}
                </div>
                {s.last_error && <div className="mt-1 text-xs text-red-300">{s.last_error}</div>}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Toggle
                  label="Enabled"
                  checked={s.enabled}
                  onChange={(v) => act(() => api.mcp.toggle(s.id, v))}
                />
                <button
                  className="btn-ghost"
                  onClick={() =>
                    act(async () => {
                      const r = await api.mcp.test(s.id);
                      setNotice(`${s.name}: ${r.message}`);
                    })
                  }
                >
                  Test
                </button>
                <button className="btn-ghost" onClick={() => setEditing(s)}>
                  Edit
                </button>
                <button
                  className="btn-danger"
                  onClick={() =>
                    confirm(`Delete MCP server "${s.name}"?`) && act(() => api.mcp.remove(s.id))
                  }
                >
                  Delete
                </button>
              </div>
            </div>
            {s.tools.length > 0 && (
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-slate-400">{s.tools.length} tools</summary>
                <ul className="mt-2 space-y-1">
                  {s.tools.map((t) => (
                    <li key={t.name}>
                      <span className="font-mono text-indigo-300">{t.name}</span>{' '}
                      <span className="text-slate-400">— {t.description}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ))}
      </div>
      {editing && (
        <McpForm
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

function McpForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: McpServer | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [f, setF] = useState<McpServerIn>(initial ? { ...initial, url: initial.url ?? '' } : blank);
  const [argsText, setArgsText] = useState((initial?.args ?? []).join('\n'));
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof McpServerIn>(k: K, v: McpServerIn[K]) =>
    setF((p) => ({ ...p, [k]: v }));

  const save = async (confirmed = false) => {
    setErr(null);
    setSaving(true);
    const body: McpServerIn = {
      ...f,
      args: argsText
        .split('\n')
        .map((a) => a.trim())
        .filter(Boolean),
      url: f.transport === 'stdio' ? null : f.url,
      command: f.transport === 'stdio' ? f.command : null,
      confirmed,
    };
    try {
      if (initial) await api.mcp.update(initial.id, body);
      else await api.mcp.create(body);
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'confirmation_required') {
        const cmd = `${body.command} ${body.args.join(' ')}`;
        if (
          confirm(
            `This will execute a local command on your machine:\n\n${cmd}\n\nOnly continue if you trust it.`,
          )
        )
          return save(true);
      } else setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={initial ? `Edit ${initial.name}` : 'Add MCP server'} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label" htmlFor="mcp-name">
              Name
            </label>
            <input
              id="mcp-name"
              className="input"
              required
              pattern="[a-z0-9]([a-z0-9\-]{0,30}[a-z0-9])?"
              placeholder="filesystem"
              value={f.name}
              onChange={(e) => set('name', e.target.value.toLowerCase())}
            />
          </div>
          <div>
            <label className="label" htmlFor="mcp-transport">
              Transport
            </label>
            <select
              id="mcp-transport"
              className="input"
              value={f.transport}
              onChange={(e) => set('transport', e.target.value as Transport)}
            >
              <option value="stdio">stdio (local command)</option>
              <option value="http">Streamable HTTP</option>
              <option value="sse">SSE (legacy)</option>
            </select>
          </div>
        </div>
        {f.transport === 'stdio' ? (
          <>
            <div>
              <label className="label" htmlFor="mcp-cmd">
                Command
              </label>
              <input
                id="mcp-cmd"
                className="input font-mono"
                required
                value={f.command ?? ''}
                onChange={(e) => set('command', e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="mcp-args">
                Arguments (one per line)
              </label>
              <textarea
                id="mcp-args"
                className="input font-mono"
                rows={3}
                placeholder={'-y\n@modelcontextprotocol/server-filesystem\n/home/me/docs'}
                value={argsText}
                onChange={(e) => setArgsText(e.target.value)}
              />
            </div>
            <div>
              <span className="label">Environment variables (encrypted)</span>
              <KeyValueEditor secret value={f.env} onChange={(v) => set('env', v)} />
            </div>
          </>
        ) : (
          <>
            <div>
              <label className="label" htmlFor="mcp-url">
                URL
              </label>
              <input
                id="mcp-url"
                className="input font-mono"
                required
                type="url"
                placeholder="http://localhost:3001/mcp"
                value={f.url ?? ''}
                onChange={(e) => set('url', e.target.value)}
              />
            </div>
            <div>
              <span className="label">Headers (encrypted)</span>
              <KeyValueEditor
                secret
                keyPlaceholder="Authorization"
                value={f.headers}
                onChange={(v) => set('headers', v)}
              />
            </div>
          </>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={f.enabled}
            onChange={(e) => set('enabled', e.target.checked)}
          />{' '}
          Connect now
        </label>
        {err && <ErrorBanner message={err} />}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={saving}>
            {saving ? <Spinner /> : null} Save
          </button>
        </div>
      </form>
    </Modal>
  );
}
