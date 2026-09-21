import type {
  AccountInfo,
  BackupItem,
  EditionInfo,
  MigrateJobInfo,
  MigratePlan,
  MigrateRunResult,
  SessionCopyRequest,
  SessionCopyResult,
  SessionExportRequest,
  SessionExportResult,
  SessionItem,
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

  jobs: Record<string, MigrateJobInfo & { stepIndex: number }> = {};

  backupsByEdition: Record<string, BackupItem[]> = {
    domestic: [
      {
        backup_id: "20260916120000_pre_migrate_11111111_a1b2c3",
        created_at: new Date(Date.now() - 24 * 3600 * 1000).toISOString(),
        target_uid: "11111111-aaaa-4000-8000-000000000001",
        label: "pre_migrate",
        edition: "domestic",
        file_count: 36,
        size_bytes: 42598400,
        files: [
          { rel_path: "workbuddy.db", target_role: "workbuddy.db", size_bytes: 42467328 },
          { rel_path: "memory/11111111-aaaa-4000-8000-000000000001.md", target_role: "memory/profile", size_bytes: 38912 },
          { rel_path: "connectors/11111111-aaaa-4000-8000-000000000001/mcp.json", target_role: "connectors", size_bytes: 92160 },
        ],
      },
      {
        backup_id: "20260914093000_manual_snapshot_11111111_d4e5f6",
        created_at: new Date(Date.now() - 3 * 86400 * 1000).toISOString(),
        target_uid: "11111111-aaaa-4000-8000-000000000001",
        label: "manual_snapshot",
        edition: "domestic",
        file_count: 34,
        size_bytes: 38850000,
      },
    ],
    international: [
      {
        backup_id: "20260915180000_pre_migrate_88888888_f7g8h9",
        created_at: new Date(Date.now() - 40 * 3600 * 1000).toISOString(),
        target_uid: "88888888-dddd-4000-8000-000000000001",
        label: "pre_migrate",
        edition: "international",
        file_count: 52,
        size_bytes: 71200000,
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
      blocked: sameAccount,
      block_reason: sameAccount ? "源账号和目标账号相同，无需执行迁移。" : undefined,
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

  createMigrateJob(body: {
    from_edition: string;
    to_edition: string;
    source_uid: string;
    target_uid?: string;
    items: Record<string, boolean>;
  }): { job_id: string; status: string } {
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    const rand = Math.random().toString(36).slice(2, 6);
    const jobId = `job_${stamp}_${rand}`;
    this.jobs[jobId] = {
      job_id: jobId,
      status: "running",
      stage: "preflight",
      progress: 5,
      message: "正在执行前置安全检查与 SQLite 连通性校验...",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      payload: {
        from_edition: body.from_edition,
        to_edition: body.to_edition,
        source_uid: body.source_uid,
        target_uid: body.target_uid,
        items: body.items,
      },
      stepIndex: 0,
      result: null,
      error: null,
    };
    return { job_id: jobId, status: "pending" };
  }

  getMigrateJob(jobId: string): MigrateJobInfo {
    const job = this.jobs[jobId];
    if (!job) {
      throw new Error("作业不存在");
    }
    const STAGES = [
      { stage: "preflight", progress: 5, message: "正在执行前置安全检查与 SQLite 连通性校验..." },
      { stage: "backup", progress: 20, message: "正在创建 SQLite 在线原子热备份与快照清单..." },
      { stage: "sessions", progress: 35, message: "正在合并数据库聊天会话..." },
      { stage: "session_content", progress: 50, message: "正在同步会话正文与关联 Blobs 附件..." },
      { stage: "user_memory", progress: 65, message: "正在增量合并用户长期记忆 Profile..." },
      { stage: "mcp_connectors", progress: 75, message: "正在深度合并 MCP 扩展与连接器配置..." },
      { stage: "tasks", progress: 82, message: "正在关联历史任务与工作空间记录..." },
      { stage: "skills", progress: 88, message: "正在同步自定义技能定义..." },
      { stage: "shared_plugins", progress: 92, message: "正在同步共享插件与市场扩展..." },
      { stage: "session_usage", progress: 96, message: "正在聚合 Token 用量记录..." },
      { stage: "completed", progress: 100, message: "数据迁移与完整性校验全部完成！" },
    ];
    if (job.status === "running") {
      job.stepIndex += 1;
      if (job.stepIndex >= STAGES.length - 1) {
        const last = STAGES[STAGES.length - 1];
        job.stage = last.stage;
        job.progress = last.progress;
        job.message = last.message;
        job.status = "completed";
        job.result = this.runMigrate();
      } else {
        const cur = STAGES[job.stepIndex];
        job.stage = cur.stage;
        job.progress = cur.progress;
        job.message = cur.message;
      }
      job.updated_at = new Date().toISOString();
    }
    return { ...job };
  }

  listMigrateJobs(): { jobs: MigrateJobInfo[] } {
    const list = Object.values(this.jobs).map((j) => ({ ...j }));
    list.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    return { jobs: list };
  }

  getBackups(edition: string): { edition: string; backups: BackupItem[] } {
    return {
      edition,
      backups: JSON.parse(JSON.stringify(this.backupsByEdition[edition] || [])),
    };
  }

  restoreBackup(edition: string, backupId: string): { ok: boolean; backup_id: string; restored_files: string[]; edition: string } {
    return {
      ok: true,
      backup_id: backupId,
      restored_files: ["workbuddy.db", "memory/profile.md", "connectors/mcp.json"],
      edition,
    };
  }

  createBackup(edition: string, targetUid?: string, label?: string): { ok: boolean; backup_id: string; path: string; edition: string } {
    const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    const rand = Math.random().toString(36).slice(2, 8);
    const safeUid = (targetUid || "default").slice(0, 8);
    const safeLabel = label || "manual";
    const backupId = `${stamp}_${safeLabel}_${safeUid}_${rand}`;
    const newItem: BackupItem = {
      backup_id: backupId,
      created_at: new Date().toISOString(),
      target_uid: targetUid || "11111111-aaaa-4000-8000-000000000001",
      label: safeLabel,
      edition,
      file_count: 35,
      size_bytes: 41943040,
    };
    if (!this.backupsByEdition[edition]) {
      this.backupsByEdition[edition] = [];
    }
    this.backupsByEdition[edition].unshift(newItem);
    return {
      ok: true,
      backup_id: backupId,
      path: `~/.workbuddy/backups/${backupId}`,
      edition,
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
      const prompt = mInput >= mCache ? mInput : mInput + mCache;
      const hitRate = prompt > 0 ? Math.round((mCache / prompt) * 1000) / 1000 : 0;
      return {
        model: m.model,
        color: m.color,
        input: mInput,
        output: mOutput,
        cache_read: mCache,
        total: mTotal,
        ratio: m.ratio,
        percent: Math.round(m.ratio * 1000) / 10,
        cache_hit_rate: hitRate,
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
        const dIn = Math.round(dTotal * 0.56);
        const dOut = Math.round(dTotal * 0.18);
        const dCache = Math.round(dTotal * 0.26);
        const dMPr = dIn >= dCache ? dIn : dIn + dCache;
        return {
          model: m.model,
          color: m.color,
          total: dTotal,
          input: dIn,
          output: dOut,
          cache_read: dCache,
          cache_hit_rate: dMPr > 0 ? Math.round((dCache / dMPr) * 1000) / 1000 : 0,
        };
      });

      const dInput = Math.round(dayTotal * 0.56);
      const dOutput = Math.round(dayTotal * 0.18);
      const dCache = Math.round(dayTotal * 0.26);
      const dPrompt = dInput >= dCache ? dInput : dInput + dCache;
      const dHit = dPrompt > 0 ? Math.round((dCache / dPrompt) * 1000) / 1000 : 0;

      by_day.push({
        date: dateStr,
        total: dayTotal,
        input: dInput,
        output: dOutput,
        cache_read: dCache,
        cache_hit_rate: dHit,
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
        daily_average: Math.round(baseTotal / Math.max(1, dayCount)),
      },
      by_model,
      by_day,
    };
  }

  mockSessions: Record<string, SessionItem[]> = {
    domestic: [
      {
        id: "sess-d01-arch-gateway",
        edition: "domestic",
        user_id: "11111111-aaaa-4000-8000-000000000001",
        account_name: "Dev-Alpha (主账号)",
        title: "构建高并发微服务网关架构方案",
        raw_title: "构建高并发微服务网关架构方案",
        custom_title: "",
        status: "completed",
        cwd: "E:\\projects\\gateway-service",
        model: "claude-3-7-sonnet",
        created_at: Date.now() - 3 * 24 * 3600 * 1000,
        updated_at: Date.now() - 40 * 60 * 1000,
        last_activity_at: Date.now() - 40 * 60 * 1000,
        turns: 18,
        message_count: 42,
        input_tokens: 125000,
        output_tokens: 18400,
        cache_read_tokens: 112000,
        total_tokens: 143400,
        cache_hit_rate: 0.896,
        has_jsonl: true,
      },
      {
        id: "sess-d02-ui-components",
        edition: "domestic",
        user_id: "11111111-aaaa-4000-8000-000000000001",
        account_name: "Dev-Alpha (主账号)",
        title: "重构前端组件库与响应式状态流",
        raw_title: "重构前端组件库与响应式状态流",
        custom_title: "",
        status: "completed",
        cwd: "E:\\workbuddy-tools\\ui",
        model: "deepseek-v3",
        created_at: Date.now() - 5 * 24 * 3600 * 1000,
        updated_at: Date.now() - 3 * 3600 * 1000,
        last_activity_at: Date.now() - 3 * 3600 * 1000,
        turns: 24,
        message_count: 56,
        input_tokens: 88500,
        output_tokens: 14200,
        cache_read_tokens: 72000,
        total_tokens: 102700,
        cache_hit_rate: 0.8136,
        has_jsonl: true,
      },
      {
        id: "sess-d03-migrate-pipeline",
        edition: "domestic",
        user_id: "22222222-bbbb-4000-8000-000000000002",
        account_name: "Demo-Tester (测试环境)",
        title: "Python 数据迁移流水线自动化调优",
        raw_title: "Python 数据迁移流水线自动化调优",
        custom_title: "",
        status: "completed",
        cwd: "E:\\workbuddy-tools\\backend",
        model: "gemini-2.5-pro",
        created_at: Date.now() - 1 * 24 * 3600 * 1000,
        updated_at: Date.now() - 6 * 3600 * 1000,
        last_activity_at: Date.now() - 6 * 3600 * 1000,
        turns: 12,
        message_count: 28,
        input_tokens: 45000,
        output_tokens: 9500,
        cache_read_tokens: 28000,
        total_tokens: 54500,
        cache_hit_rate: 0.6222,
        has_jsonl: true,
      },
    ],
    international: [
      {
        id: "sess-i01-mcp-sandbox",
        edition: "international",
        user_id: "33333333-cccc-4000-8000-000000000003",
        account_name: "Global-Lead (跨国协同)",
        title: "MCP 连接器全生命周期管理与安全沙箱",
        raw_title: "MCP 连接器全生命周期管理与安全沙箱",
        custom_title: "",
        status: "completed",
        cwd: "C:\\Workspace\\mcp-cluster",
        model: "claude-3-7-sonnet",
        created_at: Date.now() - 2 * 24 * 3600 * 1000,
        updated_at: Date.now() - 2 * 3600 * 1000,
        last_activity_at: Date.now() - 2 * 3600 * 1000,
        turns: 15,
        message_count: 34,
        input_tokens: 96000,
        output_tokens: 16800,
        cache_read_tokens: 88000,
        total_tokens: 112800,
        cache_hit_rate: 0.9167,
        has_jsonl: true,
      },
      {
        id: "sess-i02-token-analysis",
        edition: "international",
        user_id: "33333333-cccc-4000-8000-000000000003",
        account_name: "Global-Lead (跨国协同)",
        title: "LLM 提示词工程与 Cache 命中率分析",
        raw_title: "LLM 提示词工程与 Cache 命中率分析",
        custom_title: "",
        status: "completed",
        cwd: "C:\\Workspace\\llm-bench",
        model: "gemini-2.5-flash",
        created_at: Date.now() - 4 * 24 * 3600 * 1000,
        updated_at: Date.now() - 12 * 3600 * 1000,
        last_activity_at: Date.now() - 12 * 3600 * 1000,
        turns: 8,
        message_count: 18,
        input_tokens: 32000,
        output_tokens: 6100,
        cache_read_tokens: 0,
        total_tokens: 38100,
        cache_hit_rate: 0.0,
        has_jsonl: true,
      },
    ],
  };

  getSessions(
    edition: string,
    uid?: string,
    query?: string,
    sortBy: string = "updated_at",
    order: string = "desc",
  ): { edition: string; total: number; sessions: SessionItem[] } {
    let list = [...(this.mockSessions[edition] || [])];
    if (uid) {
      list = list.filter((s) => s.user_id === uid);
    }
    if (query && query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(
        (s) =>
          s.title.toLowerCase().includes(q) ||
          s.id.toLowerCase().includes(q) ||
          s.cwd.toLowerCase().includes(q) ||
          s.account_name.toLowerCase().includes(q),
      );
    }
    const reverse = order.toLowerCase() !== "asc";
    if (sortBy === "created_at") {
      list.sort((a, b) => (reverse ? (b.created_at || 0) - (a.created_at || 0) : (a.created_at || 0) - (b.created_at || 0)));
    } else if (sortBy === "tokens" || sortBy === "total_tokens") {
      list.sort((a, b) => (reverse ? b.total_tokens - a.total_tokens : a.total_tokens - b.total_tokens));
    } else if (sortBy === "cache_hit_rate") {
      list.sort((a, b) => (reverse ? b.cache_hit_rate - a.cache_hit_rate : a.cache_hit_rate - b.cache_hit_rate));
    } else if (sortBy === "turns") {
      list.sort((a, b) => (reverse ? b.turns - a.turns : a.turns - b.turns));
    } else {
      list.sort((a, b) => (reverse ? (b.updated_at || 0) - (a.updated_at || 0) : (a.updated_at || 0) - (b.updated_at || 0)));
    }
    return {
      edition,
      total: list.length,
      sessions: list,
    };
  }

  copySessions(body: SessionCopyRequest): SessionCopyResult {
    const fromList = this.mockSessions[body.from_edition] || [];
    const toList = this.mockSessions[body.to_edition] || [];
    const idMap: Record<string, string> = {};
    const suffix = body.title_suffix || " (副本)";

    for (const sid of body.session_ids) {
      const found = fromList.find((s) => s.id === sid);
      if (found) {
        const newSid = `sess-clone-${Math.random().toString(36).substring(2, 9)}`;
        idMap[sid] = newSid;
        const isSame = body.from_edition === body.to_edition && found.user_id === body.target_uid;
        const newTitle = body.clone_mode || isSame ? `${found.title}${suffix}` : found.title;
        toList.unshift({
          ...found,
          id: newSid,
          edition: body.to_edition as any,
          user_id: body.target_uid,
          account_name: "目标账号",
          title: newTitle,
          raw_title: newTitle,
          updated_at: Date.now(),
          last_activity_at: Date.now(),
        });
      }
    }
    this.mockSessions[body.to_edition] = toList;
    return {
      ok: true,
      copied: Object.keys(idMap).length,
      from_edition: body.from_edition,
      to_edition: body.to_edition,
      target_uid: body.target_uid,
      session_id_map: idMap,
      details: {
        sessions: Object.keys(idMap).length,
        content_files: Object.keys(idMap).length * 2,
        tasks: Object.keys(idMap).length,
        usage: Object.keys(idMap).length,
      },
    };
  }

  exportSessions(body: SessionExportRequest): SessionExportResult {
    const list = this.mockSessions[body.edition] || [];
    const files = body.session_ids.map((sid) => {
      const sess = list.find((s) => s.id === sid);
      const title = sess?.title || "未命名对话";
      const hitPct = ((sess?.cache_hit_rate || 0) * 100).toFixed(1);
      const modeNote = body.mode === "clean" ? "纯文本输出" : "完整模式（含 Tool Call & 思考）";
      let content = `# ${title}\n\n- **会话 ID**: \`${sid}\`\n- **Token 消耗**: ${sess?.total_tokens || 0}\n- **缓存命中率**: ${hitPct}%\n- **导出模式**: ${modeNote}\n\n---\n\n### 👤 用户\n\n你好，请帮我分析当前项目的架构。\n\n---\n\n`;
      if (body.mode === "full") {
        content += `<details>\n<summary>💭 思考过程 (Reasoning)</summary>\n\n正在检索项目配置文件与依赖关系树...\n</details>\n\n<details>\n<summary>🛠️ 工具调用: <code>read_file</code> (completed)</summary>\n\n**参数:**\n\`\`\`json\n{"path": "package.json"}\n\`\`\`\n\n**执行结果:**\n\`\`\`\n{"name": "mock-project", "version": "1.0.0"}\n\`\`\`\n</details>\n\n---\n\n`;
      }
      content += `### 🤖 助手\n\n当前项目架构清晰，模块划分合理。\n\n---\n`;
      return {
        session_id: sid,
        filename: `${title.replace(/[\s\/\\]+/g, "_")}_${sid.substring(0, 8)}.md`,
        content,
      };
    });
    return {
      ok: true,
      files,
      count: files.length,
    };
  }

  checkUpdate(): {
    current_version: string;
    latest_version: string;
    has_update: boolean;
    release_name: string;
    release_notes: string;
    published_at: string;
    html_url: string;
    download_url: string;
    error: null;
  } {
    return {
      current_version: "0.1.5.1",
      latest_version: "0.1.5.1",
      has_update: false,
      release_name: "v0.1.5.1 正式版",
      release_notes: "🎉 当前为最新正式版。\n- 迁移配置体验全面优化：更改账号与版本即时自动刷新检测\n- 重新检测 WorkBuddy 运行状态，关闭客户端后即刻进入就绪模式\n- 细化迁移就绪与锁定状态流转体验",
      published_at: new Date().toISOString(),
      html_url: "https://github.com/Harvey-Will/workbuddy-tools/releases",
      download_url: "https://github.com/Harvey-Will/workbuddy-tools/releases/latest",
      error: null,
    };
  }
}

export const mockStore = new MockStore();
