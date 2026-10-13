import type {
  CatalogModel,
  InstalledModel,
  PullJob,
  RuntimeStatus,
  ChatEvent,
  ChatMessage,
  ChatSession,
  Connector,
  ConnectorIn,
  McpServer,
  McpServerIn,
  ModelHealth,
  ModelSettings,
  Skill,
  SkillIn,
  TestResult,
  ToolInfo,
} from './types';

export const MASK = '••••••••';

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

const TOKEN_KEY = 'oai_token';
export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? '';
export const setToken = (t: string) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

function headers(json = true): HeadersInit {
  const h: Record<string, string> = {};
  if (json) h['Content-Type'] = 'application/json';
  const t = getToken();
  if (t) h.Authorization = `Bearer ${t}`;
  return h;
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const e = body?.error ?? {};
    let msg: string = e.message ?? res.statusText;
    if (Array.isArray(e.details) && e.details.length) {
      msg +=
        ': ' +
        e.details
          .map((d: { loc?: unknown[]; msg?: string }) =>
            `${(d.loc ?? []).slice(1).join('.')} ${d.msg ?? ''}`.trim(),
          )
          .join('; ');
    }
    return new ApiError(res.status, e.code ?? 'error', msg, e.details);
  } catch {
    return new ApiError(res.status, 'error', res.statusText || `HTTP ${res.status}`);
  }
}

async function req<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: headers(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await toError(res);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

function crud<TIn, TOut>(base: string) {
  return {
    list: () => req<TOut[]>('GET', base),
    create: (b: TIn) => req<TOut>('POST', base, b),
    update: (id: number, b: TIn) => req<TOut>('PUT', `${base}/${id}`, b),
    toggle: (id: number, enabled: boolean) =>
      req<TOut>('PATCH', `${base}/${id}/enabled`, { enabled }),
    remove: (id: number) => req<void>('DELETE', `${base}/${id}`),
  };
}

export const api = {
  health: (signal?: AbortSignal) => req<ModelHealth>('GET', '/health/model', undefined, signal),
  getModelSettings: () => req<ModelSettings>('GET', '/settings/model'),
  saveModelSettings: (s: ModelSettings) => req<ModelSettings>('PUT', '/settings/model', s),
  testModelSettings: (s: ModelSettings) => req<ModelHealth>('POST', '/settings/model/test', s),

  mcp: {
    ...crud<McpServerIn, McpServer>('/mcp-servers'),
    test: (id: number) => req<TestResult>('POST', `/mcp-servers/${id}/test`),
    reconnect: (id: number) => req<McpServer>('POST', `/mcp-servers/${id}/reconnect`),
  },
  connectors: {
    ...crud<ConnectorIn, Connector>('/connectors'),
    test: (id: number) => req<TestResult>('POST', `/connectors/${id}/test`),
  },
  skills: crud<SkillIn, Skill>('/skills'),
  tools: () => req<ToolInfo[]>('GET', '/tools'),

  models: {
    runtime: () => req<RuntimeStatus>('GET', '/health/runtime'),
    installed: () => req<InstalledModel[]>('GET', '/models'),
    catalog: () => req<CatalogModel[]>('GET', '/models/catalog'),
    pulls: () => req<PullJob[]>('GET', '/models/pulls'),
    pull: (name: string) => req<PullJob & { job_id: string }>('POST', '/models/pull', { name }),
    cancel: (jobId: string) => req<PullJob>('DELETE', `/models/pull/${jobId}`),
    remove: (name: string) => req<void>('DELETE', `/models/${encodeURIComponent(name)}`),
  },

  sessions: () => req<ChatSession[]>('GET', '/chat/sessions'),
  messages: (id: string) => req<ChatMessage[]>('GET', `/chat/sessions/${id}/messages`),
  deleteSession: (id: string) => req<void>('DELETE', `/chat/sessions/${id}`),
};

/** Stream download-progress snapshots (fetch-based so the bearer token is sent). */
export async function* streamPull(jobId: string, signal?: AbortSignal): AsyncGenerator<PullJob> {
  const res = await fetch(`/api/models/pull/${jobId}/events`, { headers: headers(false), signal });
  if (!res.ok || !res.body) throw await toError(res);
  for await (const evt of parseSse(res.body)) yield evt.data as unknown as PullJob;
}

/** POST /api/chat and yield parsed SSE events. */
export async function* streamChat(
  body: { session_id?: string | null; message: string; model?: string | null; use_tools?: boolean },
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw await toError(res);
  yield* parseSse(res.body);
}

export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      let data = '';
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7);
        else if (line.startsWith('data: ')) data += line.slice(6);
      }
      if (data) yield { event, data: JSON.parse(data) } as ChatEvent;
    }
  }
}
