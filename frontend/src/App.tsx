import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { ModelStatus } from './components/ModelStatus';
import { ErrorBoundary } from './components/ui';
import { useModelHealth } from './hooks/useModelHealth';
import { ChatPage } from './pages/Chat';
import { ConnectorsPage } from './pages/Connectors';
import { McpServersPage } from './pages/McpServers';
import { ModelsPage } from './pages/Models';
import { SettingsPage } from './pages/Settings';
import { SkillsPage } from './pages/Skills';

const NAV = [
  { to: '/chat', label: '💬 Chat' },
  { to: '/models', label: '📦 Models' },
  { to: '/mcp', label: '🧩 MCP servers' },
  { to: '/connectors', label: '🔌 Connectors' },
  { to: '/skills', label: '🎯 Skills' },
  { to: '/settings', label: '⚙️ Settings' },
];

export default function App() {
  const { health, checking, refresh } = useModelHealth();
  return (
    <div className="flex h-screen">
      <nav className="flex w-56 shrink-0 flex-col gap-1 border-r border-slate-800 bg-slate-950 p-3">
        <div className="mb-4 px-2 text-lg font-bold">Offline AI</div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) =>
              `rounded px-3 py-2 text-sm ${isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:bg-slate-900'}`
            }
          >
            {n.label}
          </NavLink>
        ))}
        <div className="mt-auto">
          <ModelStatus health={health} checking={checking} onRefresh={() => void refresh()} />
        </div>
      </nav>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage health={health} />} />
            <Route path="/models" element={<ModelsPage onChanged={() => void refresh()} />} />
            <Route path="/mcp" element={<McpServersPage />} />
            <Route path="/connectors" element={<ConnectorsPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/settings" element={<SettingsPage onSaved={() => void refresh()} />} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
