import type {
  AccountInfo,
  EditionInfo,
  MigratePlan,
  MigrateRunResult,
  TokenSummary,
  WorkspaceInfo,
} from "./api";

/** 
 * Completely synthetic in-memory mock store for public demonstrations and clean screenshots.
 * Contains ZERO real user data, ZERO real account IDs, and ZERO private environment paths.
 */
class MockStore {
  editions: EditionInfo[] = [
    {
      key: "domestic",
      label: "WorkBuddy 国内版",
      short: "国内版",
      root: "~/.workbuddy",
      exists: true,
      client_running: false,
    },
    {
      key: "international",
      label: "WorkBuddyAI 国际版",
      short: "国际版",
      root: "~/.workbuddy-ai",
      exists: true,
      client_running: false,
    },
  ];

  accountsByEdition: Record<string, { currentUid: string; accounts: AccountInfo[] }> = {
    domestic: {
      currentUid: "11111111-aaaa-4000-8000-000000000001",
      accounts: [
        {
          uid: "11111111-aaaa-4000-8000-000000000001",
          nickname: "Dev-Alpha",
          display_name: "Dev-Alpha (主账号)",
          name_source: "snapshot",
          edition: "domestic",
          sessions: 32,
          memory_bytes: 38912,
          mcp_servers: 16,
          connector_states: 22,
          is_current: true,
          tasks: 8,
          last_activity_at: Date.now() - 15 * 60 * 1000,
        },
        {
          uid: "22222222-bbbb-4000-8000-000000000002",
          nickname: "Demo-Tester",
          display_name: "Demo-Tester (测试环境)",
          name_source: "profile",
          edition: "domestic",
          sessions: 15,
          memory_bytes: 16384,
          mcp_servers: 8,
          connector_states: 12,
          is_current: false,
          tasks: 3,
          last_activity_at: Date.now() - 26 * 3600 * 1000,
        },
        {
          uid: "33333333-cccc-4000-8000-000000000003",
          nickname: "Automation-Bot",
          display_name: "Automation-Bot (自动化脚本)",
          name_source: "profile",
          edition: "domestic",
          sessions: 6,
          memory_bytes: 8192,
          mcp_servers: 5,
          connector_states: 7,
          is_current: false,
          tasks: 1,
          last_activity_at: Date.now() - 4 * 86400 * 1000,
        },
      ],
    },
    international: {
      currentUid: "88888888-dddd-4000-8000-000000000001",
      accounts: [
        {
          uid: "88888888-dddd-4000-8000-000000000001",
          nickname: "Global-Pro",
          display_name: "Global-Pro (海外主力)",
          name_source: "snapshot",
          edition: "international",
          sessions: 46,
          memory_bytes: 67584,
          mcp_servers: 24,
          connector_states: 30,
          is_current: true,
          tasks: 14,
          last_activity_at: Date.now() - 25 * 60 * 1000,
        },
        {
          uid: "99999999-eeee-4000-8000-000000000002",
          nickname: "Research-Lab",
          display_name: "Research-Lab (实验模型)",
          name_source: "cache",
          edition: "international",
          sessions: 18,
          memory_bytes: 24576,
          mcp_servers: 12,
          connector_states: 16,
          is_current: false,
          tasks: 4,
          last_activity_at: Date.now() - 2 * 86400 * 1000,
        },
      ],
    },
  };

  workspacesByEdition: Record<string, WorkspaceInfo[]> = {
    domestic: [
      {
        cwd: "~/Projects/ai-assistant-core",
        sessions: 18,
        exists: true,
        project_memory: true,
        memory_files: 4,
      },
      {
        cwd: "~/Workspace/desktop-app-frontend",
        sessions: 10,
        exists: true,
        project_memory: true,
        memory_files: 2,
      },
      {
        cwd: "~/Repositories/data-pipeline-sample",
        sessions: 4,
        exists: true,
        project_memory: false,
        memory_files: 0,
      },
    ],
    international: [
      {
        cwd: "~/Projects/multimodal-agent-demo",
        sessions: 28,
        exists: true,
        project_memory: true,
        memory_files: 6,
      },
      {
        cwd: "~/Workspace/cloud-integration-sdk",
        sessions: 14,
        exists: true,
        project_memory: true,
        memory_files: 3,
      },
      {
        cwd: "~/Repositories/evaluation-benchmarks",
        sessions: 4,
        exists: true,
        project_memory: false,
        memory_files: 0,
      },
    ],
  };

