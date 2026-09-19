/** HTTP client for local WorkBuddy Tools API (sidecar). */
import { mockStore } from "./mockData";

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

export interface TokenModelItem {
  model: string;
  color: string;
  input: number;
  output: number;
  cache_read: number;
  total: number;
  cache_hit_rate: number;
  ratio?: number;
  percent?: number;
}

export interface TokenDayItem {
  date: string;
  total: number;
  input?: number;
  output?: number;
  cache_read?: number;
  cache_hit_rate?: number;
  by_model: Array<{
    model: string;
    color: string;
    total: number;
    input: number;
    output: number;
    cache_read?: number;
    cache_hit_rate?: number;
  }>;
}

export interface TokenSummary {
  edition: string;
  range: { key: string; from: string; to: string; from_ms?: number; to_ms?: number };
  totals: {
    input: number;
    output: number;
    cache_read: number;
    total: number;
    cache_hit_rate: number;
    events: number;
    daily_average?: number;
  };
  by_model: TokenModelItem[];
  by_day: TokenDayItem[];
}

export interface UpdateCheckResult {
  current_version: string;
  latest_version: string;
  has_update: boolean;
  release_name?: string;
  release_notes?: string;
  published_at?: string;
  html_url?: string;
  download_url?: string;
  error?: string | null;
}

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface MigrateJobInfo {
  job_id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
  payload?: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
    items?: Record<string, boolean>;
  };
  result?: MigrateRunResult | null;
  error?: { code: string; message: string } | null;
}

export interface BackupFileEntry {
  rel_path: string;
  target_role: string;
  sha256?: string;
  size_bytes?: number;
}

export interface BackupItem {
  backup_id: string;
  created_at: string;
  target_uid: string;
  label?: string;
  edition: string;
  file_count: number;
  size_bytes?: number;
  files?: BackupFileEntry[];
}

export interface SessionItem {
  id: string;
  edition: EditionKey;
  user_id: string;
  account_name: string;
  title: string;
  raw_title: string;
  custom_title: string;
  status: string;
  cwd: string;
  model: string;
  created_at: number | null;
  updated_at: number | null;
  last_activity_at: number | null;
  turns: number;
  message_count: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  cache_hit_rate: number;
  has_jsonl: boolean;
}

export interface SessionCopyRequest {
  from_edition: string;
  to_edition: string;
  session_ids: string[];
  target_uid: string;
  title_suffix?: string;
  clone_mode?: boolean;
}

export interface SessionCopyResult {
  ok: boolean;
  copied: number;
  from_edition: string;
  to_edition: string;
  target_uid: string;
  session_id_map: Record<string, string>;
  details?: {
    sessions: number;
    content_files: number;
    tasks: number;
    usage: number;
  };
}

export interface SessionExportRequest {
  edition: string;
  session_ids: string[];
  mode: "clean" | "full";
  format?: "json" | "zip";
}

export interface ExportedFileItem {
  session_id: string;
  filename: string;
  content: string;
}

export interface SessionExportResult {
  ok: boolean;
  files: ExportedFileItem[];
  count: number;
  zip_base64?: string;
  zip_filename?: string;
}

export class ApiError extends Error {
  code?: string;
  status?: number;

  constructor(message: string, code?: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
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
    const detail = (data as { detail?: { code?: string; message?: string } | string })?.detail;
    const msg =
      typeof detail === "string" ? detail : detail?.message || `HTTP ${res.status}`;
    const code = typeof detail === "object" ? detail?.code : undefined;
    throw new ApiError(msg, code, res.status);
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
        const detail = (data as { detail?: { code?: string; message?: string } | string })?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : detail?.message || res.statusText || "请求失败";
        const code = typeof detail === "object" ? detail?.code : undefined;
        throw new ApiError(msg, code, res.status);
      }
      return data as T;
    } catch (e) {
      lastErr = e;
      if (e instanceof ApiError) throw e;
    }
  }
  throw new ApiError(lastErr instanceof Error ? lastErr.message : "无法连接本地服务");
}

export function isDemoMode(): boolean {
  return false;
}

export function setDemoMode(_enable: boolean): void {
  // Release build: demo mode permanently disabled
}

