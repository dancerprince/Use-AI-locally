import { useState } from 'react';
import { api } from '../api/client';
import type { Skill, SkillIn } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { Empty, ErrorBanner, Modal, PageHeader, Spinner, Toggle } from '../components/ui';

const blank: SkillIn = { name: '', description: '', instructions: '', tools: [], enabled: true };

export function SkillsPage() {
  const { data, error, loading, reload } = useAsync(() => api.skills.list());
  const [editing, setEditing] = useState<Skill | 'new' | null>(null);

  return (
    <div className="p-6">
      <PageHeader
        title="AI skills"
        subtitle="Reusable instructions injected into the system prompt when enabled. Link tools the skill should prefer."
        action={
          <button className="btn-primary" onClick={() => setEditing('new')}>
            + Add skill
          </button>
        }
      />
      {loading && !data && <Spinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {data?.length === 0 && (
        <Empty
          title="No skills yet"
          hint='e.g. "code-reviewer": Review code for bugs, security and style.'
        />
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map((s) => (
          <div key={s.id} className="card">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-medium">{s.name}</div>
                <div className="text-sm text-slate-400">
                  {s.description || <em>No description</em>}
                </div>
              </div>
              <Toggle
                label="Enabled"
                checked={s.enabled}
                onChange={async (v) => {
                  await api.skills.toggle(s.id, v);
                  void reload();
                }}
              />
            </div>
            <pre className="mt-2 line-clamp-3 text-xs whitespace-pre-wrap text-slate-400">
              {s.instructions}
            </pre>
            {s.tools.length > 0 && (
              <div className="mt-2 text-xs text-indigo-300">Tools: {s.tools.join(', ')}</div>
            )}
            <div className="mt-3 flex gap-2">
              <button className="btn-ghost" onClick={() => setEditing(s)}>
                Edit
              </button>
              <button
                className="btn-danger"
                onClick={async () => {
                  if (confirm(`Delete skill "${s.name}"?`)) {
                    await api.skills.remove(s.id);
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
        <SkillForm
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

function SkillForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Skill | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [f, setF] = useState<SkillIn>(initial ?? blank);
  const [err, setErr] = useState<string | null>(null);
  const tools = useAsync(() => api.tools());

  const save = async () => {
    setErr(null);
    try {
      const body: SkillIn = {
        name: f.name,
        description: f.description,
        instructions: f.instructions,
        tools: f.tools,
        enabled: f.enabled,
      };
      if (initial) await api.skills.update(initial.id, body);
      else await api.skills.create(body);
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <Modal title={initial ? `Edit ${initial.name}` : 'Add skill'} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div>
          <label className="label" htmlFor="s-name">
            Name
          </label>
          <input
            id="s-name"
            className="input"
            required
            pattern="[a-z0-9]([a-z0-9\-]{0,30}[a-z0-9])?"
            value={f.name}
            onChange={(e) => setF({ ...f, name: e.target.value.toLowerCase() })}
          />
        </div>
        <div>
          <label className="label" htmlFor="s-desc">
            Description
          </label>
          <input
            id="s-desc"
            className="input"
            maxLength={500}
            value={f.description}
            onChange={(e) => setF({ ...f, description: e.target.value })}
          />
        </div>
        <div>
          <label className="label" htmlFor="s-ins">
            Instructions (Markdown)
          </label>
          <textarea
            id="s-ins"
            className="input font-mono"
            rows={10}
            maxLength={32000}
            placeholder="You are an expert in… When asked to…, always…"
            value={f.instructions}
            onChange={(e) => setF({ ...f, instructions: e.target.value })}
          />
        </div>
        <div>
          <span className="label">Preferred tools</span>
          {tools.loading ? (
            <Spinner />
          ) : tools.data?.length ? (
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-800 p-2 text-sm">
              {tools.data.map((t) => (
                <label key={t.name} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={f.tools.includes(t.name)}
                    onChange={(e) =>
                      setF({
                        ...f,
                        tools: e.target.checked
                          ? [...f.tools, t.name]
                          : f.tools.filter((x) => x !== t.name),
                      })
                    }
                  />
                  <span className="font-mono text-indigo-300">{t.name}</span>
                  <span className="text-xs text-slate-500">{t.source}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              No tools available — connect an MCP server or add a connector first.
            </p>
          )}
        </div>
        {err && <ErrorBanner message={err} />}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary">Save</button>
        </div>
      </form>
    </Modal>
  );
}