  getHealth(): { ok: boolean; editions: string[] } {
    return { ok: true, editions: ["domestic", "international"] };
  }

  getEditions(): { editions: EditionInfo[] } {
    return { editions: JSON.parse(JSON.stringify(this.editions)) };
  }

  getAccounts(edition: string): {
    edition: string;
    current_uid: string;
    accounts: AccountInfo[];
    client_running: boolean;
  } {
    const data = this.accountsByEdition[edition] || { currentUid: "", accounts: [] };
    return {
      edition,
      current_uid: data.currentUid,
      accounts: JSON.parse(JSON.stringify(data.accounts)) as AccountInfo[],
      client_running: false,
    };
  }

  switchAccount(edition: string, targetUid: string): { ok: boolean; message: string; need_restart: boolean } {
    const group = this.accountsByEdition[edition];
    if (group) {
      group.currentUid = targetUid;
      group.accounts.forEach((a) => {
        a.is_current = a.uid === targetUid;
      });
    }
    return { ok: true, message: "已切换当前账号（演示模式）", need_restart: false };
  }

  rename(edition: string, uid: string, label: string): { ok: boolean; display_name: string } {
    const group = this.accountsByEdition[edition];
    const acc = group?.accounts.find((a) => a.uid === uid);
    if (acc) {
      acc.display_name = label;
      acc.name_source = "profile";
    }
    return { ok: true, display_name: label };
  }

  addProfile(edition: string, uid: string, label: string): { ok: boolean } {
    const group = this.accountsByEdition[edition];
    if (group) {
      group.accounts.push({
        uid,
        nickname: label || uid.slice(0, 8),
        display_name: label ? `${label} (新增)` : uid.slice(0, 8),
        name_source: "profile",
        edition,
        sessions: 0,
        memory_bytes: 0,
        mcp_servers: 0,
        connector_states: 0,
        is_current: false,
        tasks: 0,
        last_activity_at: Date.now(),
      });
    }
    return { ok: true };
  }

  getWorkspaces(edition: string): { workspaces: WorkspaceInfo[] } {
    return {
      workspaces: JSON.parse(JSON.stringify(this.workspacesByEdition[edition] || [])) as WorkspaceInfo[],
    };
  }

