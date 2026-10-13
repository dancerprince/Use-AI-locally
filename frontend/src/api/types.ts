export interface ModelHealth {
  online: boolean;
  provider: string;
  base_url: string;
  latency_ms: number | null;
  models: string[];
  error: string | null;
}

export interface ModelSettings {
  provider: 'ollama' | 'openai';
  base_url: string;
  api_key: string | null;
  default_model: string | null;
  temperature: number;
  system_prompt: string;
}

export type Transport = 'stdio' | 'sse' | 'http';

export interface McpTool {
  name: string;
  exposed_name: string;
  description: string | null;
  input_schema: Record<string, unknown>;
}

export interface McpServerIn {
  name: string;
  transport: Transport;
  command: string | null;
  args: string[];
  env: Record<string, string>;
  url: string | null;
  headers: Record<string, string>;
  enabled: boolean;
  confirmed?: boolean;
}

export interface McpServer extends McpServerIn {
  id: number;
  status: 'connecting' | 'connected' | 'error' | 'stopped' | 'disabled';
  last_error: string | null;
  tools: McpTool[];
}

export type ConnectorType = 'http' | 'filesystem' | 'sqlite' | 'postgres' | 'webhook';

export interface ConnectorIn {
  name: string;
  type: ConnectorType;
  config: Record<string, unknown>;
  enabled: boolean;
}

export interface Connector extends ConnectorIn {
  id: number;
  tools: string[];
}

export interface SkillIn {
  name: string;
  description: string;
  instructions: string;
  tools: string[];
  enabled: boolean;
}

export interface Skill extends SkillIn {
  id: number;
}

export interface TestResult {
  ok: boolean;
  message: string;
  details?: unknown;
}

export interface ToolInfo {
  name: string;
  source: string;
  description: string | null;
}

export interface ChatSession {
  id: string;
  title: string;
  model: string | null;
  updated_at: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  tool_calls: ToolCall[] | null;
  tool_call_id: string | null;
  name: string | null;
}

export type ChatEvent =
  | { event: 'session'; data: { session_id: string; title: string } }
  | { event: 'delta'; data: { content: string } }
  | { event: 'tool_call'; data: ToolCall & { source: string } }
  | { event: 'tool_result'; data: { id: string; name: string; ok: boolean; content: string } }
  | { event: 'error'; data: { message: string } }
  | { event: 'done'; data: { rounds: number; truncated?: boolean } };

export interface RuntimeStatus {
  installed: boolean;
  running: boolean;
  version: string | null;
  path: string | null;
  managed: boolean;
  install_hint: string;
}

export interface InstalledModel {
  name: string;
  size: number;
  modified_at: string | null;
  family: string | null;
  parameter_size: string | null;
  quantization: string | null;
}

export interface CatalogModel {
  name: string;
  title: string;
  size_gb: number;
  min_ram_gb: number;
  tools: boolean;
  tags: string[];
  description: string;
  installed: boolean;
}

export interface PullJob {
  id: string;
  model: string;
  status: string;
  completed: number;
  total: number;
  percent: number;
  done: boolean;
  error: string | null;
  started_at: number;
}