export const api = {
  health: () => {
    if (isDemoMode()) return Promise.resolve(mockStore.getHealth());
    return request<{ ok: boolean; editions: string[] }>("/api/health");
  },
  editions: () => {
    if (isDemoMode()) return Promise.resolve(mockStore.getEditions());
    return request<{ editions: EditionInfo[] }>("/api/editions");
  },
  accounts: (edition: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getAccounts(edition));
    return request<{
      edition: string;
      current_uid: string;
      accounts: AccountInfo[];
      client_running: boolean;
    }>(`/api/accounts?edition=${encodeURIComponent(edition)}`);
  },
  switchAccount: (edition: string, target_uid: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.switchAccount(edition, target_uid));
    return request<{ ok: boolean; message: string; need_restart: boolean }>(
      "/api/accounts/switch",
      { method: "POST", body: JSON.stringify({ edition, target_uid }) },
    );
  },
  rename: (edition: string, uid: string, label: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.rename(edition, uid, label));
    return request<{ ok: boolean; display_name: string }>("/api/accounts/rename", {
      method: "POST",
      body: JSON.stringify({ edition, uid, label }),
    });
  },
  addProfile: (edition: string, uid: string, label: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.addProfile(edition, uid, label));
    return request<{ ok: boolean }>("/api/accounts/add", {
      method: "POST",
      body: JSON.stringify({ edition, uid, label }),
    });
  },
  openClient: (edition: string) => {
    if (isDemoMode()) return Promise.resolve({ ok: true, exe: "mock_client.exe" });
    return request<{ ok: boolean; exe: string }>("/api/accounts/open-client", {
      method: "POST",
      body: JSON.stringify({ edition }),
    });
  },
  workspaces: (edition: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getWorkspaces(edition));
    return request<{ workspaces: WorkspaceInfo[] }>(
      `/api/workspaces?edition=${encodeURIComponent(edition)}`,
    );
  },
  migratePlan: (q: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
  }) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getMigratePlan(q));
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
  }) => {
    if (isDemoMode()) return Promise.resolve(mockStore.runMigrate());
    return request<MigrateRunResult>("/api/migrate/run", {
      method: "POST",
      body: JSON.stringify({ ...body, mode: "copy" }),
    });
  },
  tokens: (edition: string, range: string, dateFrom?: string, dateTo?: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getTokens(edition, range));
    const p = new URLSearchParams({ edition, range });
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    return request<TokenSummary>(`/api/tokens/summary?${p}`);
  },
  migrateCreateJob: (body: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
    items: Record<string, boolean>;
  }) => {
    if (isDemoMode()) return Promise.resolve(mockStore.createMigrateJob(body));
    return request<{ job_id: string; status: string }>("/api/migrate/jobs", {
      method: "POST",
      body: JSON.stringify({ ...body, mode: "copy" }),
    });
  },
  migrateGetJob: (jobId: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getMigrateJob(jobId));
    return request<MigrateJobInfo>(`/api/migrate/jobs/${encodeURIComponent(jobId)}`);
  },
  migrateListJobs: () => {
    if (isDemoMode()) return Promise.resolve(mockStore.listMigrateJobs());
    return request<{ jobs: MigrateJobInfo[] }>("/api/migrate/jobs");
  },
  backups: (edition: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getBackups(edition));
    return request<{ edition: string; backups: BackupItem[] }>(
      `/api/backups?edition=${encodeURIComponent(edition)}`,
    );
  },
  restoreBackup: (edition: string, backupId: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.restoreBackup(edition, backupId));
    return request<{ ok: boolean; backup_id: string; restored_files: string[]; edition: string }>(
      "/api/backups/restore",
      { method: "POST", body: JSON.stringify({ edition, backup_id: backupId }) },
    );
  },
  createBackup: (edition: string, targetUid?: string, label?: string) => {
    if (isDemoMode()) return Promise.resolve(mockStore.createBackup(edition, targetUid, label));
    return request<{ ok: boolean; backup_id: string; path: string; edition: string }>(
      "/api/backups/create",
      { method: "POST", body: JSON.stringify({ edition, target_uid: targetUid, label: label || "manual" }) },
    );
  },
  checkUpdate: async (): Promise<UpdateCheckResult> => {
    return await request<UpdateCheckResult>("/api/system/check-update");
  },
  openUrl: async (url: string): Promise<void> => {
    try {
      await request<{ ok: boolean }>("/api/system/open-url", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
    } catch {
      if (typeof window !== "undefined") {
        window.open(url, "_blank");
      }
    }
  },
  systemVersion: (): Promise<{ version: string; repo_url: string }> => {
    return request<{ version: string; repo_url: string }>("/api/system/version");
  },
  sessions: (
    edition: string,
    uid?: string,
    query?: string,
    sortBy?: string,
    order?: string,
  ) => {
    if (isDemoMode()) return Promise.resolve(mockStore.getSessions(edition, uid, query, sortBy, order));
    const p = new URLSearchParams({ edition });
    if (uid) p.set("uid", uid);
    if (query) p.set("query", query);
    if (sortBy) p.set("sort_by", sortBy);
    if (order) p.set("order", order);
    return request<{ edition: string; total: number; sessions: SessionItem[] }>(`/api/sessions?${p}`);
  },
  copySessions: (body: SessionCopyRequest) => {
    if (isDemoMode()) return Promise.resolve(mockStore.copySessions(body));
    return request<SessionCopyResult>("/api/sessions/copy", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  exportSessions: (body: SessionExportRequest) => {
    if (isDemoMode()) return Promise.resolve(mockStore.exportSessions(body));
    return request<SessionExportResult>("/api/sessions/export", {
      method: "POST",
      body: JSON.stringify({ ...body, format: body.format || "json" }),
    });
  },
};