  getMigratePlan(q: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
  }): MigratePlan {
    const sameEdition = q.from_edition === q.to_edition;
    const sameAccount = sameEdition && q.source_uid === q.target_uid;

    return {
      from_edition: q.from_edition,
      to_edition: q.to_edition,
      source_uid: q.source_uid,
      target_uid: q.target_uid || "88888888-dddd-4000-8000-000000000001",
      client_running: false,
      same_edition: sameEdition,
      same_account: sameAccount,
      blocked: false,
      items: [
        { key: "sessions", label: "聊天会话", count: 32, note: "完整会话结构" },
        { key: "session_content", label: "会话内容与附件", count: 32, note: "含 96 个 jsonl 与附件 blobs" },
        { key: "user_memory", label: "用户记忆", count: 1, note: "38.9 KB Memory Block + RAW_JSON" },
        { key: "tasks", label: "历史任务", count: 8, note: "2 个任务目录" },
        { key: "skills", label: "技能", count: 8, note: "pdf, docx, markitdown 等" },
        { key: "mcp_connectors", label: "MCP 连接器", count: 16, note: "跨版本深度合并" },
        { key: "shared_plugins", label: "插件与连接器市场", count: 24, note: "共享扩展" },
        { key: "session_usage", label: "用量记录", count: 32, note: "Token 消耗明细" },
      ],
      default_items: {
        sessions: true,
        session_content: true,
        user_memory: true,
        tasks: true,
        skills: true,
        mcp_connectors: true,
        shared_plugins: true,
        session_usage: true,
      },
      warnings: ["演示模式：迁移前已自动模拟创建完整时间戳备份快照。目标环境现有数据安全保留。"],
    };
  }

  runMigrate(): MigrateRunResult {
    return {
      ok: true,
      status: "success",
      warnings: [],
      need_restart: true,
      results: [
        { key: "sessions", status: "success", detail: "已复制 32 条会话", count: 32 },
        { key: "session_content", status: "success", detail: "已同步 32 个正文文件与附件 blobs", count: 32 },
        { key: "user_memory", status: "success", detail: "Memory Block 与 RAW_JSON 合并完成 (+38.9KB)", count: 1 },
        { key: "tasks", status: "success", detail: "已复制 2 个任务目录（共 8 项任务）", count: 8 },
        { key: "skills", status: "success", detail: "8 项技能同步完成", count: 8 },
        { key: "mcp_connectors", status: "success", detail: "已深度合并 16 个 MCP 服务配置", count: 16 },
        { key: "shared_plugins", status: "success", detail: "市场扩展索引已同步", count: 24 },
        { key: "session_usage", status: "success", detail: "32 条用量统计记录已入库", count: 32 },
      ],
    };
  }

  getTokens(edition: string, range: string): TokenSummary {
    const models = [
      { model: "claude-3-7-sonnet", color: "#4F46E5", ratio: 0.38 },
      { model: "gpt-5-turbo", color: "#0EA5E9", ratio: 0.31 },
      { model: "gemini-2.5-pro", color: "#10B981", ratio: 0.18 },
      { model: "deepseek-r1", color: "#F59E0B", ratio: 0.09 },
      { model: "qwen-max-2.5", color: "#8B5CF6", ratio: 0.04 },
    ];

    let dayCount = 7;
    let baseTotal = 4862350;
    let events = 1420;

    if (range === "today") {
      dayCount = 1;
      baseTotal = 680200;
      events = 195;
    } else if (range === "24h") {
      dayCount = 2;
      baseTotal = 890400;
      events = 260;
    } else if (range === "30d") {
      dayCount = 30;
      baseTotal = 19540000;
      events = 5820;
    } else if (range === "90d") {
      dayCount = 90;
      baseTotal = 56200000;
      events = 16800;
    }

    const input = Math.round(baseTotal * 0.56);
    const output = Math.round(baseTotal * 0.18);
    const cache_read = Math.round(baseTotal * 0.26);
    const cache_hit_rate = 0.584;

    const by_model = models.map((m) => {
      const mTotal = Math.round(baseTotal * m.ratio);
      const mInput = Math.round(mTotal * 0.56);
      const mOutput = Math.round(mTotal * 0.18);
      const mCache = Math.round(mTotal * 0.26);
      return {
        model: m.model,
        color: m.color,
        input: mInput,
        output: mOutput,
        cache_read: mCache,
        total: mTotal,
        cache_hit_rate: 0.55 + m.ratio * 0.15,
      };
    });

    const by_day = [];
    const now = new Date();
    for (let i = dayCount - 1; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 86400 * 1000);
      const dateStr = d.toISOString().slice(0, 10);
      const dayFactor = 0.75 + Math.sin(i * 1.2) * 0.3;
      const dayTotal = Math.round((baseTotal / dayCount) * dayFactor);

      const dayByModel = models.map((m) => {
        const dTotal = Math.round(dayTotal * m.ratio);
        return {
          model: m.model,
          color: m.color,
          total: dTotal,
          input: Math.round(dTotal * 0.6),
          output: Math.round(dTotal * 0.4),
        };
      });

      by_day.push({
        date: dateStr,
        total: dayTotal,
        by_model: dayByModel,
      });
    }

    return {
      edition,
      range: { key: range, from: by_day[0]?.date || "", to: by_day[by_day.length - 1]?.date || "" },
      totals: {
        total: baseTotal,
        input,
        output,
        cache_read,
        cache_hit_rate,
        events,
      },
      by_model,
      by_day,
    };
  }
}

export const mockStore = new MockStore();
