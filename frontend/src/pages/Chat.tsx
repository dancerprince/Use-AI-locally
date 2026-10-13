import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, streamChat } from '../api/client';
import type { ChatSession, ModelHealth } from '../api/types';
import { ErrorBanner, Spinner } from '../components/ui';

type Item =
  | { kind: 'user' | 'assistant'; content: string }
  | {
      kind: 'tool';
      id: string;
      name: string;
      args: unknown;
      result?: string;
      ok?: boolean;
      source?: string;
    }
  | { kind: 'error'; content: string };

export function ChatPage({ health }: { health: ModelHealth | null }) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState<string>('');
  const [useTools, setUseTools] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const refreshSessions = () =>
    api
      .sessions()
      .then(setSessions)
      .catch(() => {});
  useEffect(() => {
    void refreshSessions();
    api
      .getModelSettings()
      .then((s) => s.default_model && setModel((m) => m || s.default_model!))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!model && health?.models[0]) setModel(health.models[0]);
  }, [health, model]);
  // Effects must return nothing or a cleanup function — never another value.
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [items]);

  const openSession = async (id: string) => {
    setSessionId(id);
    setError(null);
    try {
      const msgs = await api.messages(id);
      const out: Item[] = [];
      for (const m of msgs) {
        if (m.role === 'user' || (m.role === 'assistant' && m.content))
          out.push({ kind: m.role, content: m.content });
        for (const c of m.tool_calls ?? [])
          out.push({ kind: 'tool', id: c.id, name: c.name, args: c.arguments });
        if (m.role === 'tool') {
          const t = out.find((i) => i.kind === 'tool' && i.id === m.tool_call_id);
          if (t && t.kind === 'tool') t.result = m.content;
        }
      }
      setItems(out);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setError(null);
    setBusy(true);
    setItems((p) => [...p, { kind: 'user', content: text }, { kind: 'assistant', content: '' }]);
    abort.current = new AbortController();
    try {
      for await (const ev of streamChat(
        { session_id: sessionId, message: text, model: model || null, use_tools: useTools },
        abort.current.signal,
      )) {
        if (ev.event === 'session') setSessionId(ev.data.session_id);
        else if (ev.event === 'delta')
          setItems((p) => {
            const last = p[p.length - 1];
            if (last?.kind === 'assistant')
              return [...p.slice(0, -1), { ...last, content: last.content + ev.data.content }];
            return [...p, { kind: 'assistant', content: ev.data.content }];
          });
        else if (ev.event === 'tool_call')
          setItems((p) => [
            ...p.filter(
              (i, idx) => !(idx === p.length - 1 && i.kind === 'assistant' && !i.content),
            ),
            {
              kind: 'tool',
              id: ev.data.id,
              name: ev.data.name,
              args: ev.data.arguments,
              source: ev.data.source,
            },
          ]);
        else if (ev.event === 'tool_result')
          setItems((p) => [
            ...p.map((i) =>
              i.kind === 'tool' && i.id === ev.data.id
                ? { ...i, result: ev.data.content, ok: ev.data.ok }
                : i,
            ),
            { kind: 'assistant', content: '' },
          ]);
        else if (ev.event === 'error')
          setItems((p) => [...p, { kind: 'error', content: ev.data.message }]);
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message);
    } finally {
      setItems((p) => p.filter((i) => !(i.kind === 'assistant' && !i.content)));
      setBusy(false);
      void refreshSessions();
    }
  };

  const newChat = () => {
    abort.current?.abort();
    setSessionId(null);
    setItems([]);
  };

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-800 p-3 md:flex">
        <button className="btn-primary mb-3 justify-center" onClick={newChat}>
          + New chat
        </button>
        <div className="flex-1 space-y-1 overflow-y-auto">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`group flex items-center rounded px-2 py-1.5 text-sm ${s.id === sessionId ? 'bg-slate-800' : 'hover:bg-slate-900'}`}
            >
              <button
                className="flex-1 truncate text-left"
                onClick={() => void openSession(s.id)}
                title={s.title}
              >
                {s.title}
              </button>
              <button
                className="hidden text-slate-500 hover:text-red-400 group-hover:block"
                aria-label="Delete chat"
                onClick={async () => {
                  if (!confirm('Delete this chat?')) return;
                  await api.deleteSession(s.id);
                  if (s.id === sessionId) newChat();
                  void refreshSessions();
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-4 py-2 text-sm">
          <label className="flex items-center gap-2">
            Model
            <select
              className="input w-56 py-1"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              aria-label="Model"
            >
              {!health?.models.includes(model) && model && <option value={model}>{model}</option>}
              {health?.models.map((m) => (
                <option key={m}>{m}</option>
              ))}
              {!model && <option value="">No models found</option>}
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="checkbox"
              checked={useTools}
              onChange={(e) => setUseTools(e.target.checked)}
            />
            Use tools (MCP + connectors)
          </label>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {items.length === 0 && (
            <div className="mt-20 text-center text-slate-500">
              <p className="text-lg">Chat with your local model</p>
              <p className="text-sm">
                Active skills, MCP servers and connectors are applied automatically.
              </p>
              {health?.online && health.models.length === 0 && (
                <div className="mt-6">
                  <p className="mb-3 text-sm text-amber-300">No models are installed yet.</p>
                  <Link to="/models" className="btn-primary">
                    ⬇️ Download a model
                  </Link>
                </div>
              )}
            </div>
          )}
          {items.map((it, i) => (
            <Bubble key={i} item={it} />
          ))}
          {busy && <Spinner />}
          <div ref={bottom} />
        </div>

        {error && (
          <div className="px-4">
            <ErrorBanner message={error} />
          </div>
        )}
        <form
          className="flex gap-2 border-t border-slate-800 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <textarea
            className="input min-h-[44px] resize-none"
            rows={2}
            placeholder={
              health?.online === false
                ? 'Model is offline…'
                : 'Send a message (Enter to send, Shift+Enter for newline)'
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            aria-label="Message"
          />
          {busy ? (
            <button type="button" className="btn-danger" onClick={() => abort.current?.abort()}>
              Stop
            </button>
          ) : (
            <button className="btn-primary" disabled={!input.trim() || !model}>
              Send
            </button>
          )}
        </form>
      </section>
    </div>
  );
}

function Bubble({ item }: { item: Item }) {
  if (item.kind === 'tool') {
    return (
      <details className="ml-0 max-w-3xl rounded-md border border-slate-700 bg-slate-900 text-xs">
        <summary className="cursor-pointer px-3 py-2 text-slate-300">
          🔧 <span className="font-mono">{item.name}</span>
          {item.source && <span className="ml-2 text-slate-500">{item.source}</span>}
          <span className="ml-2">
            {item.result === undefined ? '…running' : item.ok === false ? '❌' : '✅'}
          </span>
        </summary>
        <div className="space-y-2 border-t border-slate-800 p-3 font-mono whitespace-pre-wrap">
          <div>
            <span className="text-slate-500">args:</span> {JSON.stringify(item.args, null, 2)}
          </div>
          {item.result !== undefined && (
            <div className="max-h-64 overflow-auto">
              <span className="text-slate-500">result:</span> {item.result}
            </div>
          )}
        </div>
      </details>
    );
  }
  if (item.kind === 'error') return <ErrorBanner message={item.content} />;
  const user = item.kind === 'user';
  return (
    <div className={`flex ${user ? 'justify-end' : ''}`}>
      <div
        className={`max-w-3xl rounded-lg px-4 py-2 text-sm whitespace-pre-wrap ${user ? 'bg-indigo-600' : 'bg-slate-800'}`}
      >
        {item.content}
      </div>
    </div>
  );
}
