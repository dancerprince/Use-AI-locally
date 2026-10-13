import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelsPage } from '../pages/Models';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const sse = (events: unknown[]) =>
  new Response(
    new ReadableStream({
      start(c) {
        const enc = new TextEncoder();
        for (const e of events)
          c.enqueue(enc.encode(`event: progress\ndata: ${JSON.stringify(e)}\n\n`));
        c.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );

const job = (over: object) => ({
  id: 'j1',
  model: 'phi4-mini',
  status: 'downloading',
  completed: 50,
  total: 100,
  percent: 50,
  done: false,
  error: null,
  started_at: 0,
  ...over,
});

function mockApi(installed = [{ name: 'llama3.2:3b', size: 2e9, parameter_size: '3B' }]) {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const m = init?.method ?? 'GET';
      calls.push(`${m} ${url}`);
      if (url === '/api/health/runtime')
        return json({ installed: true, running: true, version: '0.5', install_hint: '' });
      if (url === '/api/settings/model')
        return json({ provider: 'ollama', base_url: 'http://x', default_model: null });
      if (url === '/api/models/catalog')
        return json([
          {
            name: 'phi4-mini',
            title: 'Phi-4 Mini',
            size_gb: 2.5,
            min_ram_gb: 8,
            tools: true,
            tags: [],
            description: 'd',
            installed: false,
          },
        ]);
      if (url === '/api/models/pulls') return json([]);
      if (url === '/api/models' && m === 'GET') return json(installed);
      if (url === '/api/models/pull') return json({ job_id: 'j1', ...job({ percent: 0 }) }, 202);
      if (url.endsWith('/events'))
        return sse([job({}), job({ status: 'success', done: true, percent: 100 })]);
      if (m === 'DELETE') return new Response(null, { status: 204 });
      return json({}, 404);
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe('ModelsPage', () => {
  it('lists installed and recommended models', async () => {
    mockApi();
    render(<ModelsPage />);
    expect(await screen.findByText('llama3.2:3b')).toBeInTheDocument();
    expect(screen.getByText('Phi-4 Mini')).toBeInTheDocument();
  });

  it('downloads a model and shows progress', async () => {
    const calls = mockApi();
    const onChanged = vi.fn();
    render(<ModelsPage onChanged={onChanged} />);
    fireEvent.click(await screen.findByLabelText('Download phi4-mini'));
    expect(await screen.findByTestId('job-phi4-mini')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('success')).toBeInTheDocument());
    expect(calls).toContain('POST /api/models/pull');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('deletes a model after confirmation', async () => {
    const calls = mockApi();
    vi.stubGlobal('confirm', () => true);
    render(<ModelsPage />);
    fireEvent.click(await screen.findByLabelText('Delete llama3.2:3b'));
    await waitFor(() => expect(calls).toContain('DELETE /api/models/llama3.2%3A3b'));
  });
});
