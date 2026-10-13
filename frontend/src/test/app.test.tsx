import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parseSse } from '../api/client';
import { ModelStatus } from '../components/ModelStatus';
import { KeyValueEditor } from '../components/ui';

describe('ModelStatus', () => {
  it('shows online state with latency', () => {
    render(
      <ModelStatus
        checking={false}
        onRefresh={() => {}}
        health={{
          online: true,
          provider: 'ollama',
          base_url: 'http://localhost:11434',
          latency_ms: 12,
          models: ['a', 'b'],
          error: null,
        }}
      />,
    );
    expect(screen.getByText('Model online')).toBeInTheDocument();
    expect(screen.getByText(/12 ms · 2 models/)).toBeInTheDocument();
  });

  it('shows offline error and pings on click', () => {
    const onRefresh = vi.fn();
    render(
      <ModelStatus
        checking={false}
        onRefresh={onRefresh}
        health={{
          online: false,
          provider: 'ollama',
          base_url: 'x',
          latency_ms: null,
          models: [],
          error: 'refused',
        }}
      />,
    );
    expect(screen.getByText('Model offline')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Ping model'));
    expect(onRefresh).toHaveBeenCalled();
  });
});

describe('parseSse', () => {
  it('parses events split across chunks', async () => {
    const enc = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode('event: delta\ndata: {"content":"He'));
        c.enqueue(enc.encode('llo"}\n\nevent: done\ndata: {"rounds":1}\n\n'));
        c.close();
      },
    });
    const out = [];
    for await (const e of parseSse(stream)) out.push(e);
    expect(out).toEqual([
      { event: 'delta', data: { content: 'Hello' } },
      { event: 'done', data: { rounds: 1 } },
    ]);
  });
});

describe('KeyValueEditor', () => {
  it('emits added pairs', () => {
    const onChange = vi.fn();
    render(<KeyValueEditor value={{}} onChange={onChange} />);
    fireEvent.click(screen.getByText('+ Add'));
    fireEvent.change(screen.getByPlaceholderText('KEY'), { target: { value: 'TOKEN' } });
    fireEvent.change(screen.getByPlaceholderText('value'), { target: { value: 'abc' } });
    expect(onChange).toHaveBeenLastCalledWith({ TOKEN: 'abc' });
  });
});
