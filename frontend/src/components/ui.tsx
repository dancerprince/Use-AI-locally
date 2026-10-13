import { Component, useState, type ErrorInfo, type ReactNode } from 'react';
import { MASK } from '../api/client';

export function Spinner() {
  return (
    <span
      role="status"
      aria-label="loading"
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-transparent"
    />
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-md border border-red-800 bg-red-950/50 p-3 text-sm text-red-200"
    >
      <span className="break-words">{message}</span>
      {onRetry && (
        <button className="btn-ghost shrink-0" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card text-center text-slate-400">
      <p className="font-medium text-slate-300">{title}</p>
      {hint && <p className="mt-1 text-sm">{hint}</p>}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 rounded-full transition ${checked ? 'bg-indigo-600' : 'bg-slate-700'}`}
    >
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${checked ? 'left-4' : 'left-0.5'}`}
      />
    </button>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button className="text-slate-400 hover:text-white" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function StatusDot({ status }: { status: string }) {
  const color =
    {
      connected: 'bg-emerald-500',
      online: 'bg-emerald-500',
      connecting: 'bg-amber-400 animate-pulse',
      error: 'bg-red-500',
      offline: 'bg-red-500',
    }[status] ?? 'bg-slate-500';
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

/** Editable key/value list; values shown as the mask are kept server-side. */
export function KeyValueEditor({
  value,
  onChange,
  secret,
  keyPlaceholder = 'KEY',
}: {
  value: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
  secret?: boolean;
  keyPlaceholder?: string;
}) {
  const [rows, setRows] = useState<[string, string][]>(() => Object.entries(value));
  const commit = (next: [string, string][]) => {
    setRows(next);
    onChange(Object.fromEntries(next.filter(([k]) => k.trim())));
  };
  return (
    <div className="space-y-2">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex gap-2">
          <input
            className="input"
            placeholder={keyPlaceholder}
            value={k}
            onChange={(e) => commit(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))}
          />
          <input
            className="input"
            placeholder="value"
            type={secret && v !== MASK ? 'password' : 'text'}
            value={v}
            onFocus={() => v === MASK && commit(rows.map((r, j) => (j === i ? [r[0], ''] : r)))}
            onChange={(e) => commit(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))}
          />
          <button
            type="button"
            className="btn-ghost"
            aria-label="Remove"
            onClick={() => commit(rows.filter((_, j) => j !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      <button type="button" className="btn-ghost" onClick={() => setRows([...rows, ['', '']])}>
        + Add
      </button>
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI crashed', error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-8">
          <ErrorBanner
            message={`Something went wrong: ${this.state.error.message}`}
            onRetry={() => this.setState({ error: null })}
          />
        </div>
      );
    }
    return this.props.children;
  }
}
