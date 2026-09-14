/** HTTP client for local WorkBuddy Tools API (sidecar). */

export type EditionKey = "domestic" | "international";

export interface EditionInfo {
  key: EditionKey;
  label: string;
  short: string;
  root: string;
  exists: boolean;
  client_running?: boolean;
  client_binaries?: string[];
}

export interface AccountInfo {
  uid: string;
  nickname: string;
  display_name: string;
  name_source: string;
  edition: string;
  sessions: number;
  memory_bytes: number;
  mcp_servers: number;
  connector_states: number;
  is_current: boolean;
  tasks: number;
  last_activity_at?: number | null;
  role?: string;
}

export interface WorkspaceInfo {
  cwd: string;
  sessions: number;
  exists: boolean;
  project_memory: boolean;
  memory_files: number;
}

export interface MigratePlanItem {
  key: string;
  label: string;
  count: number;
  note?: string;
}

export type MigrateItemStatus = "success" | "skipped" | "failed";

export interface MigrateItemResult {
  key: string;
  status: MigrateItemStatus;
  detail: string;
  count: number;
}

export interface MigratePlan {
  from_edition: string;
  to_edition: string;
  source_uid: string;
  target_uid: string;
  client_running: boolean;
  items: MigratePlanItem[];
  default_items: Record<string, boolean>;
  blocked?: boolean;
  block_reason?: string;
  blocked_item_keys?: string[];
  same_edition?: boolean;
  same_account?: boolean;
  warnings?: string[];
}

export interface MigrateRunResult {
  ok: boolean;
  status?: string;
  warnings?: string[];
  results?: MigrateItemResult[];
  need_restart?: boolean;
}

export interface TokenSummary {
  edition: string;
  range: { key: string; from: string; to: string };
  totals: {
    input: number;
    output: number;
    cache_read: number;
    total: number;
    cache_hit_rate: number;
    events: number;
  };
  by_model: Array<{
    model: string;
    color: string;
    input: number;
    output: number;
    cache_read: number;
    total: number;
    cache_hit_rate: number;
  }>;
  by_day: Array<{
    date: string;
    total: number;
    by_model: Array<{ model: string; color: string; total: number; input: number; output: number }>;
  }>;
}

export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export function apiBase(): string {
  const fromEnv = import.meta.env.VITE_API_BASE as string | undefined;
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  return "http://127.0.0.1:18765";
}

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

let cachedToken: string | null = null;

async function apiToken(): Promise<string | null> {
  if (!isTauri()) return null;
  if (cachedToken !== null) return cachedToken;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    cachedToken = (await invoke<string>("get_api_token")) || "";
  } catch {
    cachedToken = "";
  }
  return cachedToken;
}

async function invokeProxy<T>(path: string, init?: RequestInit): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  const method = (init?.method || "GET").toUpperCase();
  const body =
    typeof init?.body === "string" ? init.body : init?.body ? String(init.body) : null;
  const res = await invoke<{ status: number; body: string }>("api_proxy", {
    req: { path, method, body },
  });
  let data: unknown = null;
  try {
    data = res.body ? JSON.parse(res.body) : null;
  } catch {
    data = { raw: res.body };
  }
  if (res.status >= 400) {
    const detail = (data as { detail?: { message?: string } | string })?.detail;
    const msg =
      typeof detail === "string" ? detail : detail?.message || `HTTP ${res.status}`;
    throw new ApiError(msg);
  }
  return data as T;
}

const API_HOSTS = ["http://127.0.0.1:18765", "http://localhost:18765"];
let activeHost: string | null = null;

async function fetchWithHost(host: string, path: string, init?: RequestInit): Promise<Response> {
  const token = await apiToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (token) headers["X-WBT-Token"] = token;
  return fetch(host + path, { ...init, headers });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Desktop: always proxy through Rust to avoid WebView network blocks.
  if (isTauri()) {
    return invokeProxy<T>(path, init);
  }
  const hosts = activeHost ? [activeHost, ...API_HOSTS.filter((h) => h !== activeHost)] : API_HOSTS;
  let lastErr: unknown = null;
  for (const host of hosts) {
    try {
      const res = await fetchWithHost(host, path, init);
      activeHost = host;
      const text = await res.text();
      let data: unknown = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { raw: text };
      }
      if (!res.ok) {
        const detail = (data as { detail?: { message?: string } | string })?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : detail?.message || res.statusText || "请求失败";
        throw new ApiError(msg);
      }
      return data as T;
    } catch (e) {
      lastErr = e;
      if (e instanceof ApiError) throw e;
    }
  }
  throw new ApiError(lastErr instanceof Error ? lastErr.message : "无法连接本地服务");
}

export const api = {
  health: () => request<{ ok: boolean; editions: string[] }>("/api/health"),
  editions: () => request<{ editions: EditionInfo[] }>("/api/editions"),
  accounts: (edition: string) =>
    request<{
      edition: string;
      current_uid: string;
      accounts: AccountInfo[];
      client_running: boolean;
    }>(`/api/accounts?edition=${encodeURIComponent(edition)}`),
  switchAccount: (edition: string, target_uid: string) =>
    request<{ ok: boolean; message: string; need_restart: boolean }>(
      "/api/accounts/switch",
      { method: "POST", body: JSON.stringify({ edition, target_uid }) },
    ),
  rename: (edition: string, uid: string, label: string) =>
    request<{ ok: boolean; display_name: string }>("/api/accounts/rename", {
      method: "POST",
      body: JSON.stringify({ edition, uid, label }),
    }),
  addProfile: (edition: string, uid: string, label: string) =>
    request<{ ok: boolean }>("/api/accounts/add", {
      method: "POST",
      body: JSON.stringify({ edition, uid, label }),
    }),
  openClient: (edition: string) =>
    request<{ ok: boolean; exe: string }>("/api/accounts/open-client", {
      method: "POST",
      body: JSON.stringify({ edition }),
    }),
  workspaces: (edition: string) =>
    request<{ workspaces: WorkspaceInfo[] }>(
      `/api/workspaces?edition=${encodeURIComponent(edition)}`,
    ),
  migratePlan: (q: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
  }) => {
    const p = new URLSearchParams({
      from_edition: q.from_edition,
      to_edition: q.to_edition,
      source_uid: q.source_uid,
    });
    if (q.target_uid) p.set("target_uid", q.target_uid);
    return request<MigratePlan>(`/api/migrate/plan?${p}`);
  },
  migrateRun: (body: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
    items: Record<string, boolean>;
  }) =>
    request<MigrateRunResult>("/api/migrate/run", {
      method: "POST",
      body: JSON.stringify({ ...body, mode: "copy" }),
    }),
  tokens: (edition: string, range: string, dateFrom?: string, dateTo?: string) => {
    const p = new URLSearchParams({ edition, range });
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    return request<TokenSummary>(`/api/tokens/summary?${p}`);
  },
};
