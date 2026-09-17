import "./styles.css";
import logoUrl from "./assets/logo.svg";
import {
  api,
  type AccountInfo,
  type BackupItem,
  type EditionInfo,
  type MigrateJobInfo,
  type MigratePlan,
  type MigrateRunResult,
  type TokenSummary,
  type UpdateCheckResult,
  type WorkspaceInfo,
  ApiError,
} from "./api";

const APP_VERSION = "0.1.3";
const GITHUB_REPO_URL = "https://github.com/Harvey-Will/workbuddy-tools";
const GITHUB_ICON_SVG = `<svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>`;

const MIGRATE_LABELS: Record<string, string> = {
  sessions: "聊天会话",
  session_content: "会话内容与附件",
  user_memory: "用户记忆",
  tasks: "历史任务",
  skills: "技能",
  mcp_connectors: "MCP 连接器",
  shared_plugins: "插件与连接器市场",
  session_usage: "用量记录",
};

interface TrackerStageDef {
  key: string;
  name: string;
  percent: number;
  itemKey?: string;
}

const TRACKER_STAGES: TrackerStageDef[] = [
  { key: "preflight", name: "前置安全检查", percent: 5 },
  { key: "backup", name: "在线原子热备份", percent: 20 },
  { key: "sessions", name: "聊天会话数据", percent: 35, itemKey: "sessions" },
  { key: "session_content", name: "正文与关联附件", percent: 50, itemKey: "session_content" },
  { key: "user_memory", name: "用户长期记忆", percent: 65, itemKey: "user_memory" },
  { key: "mcp_connectors", name: "MCP 扩展配置", percent: 75, itemKey: "mcp_connectors" },
  { key: "tasks", name: "历史任务记录", percent: 82, itemKey: "tasks" },
  { key: "skills", name: "自定义技能定义", percent: 88, itemKey: "skills" },
  { key: "shared_plugins", name: "插件与市场扩展", percent: 92, itemKey: "shared_plugins" },
  { key: "session_usage", name: "Token 用量统计", percent: 96, itemKey: "session_usage" },
  { key: "completed", name: "迁移校验完成", percent: 100 },
];

const state = {
  page: "accounts" as "accounts" | "migrate" | "tokens" | "about",
  editions: [] as EditionInfo[],
  edition: "domestic",
  accounts: [] as AccountInfo[],
  currentUid: "",
  workspaces: [] as WorkspaceInfo[],
  migratePlan: null as MigratePlan | null,
  selectedItems: {} as Record<string, boolean>,
  migFrom: "domestic",
  migTo: "international",
  tokenRange: "7d",
  tokenTableView: "model" as "model" | "day",
  tokenData: null as TokenSummary | null,
  cleanCaptureMode: false,
  isMigrating: false,
  activeJobId: null as string | null,
  jobStartTime: null as number | null,
  currentJob: null as MigrateJobInfo | null,
  timerInterval: null as number | null,
  pollTimeout: null as number | null,
  backupsEdition: "domestic",
  backups: [] as BackupItem[],
  pendingRestoreBackup: null as BackupItem | null,
  isCheckingUpdate: false,
  latestUpdate: null as UpdateCheckResult | null,
};

function $(sel: string, root: ParentNode = document): HTMLElement {
  const el = root.querySelector<HTMLElement>(sel);
  if (!el) throw new Error(`missing ${sel}`);
  return el;
}

function fmtNum(n: number): string {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n || 0);
}

function fmtBytes(n: number): string {
  if (!n) return "0 B";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function fmtTime(ms?: number | null): string {
  if (!ms) return "—";
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

function nameSourceLabel(src: string): string {
  const map: Record<string, string> = {
    snapshot: "客户端昵称",
    profile: "自定义备注",
    cache: "已记忆昵称",
    fallback: "自动识别",
  };
  return map[src] || "自动识别";
}

function toast(msg: string): void {
  let el = document.querySelector<HTMLDivElement>("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.remove("hidden");
  window.clearTimeout((toast as unknown as { t?: number }).t);
  (toast as unknown as { t?: number }).t = window.setTimeout(() => {
    el?.classList.add("hidden");
  }, 2800);
}

function safeColor(c: string): string {
  return /^#[0-9A-Fa-f]{3,8}$/.test(c || "") ? c : "#4F46E5";
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function displayName(a: AccountInfo): string {
  const ed = a.edition === "international" ? "国际版" : "国内版";
  return a.display_name || a.nickname || `${ed} · ${a.uid.slice(0, 8)}`;
}

function fmtRelativeTime(isoStr?: string): string {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  const ms = d.getTime();
  if (Number.isNaN(ms)) return isoStr;
  const diffSec = Math.floor((Date.now() - ms) / 1000);
  if (diffSec < 60) return "刚刚";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`;
  const days = Math.floor(diffSec / 86400);
  if (days < 30) return `${days} 天前`;
  return d.toLocaleDateString();
}

function fmtElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function backupLabelBadge(label?: string): { text: string; colorClass: string } {
  if (!label || label === "manual" || label === "manual_snapshot") {
    return { text: "手动即时快照", colorClass: "ok" };
  }
  if (label === "target" || label === "pre_migrate") {
    return { text: "迁移前自动 (目标端)", colorClass: "" };
  }
  if (label === "source") {
    return { text: "迁移前自动 (源端)", colorClass: "soft" };
  }
  return { text: label, colorClass: "soft" };
}

/* ---------- shell ---------- */
function renderShell(): void {
  const app = document.querySelector("#app");
  if (!app) return;
  app.innerHTML = `
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <img class="brand-mark" src="${logoUrl}" width="36" height="36" alt="" />
        <div>
          <div class="brand-title">WorkBuddy Tools</div>
          <div class="brand-sub">账号与数据管家</div>
        </div>
      </div>
      <nav class="nav">
        <button class="nav-item active" data-page="accounts">账号中心</button>
        <button class="nav-item" data-page="migrate">迁移复制</button>
        <button class="nav-item" data-page="tokens">Token 统计</button>
        <button class="nav-item" data-page="about">关于</button>
      </nav>
      <div class="side-foot">
        <span id="client-pill" class="pill">检测中…</span>
      </div>
    </aside>
    <main class="main">
      <div id="global-migrate-banner" class="global-migrate-banner hidden"></div>
      <div id="global-update-banner" class="global-migrate-banner hidden" style="background:linear-gradient(90deg, #ecfdf5, #f0fdf4);border-color:#a7f3d0;color:#065f46"></div>
      <header class="topbar">
        <div>
          <h1 id="page-title">账号中心</h1>
          <p id="page-desc">查看双端账号并一键切换</p>
        </div>
        <div class="top-actions">
          <select id="edition-select" class="select"></select>
          <button id="btn-refresh" class="btn ghost">刷新</button>
        </div>
      </header>

      <section id="page-accounts" class="page active">
        <div class="cards" id="account-cards"></div>
        <div class="panel">
          <div class="panel-head"><h2>添加用户</h2></div>
          <div class="row">
            <input id="add-uid" class="input" placeholder="账号 ID（可选）" style="min-width:220px" />
            <input id="add-label" class="input" placeholder="备注名" style="min-width:140px" />
            <button id="btn-add" class="btn">保存</button>
            <button id="btn-open" class="btn primary">打开客户端登录</button>
          </div>
          <p class="muted small" style="margin:.55rem 0 0">登录完成后点「刷新」即可看到新账号。</p>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>工作空间</h2></div>
          <div id="workspace-list" class="list"></div>
        </div>
      </section>

      <section id="page-migrate" class="page">
        <!-- Tracker Panel (shown during / after migration) -->
        <div id="mig-tracker-panel" class="tracker-panel hidden">
          <div class="tracker-header">
            <div class="tracker-title">
              <span id="tracker-icon">⚡</span>
              <span id="tracker-header-title">数据迁移流水线</span>
              <span id="tracker-status-badge" class="badge">就绪</span>
            </div>
            <div class="tracker-timer" id="tracker-timer">00:00</div>
          </div>
          <div class="progress-bar-wrap">
            <div id="tracker-progress-fill" class="progress-bar-fill" style="width:0%"></div>
          </div>
          <div class="tracker-msg">
            <span id="tracker-status-text">初始化中...</span>
            <span id="tracker-percent-text" style="font-weight:700;font-variant-numeric:tabular-nums">0%</span>
          </div>
          <div id="tracker-stages" class="pipeline-stages"></div>
          <div id="tracker-failure-card" class="failure-card hidden">
            <div class="failure-info">
              <div class="failure-title">⚠️ 任务中断或执行失败</div>
              <div class="failure-desc" id="failure-error-msg">请检查错误信息并尝试回滚</div>
            </div>
            <button id="btn-rollback" class="btn small" style="background:#dc2626;color:#fff;border:none">↩️ 一键回滚至快照</button>
          </div>
          <div id="tracker-success-actions" class="row hidden" style="margin-top:1rem;justify-content:flex-end">
            <button id="btn-reset-tracker" class="btn">返回配置面板</button>
          </div>
        </div>

        <!-- Config Panel -->
        <div id="mig-config-panel" class="panel">
          <div class="steps"><div class="step on"></div><div class="step" id="step2"></div><div class="step" id="step3"></div></div>
          <div class="panel-head"><h2>选择性迁移 / 复制</h2></div>
          <div class="row">
            <label class="muted small">源 <select id="mig-from" class="select"></select></label>
            <select id="mig-source" class="select wide"></select>
            <span class="muted">→</span>
            <label class="muted small">目标 <select id="mig-to" class="select"></select></label>
            <select id="mig-target" class="select wide"></select>
            <button id="btn-plan" class="btn">预览</button>
          </div>
          <div id="mig-warn" class="banner warn hidden"></div>
          <div id="mig-items" class="check-grid"></div>
          <div class="row">
            <button id="btn-run" class="btn primary" disabled>执行迁移</button>
            <span id="mig-hint" class="muted small">先预览再执行</span>
          </div>
        </div>

        <div class="panel hidden" id="mig-result-panel">
          <div class="panel-head"><h2>迁移结果明细</h2></div>
          <div id="mig-result" class="list"></div>
        </div>

        <!-- Backups Panel -->
        <div class="backup-panel" id="backup-panel">
          <div class="panel-head" style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <h2>备份与快照历史</h2>
              <p class="muted small" style="margin:0.2rem 0 0">迁移前自动创建快照，保障数据零丢失</p>
            </div>
            <div class="row">
              <select id="backup-edition-select" class="select"></select>
              <button id="btn-create-backup" class="btn small">+ 创建即时快照</button>
            </div>
          </div>
          <div id="backup-table-wrap"></div>
        </div>
      </section>

      <section id="page-tokens" class="page">
        <div class="panel token-header-panel">
          <div class="token-toolbar">
            <div class="token-title-group">
              <h2>Token 用量与成本效率</h2>
              <p class="muted small">监控多模型 Token 消耗、输入输出结构及 Prompt 缓存命中率</p>
            </div>
            <div class="token-controls">
              <div class="scale-selector-wrap">
                <div class="scale-tabs" id="scale-tabs" role="tablist">
                  <button class="scale-tab" data-range="today" type="button">每日</button>
                  <button class="scale-tab" data-range="24h" type="button">24H</button>
                  <button class="scale-tab active" data-range="7d" type="button">7 天</button>
                  <button class="scale-tab" data-range="30d" type="button">30 天</button>
                  <button class="scale-tab" data-range="90d" type="button">90 天</button>
                </div>
                <select id="token-range" class="select hidden">
                  <option value="today">每日</option>
                  <option value="24h">24H</option>
                  <option value="7d" selected>7 天</option>
                  <option value="30d">30 天</option>
                  <option value="90d">90 天</option>
                </select>
              </div>
              <button id="btn-token" class="btn primary small" title="刷新最新 Token 统计">
                <span id="token-refresh-icon">🔄</span> 刷新统计
              </button>
            </div>
          </div>
        </div>

        <!-- 6 KPI Metric Cards -->
        <div class="token-kpis-grid" id="token-kpis"></div>

        <!-- Charts Row -->
        <div class="token-charts-row">
          <div class="chart-box daily-chart-box">
            <div class="chart-header">
              <div>
                <h3>每日总用量与多模型消耗走势</h3>
                <p class="muted small">柱顶标明每日总用量，悬浮查看各模型实际用量与占比</p>
              </div>
              <div id="chart-daily-summary" class="badge"></div>
            </div>
            <div id="bar-chart" class="chart-canvas-wrap"></div>
          </div>

          <div class="chart-box donut-chart-box">
            <div class="chart-header">
              <div>
                <h3>各模型使用占比</h3>
                <p class="muted small">多模型消耗份额分布及比例</p>
              </div>
            </div>
            <div class="donut-content-grid">
              <div class="donut-graphic-col">
                <div id="pie-chart" class="donut-chart"></div>
              </div>
              <div class="donut-legend-col">
                <div id="pie-share-list" class="model-share-list"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Detailed Table with Model & Daily Views -->
        <div class="panel token-table-panel">
          <div class="panel-head" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.6rem">
            <div>
              <h3 id="token-table-title">各模型详细数据与缓存命中率</h3>
            </div>
            <div style="display:flex;align-items:center;gap:0.6rem">
              <div class="table-view-tabs" role="tablist">
                <button class="table-tab active" id="tab-table-model" data-table-view="model" type="button">📊 按模型汇总</button>
                <button class="table-tab" id="tab-table-day" data-table-view="day" type="button">📅 按日期每日明细</button>
              </div>
              <div id="token-table-count" class="badge"></div>
            </div>
          </div>
          <div id="token-table-wrap" class="token-table-wrap"></div>
        </div>
      </section>

      <section id="page-about" class="page">
        <div class="about-hero-card">
          <div class="about-hero-content">
            <img src="${logoUrl}" width="54" height="54" alt="Logo" class="about-logo" />
            <div class="about-hero-texts">
              <div class="about-hero-title-row">
                <h2>WorkBuddy Tools</h2>
                <span class="version-tag-pill">v${APP_VERSION}</span>
                <span class="edition-tag-pill">开源桌面版</span>
              </div>
              <p class="about-tagline">专为 WorkBuddy / WorkBuddyAI 打造的账号多开、数据热迁移与 Token 智能分析工具</p>
            </div>
          </div>

          <div class="about-update-section">
            <div class="update-check-card">
              <div class="update-info-col">
                <div class="update-status-row">
                  <span class="update-dot"></span>
                  <span id="update-status-text">当前版本：v${APP_VERSION}</span>
                  <span id="update-badge" class="badge ok">已就绪</span>
                </div>
                <div class="update-pref-row">
                  <label class="auto-update-label" title="开启后每次打开软件时自动检测是否有新版本发布">
                    <input type="checkbox" id="check-auto-update" />
                    <span>每次打开自动检查更新</span>
                  </label>
                </div>
              </div>
              <div class="update-actions-col">
                <button id="btn-check-update" class="btn primary">
                  <span id="update-spin-icon">🔄</span> 检查更新
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="about-card github-card">
          <div class="github-card-header">
            <div class="github-card-title">
              ${GITHUB_ICON_SVG}
              <div>
                <h3>GitHub 开源项目</h3>
                <p class="muted small">代码开源透明，无任何隐藏上报或第三方遥测，完全运行于本机</p>
              </div>
            </div>
            <button id="btn-about-github-main" class="btn-github-pill">
              ${GITHUB_ICON_SVG}
              <span>访问 GitHub 仓库</span>
              <span class="arrow-icon">↗</span>
            </button>
          </div>
          <div class="github-card-links">
            <div class="gh-link-box" id="gh-link-repo">
              <span class="gh-icon">📦</span>
              <div>
                <div class="gh-name">开源主页</div>
                <div class="gh-sub">Harvey-Will/workbuddy-tools</div>
              </div>
            </div>
            <div class="gh-link-box" id="gh-link-releases">
              <span class="gh-icon">🏷️</span>
              <div>
                <div class="gh-name">Releases 发行页</div>
                <div class="gh-sub">下载最新安装包与查看更新日志</div>
              </div>
            </div>
            <div class="gh-link-box" id="gh-link-issues">
              <span class="gh-icon">💬</span>
              <div>
                <div class="gh-name">提交反馈 / Issue</div>
                <div class="gh-sub">报告 Bug 或提出新功能建议</div>
              </div>
            </div>
          </div>
        </div>

        <div class="about-grid">
          <div class="about-feature-box">
            <div class="feat-icon">🛡️</div>
            <h4>数据与隐私绝对安全</h4>
            <p>所有会话、记忆、插件配置均在本地安全环境处理。离线可用，不经过任何外部服务器。</p>
          </div>
          <div class="about-feature-box">
            <div class="feat-icon">⚡</div>
            <h4>SQLite 在线原子热备份</h4>
            <p>独家支持客户端运行状态下的原子快照与毫秒级一键安全回滚，保障核心资产零丢失。</p>
          </div>
          <div class="about-feature-box">
            <div class="feat-icon">📊</div>
            <h4>精准多尺度 Token 洞察</h4>
            <p>支持 24H、每日、7天、30天、90天尺度缩放，精确还原 Prompt 缓存命中率与多模型用量。</p>
          </div>
        </div>
      </section>
    </main>
  </div>

  <!-- Safety Restore Modal -->
  <div id="restore-modal" class="modal-backdrop hidden">
    <div class="modal-dialog">
      <div class="modal-header">
        <span>⚠️</span>
        <h3>安全还原确认</h3>
      </div>
      <div class="modal-body">
        <div class="modal-warning-box">
          <strong>高危破坏性操作：</strong> 还原将使用选定快照覆盖该版本的完整数据库与配置，当前最新数据若未备份将被替代！
        </div>
        <div id="restore-modal-info"></div>
        <label style="display:flex;align-items:flex-start;gap:0.5rem;font-size:12.5px;cursor:pointer;margin-top:0.4rem">
          <input type="checkbox" id="restore-confirm-check" style="margin-top:2px" />
          <span>我已知晓目标环境现有数据将被此快照覆盖，且已完全关闭客户端。</span>
        </label>
      </div>
      <div class="modal-footer">
        <button id="btn-cancel-restore" class="btn">取消</button>
        <button id="btn-do-restore" class="btn danger" disabled>确认执行还原</button>
      </div>
    </div>
  </div>

  <!-- Update Notification & Dialog Modal -->
  <div id="update-modal" class="modal-backdrop hidden">
    <div class="modal-dialog update-dialog">
      <div class="modal-header">
        <div style="display:flex;align-items:center;gap:8px">
          <span>🚀</span>
          <h3 id="update-modal-title">发现新版本</h3>
        </div>
        <button id="btn-update-modal-close" class="modal-close-btn" title="关闭窗口">&times;</button>
      </div>
      <div class="modal-body">
        <div class="update-modal-banner">
          <div class="update-badge-row">
            <span class="badge ok" id="update-modal-ver">v0.1.4</span>
            <span class="muted small" id="update-modal-date"></span>
          </div>
          <h4 id="update-modal-name" style="margin:0.4rem 0 0.2rem;font-size:14px;color:var(--ink)"></h4>
        </div>
        <div class="update-notes-title">更新日志与说明：</div>
        <div class="update-notes-box" id="update-modal-notes"></div>
        <div class="update-modal-pref" style="margin-top:0.8rem;padding-top:0.6rem;border-top:1px solid var(--line)">
          <label class="auto-update-label" title="开启后每次打开软件时自动检测是否有新版本发布">
            <input type="checkbox" id="check-modal-auto-update" />
            <span>每次打开自动检查更新</span>
          </label>
        </div>
      </div>
      <div class="modal-footer">
        <button id="btn-update-cancel" class="btn">稍后提醒</button>
        <button id="btn-update-download" class="btn primary">前往 GitHub 下载升级 ↗</button>
      </div>
    </div>
  </div>`;
}

const pageMeta: Record<string, [string, string]> = {
  accounts: ["账号中心", "查看双端账号并一键切换"],
  migrate: ["迁移复制", "选择性复制会话、记忆、技能与 MCP"],
  tokens: ["Token 统计", "按模型查看输入输出与缓存命中"],
  about: ["关于", "产品说明"],
};

function setPage(page: string): void {
  state.page = page as typeof state.page;
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", (b as HTMLElement).dataset.page === page);
  });
  document.querySelectorAll(".page").forEach((p) => {
    p.classList.toggle("active", (p as HTMLElement).id === "page-" + page);
  });
  const [title, desc] = pageMeta[page] || ["", ""];
  $("#page-title").textContent = title;
  $("#page-desc").textContent = desc;
  if (page === "tokens") void loadTokens();
  if (page === "migrate") {
    renderTracker();
    void fillMigrateSelects();
    void loadBackups();
  }
  applyConcurrencyLock();
}

function fillEditionSelects(): void {
  const opts = state.editions
    .filter((e) => e.exists)
    .map((e) => `<option value="${e.key}">${escapeHtml(e.label)}</option>`)
    .join("");
  ["#edition-select", "#mig-from", "#mig-to", "#backup-edition-select"].forEach((sel) => {
    const el = document.querySelector<HTMLSelectElement>(sel);
    if (!el) return;
    const prev = el.value;
    el.innerHTML = opts || `<option value="">未检测到</option>`;
    if (prev && [...el.options].some((o) => o.value === prev)) el.value = prev;
    else if (sel === "#backup-edition-select" && state.backupsEdition) el.value = state.backupsEdition;
    else if (state.edition) el.value = state.edition;
  });
}

function applyConcurrencyLock(): void {
  const banner = document.getElementById("global-migrate-banner");
  if (banner) {
    if (state.isMigrating) {
      const job = state.currentJob;
      const pct = job?.progress ?? 0;
      const msg = job?.message || "正在迁移中...";
      banner.innerHTML = `
        <div class="banner-info">
          <span class="banner-spinner"></span>
          <span><b>任务执行中</b> (${pct}%) — ${escapeHtml(msg)}</span>
        </div>
        <button class="btn-banner-view" id="btn-banner-view">查看流水线 →</button>
      `;
      banner.classList.remove("hidden");
      const bannerView = document.getElementById("btn-banner-view");
      if (bannerView) {
        bannerView.onclick = () => setPage("migrate");
      }
    } else {
      banner.classList.add("hidden");
    }
  }

  const disabled = state.isMigrating;
  document.querySelectorAll<HTMLButtonElement>("[data-switch]").forEach((btn) => {
    btn.disabled = disabled;
    if (disabled) btn.title = "迁移正在进行中，已暂时锁定";
    else btn.removeAttribute("title");
  });
  document.querySelectorAll<HTMLButtonElement>("[data-rename]").forEach((btn) => {
    btn.disabled = disabled;
    if (disabled) btn.title = "迁移正在进行中，已暂时锁定";
    else btn.removeAttribute("title");
  });
  const addBtn = document.getElementById("btn-add") as HTMLButtonElement | null;
  if (addBtn) addBtn.disabled = disabled;
  const openBtn = document.getElementById("btn-open") as HTMLButtonElement | null;
  if (openBtn) openBtn.disabled = disabled;
  const planBtn = document.getElementById("btn-plan") as HTMLButtonElement | null;
  if (planBtn) planBtn.disabled = disabled;
  const runBtn = document.getElementById("btn-run") as HTMLButtonElement | null;
  if (runBtn) {
    if (disabled) runBtn.disabled = true;
    else if (state.migratePlan) runBtn.disabled = Boolean(state.migratePlan.blocked || state.migratePlan.client_running);
  }
  const createBkBtn = document.getElementById("btn-create-backup") as HTMLButtonElement | null;
  if (createBkBtn) createBkBtn.disabled = disabled;
  document.querySelectorAll<HTMLButtonElement>("[data-restore]").forEach((btn) => {
    if (disabled) {
      btn.disabled = true;
      btn.title = "迁移正在进行中，已暂时锁定";
    }
  });
}

function renderPill(): void {
  const ed = state.editions.find((e) => e.key === state.edition);
  const el = $("#client-pill");
  if (!ed?.exists) {
    el.textContent = "未检测到数据";
    el.className = "pill warn";
    return;
  }
  if (ed.client_running) {
    el.textContent = ed.short + " 运行中";
    el.className = "pill warn";
  } else {
    el.textContent = ed.short + " 就绪";
    el.className = "pill ok";
  }
}

function renderAccounts(): void {
  const root = $("#account-cards");
  if (!state.accounts.length) {
    root.innerHTML = `<div class="empty">暂无账号数据。请先打开客户端登录，再点右上角「刷新」。</div>`;
    return;
  }
  root.innerHTML = state.accounts
    .map((a) => {
      const current = a.uid === state.currentUid || a.is_current;
      const name = escapeHtml(displayName(a));
      return `
      <div class="card ${current ? "current" : ""}">
        <div class="nick" title="${name}">${name}</div>
        <div class="uid">${escapeHtml(a.uid)}</div>
        <div class="meta">
          <span class="badge ${current ? "ok" : ""}">${current ? "当前登录" : "历史账号"}</span>
          <span class="badge soft">${nameSourceLabel(a.name_source)}</span>
        </div>
        <div class="stats">
          <div class="stat"><b>${a.sessions}</b><span>会话</span></div>
          <div class="stat"><b>${fmtBytes(a.memory_bytes)}</b><span>记忆</span></div>
          <div class="stat"><b>${a.mcp_servers}</b><span>MCP</span></div>
        </div>
        <div class="muted small">最近活跃 ${fmtTime(a.last_activity_at)}</div>
        <div class="row" style="margin-top:.65rem">
          ${current ? "" : `<button class="btn primary" data-switch="${escapeHtml(a.uid)}" data-name="${name}">切换</button>`}
          <button class="btn" data-rename="${escapeHtml(a.uid)}" data-name="${name}">重命名</button>
          <button class="btn ghost" data-src="${escapeHtml(a.uid)}">迁移源</button>
        </div>
      </div>`;
    })
    .join("");

  root.querySelectorAll<HTMLElement>("[data-switch]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const uid = btn.dataset.switch!;
      if (!confirm(`切换到「${btn.dataset.name}」？切换后请重启客户端。`)) return;
      try {
        const r = await api.switchAccount(state.edition, uid);
        toast(r.message || "已切换");
        await loadAccounts();
      } catch (e) {
        toast((e as Error).message);
      }
    });
  });
  root.querySelectorAll<HTMLElement>("[data-rename]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const next = prompt("显示名称", btn.dataset.name || "");
      if (next === null) return;
      try {
        await api.rename(state.edition, btn.dataset.rename!, next.trim());
        toast("已更新名称");
        await loadAccounts();
      } catch (e) {
        toast((e as Error).message);
      }
    });
  });
  root.querySelectorAll<HTMLElement>("[data-src]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setPage("migrate");
      ($("#mig-from") as HTMLSelectElement).value = state.edition;
      void fillMigrateSelects().then(() => {
        ($("#mig-source") as HTMLSelectElement).value = btn.dataset.src!;
      });
    });
  });
  applyConcurrencyLock();
}

function renderWorkspaces(): void {
  const root = $("#workspace-list");
  if (!state.workspaces.length) {
    root.innerHTML = `<div class="empty">暂无工作空间记录</div>`;
    return;
  }
  root.innerHTML = state.workspaces
    .map(
      (w) => `
    <div class="list-item">
      <div>
        <div><strong>${escapeHtml(w.cwd)}</strong></div>
        <div class="muted small">${w.sessions} 个会话 · ${w.project_memory ? "有项目记忆" : "无项目记忆"}</div>
      </div>
      <span class="badge">${w.exists ? "可用" : "路径缺失"}</span>
    </div>`,
    )
    .join("");
}

async function loadEditions(): Promise<void> {
  const data = await api.editions();
  state.editions = data.editions || [];
  const existing = state.editions.filter((e) => e.exists);
  if (!existing.some((e) => e.key === state.edition) && existing[0]) {
    state.edition = existing[0].key;
  }
  fillEditionSelects();
  ($("#edition-select") as HTMLSelectElement).value = state.edition;
  renderPill();
}

async function loadAccounts(): Promise<void> {
  if (!state.edition) return;
  const data = await api.accounts(state.edition);
  state.accounts = data.accounts || [];
  state.currentUid = data.current_uid || "";
  const ed = state.editions.find((e) => e.key === state.edition);
  if (ed) ed.client_running = data.client_running;
  renderAccounts();
  renderPill();
  try {
    const ws = await api.workspaces(state.edition);
    state.workspaces = ws.workspaces || [];
    renderWorkspaces();
  } catch {
    state.workspaces = [];
    renderWorkspaces();
  }
}

async function fillMigrateSelects(): Promise<void> {
  const from = ($("#mig-from") as HTMLSelectElement).value || state.edition;
  const to = ($("#mig-to") as HTMLSelectElement).value || state.edition;
  state.migFrom = from;
  state.migTo = to;
  await Promise.all([fillAccountOptions(from, "#mig-source"), fillAccountOptions(to, "#mig-target")]);
}

async function fillAccountOptions(edition: string, sel: string): Promise<void> {
  const el = $(sel) as HTMLSelectElement;
  if (!edition) {
    el.innerHTML = "";
    return;
  }
  try {
    const data = await api.accounts(edition);
    el.innerHTML = (data.accounts || [])
      .map((a) => {
        const label = `${displayName(a)} · ${a.sessions}会话`;
        return `<option value="${escapeHtml(a.uid)}">${escapeHtml(label)}</option>`;
      })
      .join("");
  } catch {
    el.innerHTML = `<option value="">加载失败</option>`;
  }
}

async function loadPlan(): Promise<void> {
  const from = ($("#mig-from") as HTMLSelectElement).value;
  const to = ($("#mig-to") as HTMLSelectElement).value;
  const source = ($("#mig-source") as HTMLSelectElement).value;
  const target = ($("#mig-target") as HTMLSelectElement).value;
  if (!from || !to || !source) {
    toast("请选择源账号");
    return;
  }
  try {
    const plan = await api.migratePlan({
      from_edition: from,
      to_edition: to,
      source_uid: source,
      target_uid: target || undefined,
    });
    state.migratePlan = plan;
    state.selectedItems = { ...(plan.default_items || {}) };
    const blockedKeys = new Set(plan.blocked_item_keys || []);
    const keys = [...new Set([...(plan.items || []).map((i) => i.key), ...Object.keys(MIGRATE_LABELS)])];
    $("#mig-items").innerHTML = keys
      .map((k) => {
        const item = plan.items?.find((i) => i.key === k);
        const checked = state.selectedItems[k] === true;
        const disabled = blockedKeys.has(k) || plan.client_running;
        return `
        <label class="check-item">
          <input type="checkbox" data-item="${k}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
          <div>
            <div><strong>${MIGRATE_LABELS[k] || k}</strong> <span class="muted small">×${item?.count ?? 0}</span></div>
          </div>
        </label>`;
      })
      .join("");
    document.querySelectorAll<HTMLInputElement>("[data-item]").forEach((cb) => {
      cb.addEventListener("change", () => {
        state.selectedItems[cb.dataset.item!] = cb.checked;
      });
    });
    const warn = $("#mig-warn");
    const messages: string[] = [];
    if (plan.blocked && plan.block_reason) messages.push(plan.block_reason);
    if (plan.client_running) messages.push("客户端正在运行，请先完全退出 WorkBuddy / WorkBuddyAI 后再执行迁移。");
    if (plan.same_edition && !plan.same_account) {
      messages.push("同版本账号间暂不支持会话相关数据迁移（会话/正文/任务/用量），仅可迁移记忆、MCP、技能等。");
    }
    for (const w of plan.warnings || []) messages.push(w);
    if (messages.length) {
      warn.textContent = messages.join(" ");
      warn.classList.remove("hidden");
    } else warn.classList.add("hidden");
    const runBtn = $("#btn-run") as HTMLButtonElement;
    runBtn.disabled = Boolean(plan.blocked || plan.client_running);
    $("#mig-hint").textContent = `${plan.source_uid.slice(0, 8)}… → ${(plan.target_uid || "").slice(0, 8)}…`;
    $("#step2").classList.add("on");
    toast(plan.blocked ? "当前组合不可迁移" : "已生成预览");
  } catch (e) {
    toast((e as Error).message);
  }
}

function renderTracker(): void {
  const panel = $("#mig-tracker-panel");
  const configPanel = $("#mig-config-panel");
  const job = state.currentJob;

  if (!job && !state.isMigrating) {
    panel.classList.add("hidden");
    configPanel.classList.remove("hidden");
    return;
  }

  panel.classList.remove("hidden");
  configPanel.classList.add("hidden");

  const isCompleted = job?.status === "completed";
  const isFailed = job?.status === "failed";
  const isRunning = job?.status === "running" || job?.status === "pending";

  const statusBadge = $("#tracker-status-badge");
  if (isCompleted) {
    statusBadge.textContent = "已完成";
    statusBadge.className = "badge ok";
  } else if (isFailed) {
    statusBadge.textContent = "执行失败";
    statusBadge.className = "badge warn";
  } else {
    statusBadge.textContent = "运行中";
    statusBadge.className = "badge";
  }

  const fill = $("#tracker-progress-fill");
  const pct = Math.min(100, Math.max(0, job?.progress ?? (isRunning ? 5 : 0)));
  fill.style.width = `${pct}%`;
  fill.className = `progress-bar-fill ${isCompleted ? "completed" : isFailed ? "failed" : ""}`;

  $("#tracker-percent-text").textContent = `${pct}%`;
  $("#tracker-status-text").textContent = job?.message || "正在准备迁移环境...";

  // Render 10 stages
  const currentStageKey = job?.stage || "preflight";
  const rawStageIdx = TRACKER_STAGES.findIndex((s) => s.key === currentStageKey);
  const currentStageIdx = rawStageIdx >= 0 ? rawStageIdx : (isFailed ? 0 : -1);

  const payloadItems = (job?.payload as { items?: Record<string, boolean> } | undefined)?.items;
  const selectedMap = payloadItems && Object.keys(payloadItems).length > 0 ? payloadItems : state.selectedItems;

  const stagesRoot = $("#tracker-stages");
  stagesRoot.innerHTML = TRACKER_STAGES.map((s, idx) => {
    let status: "pending" | "running" | "completed" | "skipped" | "failed" = "pending";
    let icon = "○";
    let sub = `阶段期望 ${s.percent}%`;

    const isSkipped = Boolean(s.itemKey && selectedMap[s.itemKey] === false);
    if (isSkipped) {
      status = "skipped";
      icon = "—";
      sub = "未勾选此项 · 已跳过";
    } else if (isCompleted) {
      status = "completed";
      icon = "✓";
      sub = "已成功完成";
    } else if (isFailed) {
      if (idx < currentStageIdx) {
        status = "completed";
        icon = "✓";
        sub = "已完成";
      } else if (idx === currentStageIdx) {
        status = "failed";
        icon = "✕";
        sub = "此阶段发生错误";
      } else {
        status = "pending";
        icon = "○";
        sub = "未执行";
      }
    } else if (isRunning) {
      if (idx < currentStageIdx) {
        status = "completed";
        icon = "✓";
        sub = "已完成";
      } else if (idx === currentStageIdx) {
        status = "running";
        icon = `<span class="banner-spinner" style="width:12px;height:12px;border-width:2px;border-color:rgba(255,255,255,0.4);border-top-color:#fff"></span>`;
        sub = "正在处理中...";
      } else {
        status = "pending";
        icon = "○";
        sub = "等待执行";
      }
    }

    return `
      <div class="stage-card ${status}">
        <div class="stage-icon ${status}">${icon}</div>
        <div class="stage-info">
          <div class="stage-title">${escapeHtml(s.name)}</div>
          <div class="stage-sub">${escapeHtml(sub)}</div>
        </div>
      </div>
    `;
  }).join("");

  // Failure Card & One-Click Rollback
  const failureCard = $("#tracker-failure-card");
  if (isFailed) {
    failureCard.classList.remove("hidden");
    const errMsg = job?.error?.message || "未知错误";
    $("#failure-error-msg").textContent = errMsg;
    const rollbackBtn = $("#btn-rollback") as HTMLButtonElement;
    rollbackBtn.onclick = () => {
      void handleOneClickRollback();
    };
  } else {
    failureCard.classList.add("hidden");
  }

  // Completion / reset actions
  const successActions = $("#tracker-success-actions");
  if (isCompleted || isFailed) {
    successActions.classList.remove("hidden");
  } else {
    successActions.classList.add("hidden");
  }
}

async function handleOneClickRollback(): Promise<void> {
  const targetEdition = state.currentJob?.payload?.to_edition || state.migTo || state.edition;
  const targetUid = state.currentJob?.payload?.target_uid;
  try {
    const res = await api.backups(targetEdition);
    const backups = res.backups || [];
    if (!backups.length) {
      toast("未找到可用于回滚的备份快照");
      return;
    }
    // Prefer target pre-migration snapshot for this specific target UID
    const targetBackup =
      (targetUid
        ? backups.find((b) => (b.label === "target" || b.label === "pre_migrate") && b.target_uid === targetUid)
        : null) ||
      backups.find((b) => b.label === "target" || b.label === "pre_migrate") ||
      backups[0];
    openRestoreModal(targetBackup);
  } catch (e) {
    toast("获取备份快照失败: " + (e as Error).message);
  }
}

function renderMigrateResult(r?: MigrateRunResult | null): void {
  if (!r) return;
  const panel = $("#mig-result-panel");
  panel.classList.remove("hidden");
  const warns = (r.warnings || []).map((w) => `<div class="banner warn">${escapeHtml(w)}</div>`).join("");
  const rows = (r.results || [])
    .map(
      (x) =>
        `<div class="list-item"><div><strong>${MIGRATE_LABELS[x.key] || x.key}</strong><div class="muted small">${escapeHtml(x.detail)}</div></div><span class="badge ${x.status === "success" ? "ok" : ""}">${escapeHtml(x.status)} · ${x.count}</span></div>`,
    )
    .join("");
  $("#mig-result").innerHTML =
    warns +
    (r.ok === false ? `<div class="banner warn">迁移未完全成功，请检查下方失败项。</div>` : "") +
    rows +
    `<div class="muted small" style="margin-top:.5rem">${r.need_restart ? "请重启客户端后查看。" : "完成"}</div>`;
  $("#step3").classList.add("on");
}

function startJobPolling(jobId: string): void {
  if (state.pollTimeout !== null) {
    window.clearTimeout(state.pollTimeout);
    state.pollTimeout = null;
  }
  if (state.timerInterval !== null) {
    window.clearInterval(state.timerInterval);
    state.timerInterval = null;
  }

  if (!state.jobStartTime) {
    const createdMs = state.currentJob?.created_at ? new Date(state.currentJob.created_at).getTime() : Date.now();
    state.jobStartTime = Number.isNaN(createdMs) ? Date.now() : createdMs;
  }

  state.timerInterval = window.setInterval(() => {
    if (state.jobStartTime) {
      const elapsed = Date.now() - state.jobStartTime;
      const timerEl = document.getElementById("tracker-timer");
      if (timerEl) timerEl.textContent = fmtElapsed(elapsed);
    }
  }, 500);

  const poll = async () => {
    try {
      const job = await api.migrateGetJob(jobId);
      state.currentJob = job;
      if (!state.jobStartTime && job.created_at) {
        const ms = new Date(job.created_at).getTime();
        if (!Number.isNaN(ms)) state.jobStartTime = ms;
      }
      renderTracker();
      applyConcurrencyLock();

      if (job.status === "completed") {
        state.isMigrating = false;
        sessionStorage.removeItem("wbt_active_job_id");
        sessionStorage.removeItem("wbt_job_start_time");
        sessionStorage.removeItem("wbt_selected_items");
        if (state.timerInterval !== null) {
          window.clearInterval(state.timerInterval);
          state.timerInterval = null;
        }
        applyConcurrencyLock();
        toast("迁移全部完成！请重启客户端生效。");
        await Promise.all([loadAccounts(), loadBackups()]);
        renderMigrateResult(job.result);
        return;
      }

      if (job.status === "failed") {
        state.isMigrating = false;
        sessionStorage.removeItem("wbt_active_job_id");
        sessionStorage.removeItem("wbt_job_start_time");
        sessionStorage.removeItem("wbt_selected_items");
        if (state.timerInterval !== null) {
          window.clearInterval(state.timerInterval);
          state.timerInterval = null;
        }
        applyConcurrencyLock();
        toast(`迁移失败: ${job.error?.message || "未知错误"}`);
        await loadBackups();
        return;
      }

      state.pollTimeout = window.setTimeout(poll, 600);
    } catch (e) {
      console.error("Poll job error", e);
      state.pollTimeout = window.setTimeout(poll, 1500);
    }
  };

  void poll();
}

async function runMigrate(): Promise<void> {
  if (!state.migratePlan) return;
  if (!confirm("确认执行迁移？系统将在迁移前自动创建完整一致性快照。")) return;
  ($("#btn-run") as HTMLButtonElement).disabled = true;

  try {
    const jobRes = await api.migrateCreateJob({
      from_edition: state.migratePlan.from_edition,
      to_edition: state.migratePlan.to_edition,
      source_uid: state.migratePlan.source_uid,
      target_uid: state.migratePlan.target_uid,
      items: state.selectedItems,
    });

    state.activeJobId = jobRes.job_id;
    state.isMigrating = true;
    state.jobStartTime = Date.now();
    sessionStorage.setItem("wbt_active_job_id", jobRes.job_id);
    sessionStorage.setItem("wbt_job_start_time", String(state.jobStartTime));
    sessionStorage.setItem("wbt_selected_items", JSON.stringify(state.selectedItems));

    renderTracker();
    applyConcurrencyLock();
    startJobPolling(jobRes.job_id);
    toast("迁移作业已启动");
  } catch (e) {
    const err = e as ApiError;
    if (err.code === "busy") {
      toast("已有任务正在进行中，请稍后再试");
    } else if (err.code === "client_running" || err.status === 409) {
      toast("客户端正在运行，请先完全退出客户端再执行迁移");
    } else {
      toast((e as Error).message);
    }
    applyConcurrencyLock();
  }
}

async function loadBackups(): Promise<void> {
  const edition = state.backupsEdition || state.edition;
  try {
    const res = await api.backups(edition);
    state.backups = res.backups || [];
    renderBackups();
  } catch {
    state.backups = [];
    renderBackups();
  }
}

function renderBackups(): void {
  const root = document.getElementById("backup-table-wrap");
  if (!root) return;

  const curEd = state.editions.find((e) => e.key === state.backupsEdition);
  const clientRunning = curEd?.client_running ?? false;

  if (!state.backups.length) {
    root.innerHTML = `<div class="empty" style="padding:1.5rem">当前版本暂无快照备份记录</div>`;
    return;
  }

  const rows = state.backups.map((bk) => {
    const labelInfo = backupLabelBadge(bk.label);
    const relTime = fmtRelativeTime(bk.created_at);
    const absTime = bk.created_at ? new Date(bk.created_at).toLocaleString() : bk.backup_id;
    const sizeStr = fmtBytes(bk.size_bytes || 0);
    const disabledAttr = (clientRunning || state.isMigrating) ? 'disabled title="客户端正在运行或迁移进行中，暂无法还原"' : "";

    return `
      <tr>
        <td>
          <div style="font-weight:600;color:var(--ink)">${escapeHtml(bk.backup_id)}</div>
          <div class="muted small">${escapeHtml(absTime)} (${escapeHtml(relTime)})</div>
        </td>
        <td>
          <span class="badge ${labelInfo.colorClass}">${escapeHtml(labelInfo.text)}</span>
        </td>
        <td>
          <div style="font-family:monospace;font-size:12px">${escapeHtml((bk.target_uid || "all").slice(0, 16))}…</div>
        </td>
        <td>
          <div><b>${bk.file_count}</b> 个文件</div>
          <div class="muted small">${sizeStr}</div>
        </td>
        <td style="text-align:right">
          <button class="btn small" data-restore="${escapeHtml(bk.backup_id)}" ${disabledAttr}>↩️ 还原</button>
        </td>
      </tr>
    `;
  }).join("");

  root.innerHTML = `
    <table class="backup-table">
      <thead>
        <tr>
          <th>快照 ID / 时间</th>
          <th>类型标签</th>
          <th>归属账号</th>
          <th>包含数据</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  root.querySelectorAll<HTMLButtonElement>("[data-restore]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const bkId = btn.dataset.restore!;
      const bk = state.backups.find((b) => b.backup_id === bkId);
      if (!bk) return;
      openRestoreModal(bk);
    });
  });
}

function openRestoreModal(bk: BackupItem): void {
  const curEd = state.editions.find((e) => e.key === bk.edition);
  if (curEd?.client_running) {
    toast(`检测到 ${curEd.short} 正在运行，请先完全退出客户端再执行还原。`);
    return;
  }
  if (state.isMigrating) {
    toast("迁移任务正在进行中，暂时无法执行还原操作。");
    return;
  }

  state.pendingRestoreBackup = bk;
  const modal = $("#restore-modal");
  const infoEl = $("#restore-modal-info");
  const checkEl = $("#restore-confirm-check") as HTMLInputElement;
  const doBtn = $("#btn-do-restore") as HTMLButtonElement;

  checkEl.checked = false;
  doBtn.disabled = true;

  const edName = bk.edition === "international" ? "WorkBuddyAI 国际版" : "WorkBuddy 国内版";
  const sizeStr = fmtBytes(bk.size_bytes || 0);
  const timeStr = bk.created_at ? new Date(bk.created_at).toLocaleString() : bk.backup_id;

  infoEl.innerHTML = `
    <div style="background:var(--bg-subtle);padding:0.75rem 0.9rem;border-radius:var(--radius-xs);border:1px solid var(--line);margin:0.5rem 0">
      <div><b>目标版本：</b> ${escapeHtml(edName)}</div>
      <div><b>快照标识：</b> <code>${escapeHtml(bk.backup_id)}</code></div>
      <div><b>备份时间：</b> ${escapeHtml(timeStr)}</div>
      <div><b>包含数据：</b> ${bk.file_count} 个文件 · ${sizeStr}</div>
    </div>
  `;

  modal.classList.remove("hidden");
}

function renderKpis(data: TokenSummary): void {
  const t = data.totals;
  const days = data.by_day || [];
  const daysCount = days.length || 1;
  const dailyAvg = t.daily_average ? t.daily_average : Math.round(t.total / daysCount);
  const inPct = t.total > 0 ? ((t.input / t.total) * 100).toFixed(1) + "%" : "0.0%";
  const outPct = t.total > 0 ? ((t.output / t.total) * 100).toFixed(1) + "%" : "0.0%";
  const hitRatePct = ((t.cache_hit_rate || 0) * 100).toFixed(1) + "%";

  const hitBadge =
    t.cache_hit_rate >= 0.9
      ? { text: "⚡ 高效命中", cls: "ok" }
      : t.cache_hit_rate >= 0.7
        ? { text: "良好", cls: "ok" }
        : t.cache_hit_rate > 0
          ? { text: "偏低", cls: "soft" }
          : { text: "常规", cls: "soft" };

  const isDailyScale = state.tokenRange === "today";
  const is24hScale = state.tokenRange === "24h";

  let card2Title = "每日总用量 (日均)";
  let card2Value = fmtNum(dailyAvg);
  let card2Badge = "平均走势";
  let card2Sub = `跨 ${daysCount} 天活跃消耗明细`;
  let card2Tooltip = `周期内日均消耗：${dailyAvg.toLocaleString()} tokens/天`;

  if (isDailyScale) {
    card2Title = "今日总用量";
    card2Value = fmtNum(t.total);
    card2Badge = "今日实时";
    card2Sub = "今日全量 Token 消耗";
    card2Tooltip = `今日总消耗：${t.total.toLocaleString()} tokens`;
  } else if (is24hScale) {
    card2Title = "24小时总用量";
    card2Value = fmtNum(t.total);
    card2Badge = "近24小时";
    card2Sub = "动态 24 小时全量消耗";
    card2Tooltip = `近 24 小时消耗：${t.total.toLocaleString()} tokens`;
  }

  const cardsHtml = `
    <div class="token-kpi-card" title="当前周期全量 Token 消耗：${t.total.toLocaleString()}">
      <div class="token-kpi-header">
        <span class="token-kpi-label"><span>📊</span>总消耗 Token</span>
        <span class="badge ${t.total > 0 ? "ok" : "soft"} token-kpi-badge">全量统计</span>
      </div>
      <div class="token-kpi-value">${fmtNum(t.total)}</div>
      <div class="token-kpi-sub">共计 ${fmtNum(t.events || 0)} 次模型交互记录</div>
    </div>

    <div class="token-kpi-card" title="${escapeHtml(card2Tooltip)}">
      <div class="token-kpi-header">
        <span class="token-kpi-label"><span>📅</span>${escapeHtml(card2Title)}</span>
        <span class="badge token-kpi-badge">${escapeHtml(card2Badge)}</span>
      </div>
      <div class="token-kpi-value">${escapeHtml(card2Value)}</div>
      <div class="token-kpi-sub">${escapeHtml(card2Sub)}</div>
    </div>

    <div class="token-kpi-card" title="输入 Prompt：${t.input.toLocaleString()} tokens">
      <div class="token-kpi-header">
        <span class="token-kpi-label"><span>📥</span>输入 Token</span>
        <span class="badge token-kpi-badge">Prompt</span>
      </div>
      <div class="token-kpi-value">${fmtNum(t.input)}</div>
      <div class="token-kpi-sub">占总用量比例 ${inPct}</div>
    </div>

    <div class="token-kpi-card" title="输出 Completion：${t.output.toLocaleString()} tokens">
      <div class="token-kpi-header">
        <span class="token-kpi-label"><span>📤</span>输出 Token</span>
        <span class="badge token-kpi-badge">Completion</span>
      </div>
      <div class="token-kpi-value">${fmtNum(t.output)}</div>
      <div class="token-kpi-sub">占总用量比例 ${outPct}</div>
    </div>

    <div class="token-kpi-card" title="缓存读取：${t.cache_read.toLocaleString()} tokens">
      <div class="token-kpi-header">
        <span class="token-kpi-label"><span>⚡</span>缓存读取 Token</span>
        <span class="badge ok token-kpi-badge">Cache Read</span>
      </div>
      <div class="token-kpi-value" style="color:#059669">${fmtNum(t.cache_read)}</div>
      <div class="token-kpi-sub">免重复推理的高速缓存</div>
    </div>

    <div class="token-kpi-card" title="缓存命中率 = 缓存读取 / 总输入 (Prompt) · ≥90% 为高效">
      <div class="token-kpi-header">
        <span class="token-kpi-label"><span>🎯</span>综合缓存命中率</span>
        <span class="badge ${hitBadge.cls} token-kpi-badge">${hitBadge.text}</span>
      </div>
      <div class="token-kpi-value" style="color:${t.cache_hit_rate >= 0.9 ? "#059669" : "inherit"}">${hitRatePct}</div>
      <div class="token-kpi-sub">缓存读取 / 总输入 · ≥90% 为高效</div>
    </div>
  `;
  const el = document.getElementById("token-kpis");
  if (el) el.innerHTML = cardsHtml;
}

function renderBar(data: TokenSummary): void {
  const chartEl = document.getElementById("bar-chart");
  const summaryEl = document.getElementById("chart-daily-summary");
  if (!chartEl) return;

  const days = data.by_day || [];
  if (!days.length) {
    chartEl.innerHTML = `<div class="empty" style="padding:3.5rem 1rem">所选时间尺度内暂无 Token 消耗数据</div>`;
    if (summaryEl) summaryEl.textContent = "无数据";
    return;
  }

  const daysCount = days.length;
  const grandTotal = data.totals.total;
  const avgDaily = Math.round(grandTotal / daysCount);
  const defaultSummary = `共 ${daysCount} 天 · 每日均量 ${fmtNum(avgDaily)}`;
  if (summaryEl) {
    summaryEl.textContent = defaultSummary;
  }

  const W = 700;
  const H = 260;
  const padL = 54;
  const padB = 36;
  const padT = 32;
  const padR = 16;
  const max = Math.max(1, ...days.map((d) => d.total || 0));
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const groupW = innerW / days.length;
  const barW = Math.max(3, Math.min(32, groupW * 0.68));

  let barsHtml = "";
  days.forEach((d, di) => {
    const x = padL + di * groupW + (groupW - barW) / 2;
    const dayTotal = d.total || 0;
    const totalBarH = (dayTotal / max) * innerH;
    let currentY = padT + innerH;

    const mSegments = (d.by_model || []).map((m) => {
      const segH = dayTotal > 0 ? ((m.total || 0) / dayTotal) * totalBarH : 0;
      currentY -= segH;
      return `<rect x="${x}" y="${currentY}" width="${barW}" height="${Math.max(segH, 0)}" fill="${safeColor(m.color)}" rx="1"><title>${d.date}\n${escapeHtml(m.model)}: ${(m.total || 0).toLocaleString()} tokens</title></rect>`;
    }).join("");

    const labelY = padT + innerH - totalBarH - 6;
    const isPeak = dayTotal === max && dayTotal > 0;
    const showLabel = dayTotal > 0 && (days.length <= 14 || isPeak);
    const totalLabel = showLabel
      ? `<text x="${x + barW / 2}" y="${Math.max(14, labelY)}" text-anchor="middle" font-size="${days.length > 14 ? "9.5" : "10.5"}" font-weight="700" fill="${isPeak && days.length > 14 ? "#4f46e5" : "#0f172a"}">${fmtNum(dayTotal)}</text>`
      : "";

    const dayDetails = (d.by_model || [])
      .map((m) => `• ${m.model}: ${(m.total || 0).toLocaleString()} (${dayTotal > 0 ? ((m.total / dayTotal) * 100).toFixed(1) : 0}%)`)
      .join("\n");
    const dayTitle = `<title>日期：${d.date}\n每日总用量：${dayTotal.toLocaleString()} tokens\n------------------\n${dayDetails}</title>`;

    barsHtml += `
      <g class="chart-day-group" data-date="${escapeHtml(d.date)}" data-total="${dayTotal}" style="cursor:pointer">
        ${dayTitle}
        ${mSegments}
        ${totalLabel}
      </g>
    `;
  });

  const labelsHtml = days
    .map((d, i) => {
      if (days.length > 14 && i % Math.ceil(days.length / 10) !== 0 && i !== days.length - 1) return "";
      const x = padL + i * groupW + groupW / 2;
      const labelText = d.date.length > 5 ? d.date.slice(5) : d.date;
      return `<text x="${x}" y="${H - 10}" text-anchor="middle" font-size="10.5" font-weight="500" fill="#64748b">${labelText}</text>`;
    })
    .join("");

  const yTicksHtml = [0, 0.5, 1]
    .map((p) => {
      const y = padT + innerH - p * innerH;
      return `
        <line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="#e8ecf4" stroke-dasharray="${p === 0 ? "none" : "3,3"}" />
        <text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="10" font-weight="500" fill="#64748b">${fmtNum(max * p)}</text>
      `;
    })
    .join("");

  chartEl.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="260" style="overflow:visible">${yTicksHtml}${barsHtml}${labelsHtml}</svg>`;

  chartEl.querySelectorAll<SVGGElement>(".chart-day-group").forEach((g) => {
    g.addEventListener("mouseenter", () => {
      const date = g.getAttribute("data-date") || "";
      const total = Number(g.getAttribute("data-total") || "0");
      if (summaryEl) {
        summaryEl.textContent = `${date} · ${fmtNum(total)} 用量`;
      }
    });
    g.addEventListener("mouseleave", () => {
      if (summaryEl) {
        summaryEl.textContent = defaultSummary;
      }
    });
  });
}

function renderPie(data: TokenSummary): void {
  const pieEl = document.getElementById("pie-chart");
  const shareListEl = document.getElementById("pie-share-list");
  if (!pieEl || !shareListEl) return;

  const models = data.by_model || [];
  const total = models.reduce((s, m) => s + (m.total || 0), 0);

  if (!total) {
    pieEl.innerHTML = `<div class="empty" style="padding:2.5rem 1rem">暂无数据</div>`;
    shareListEl.innerHTML = "";
    return;
  }

  const cx = 70;
  const cy = 70;
  const r = 54;
  let angle = -Math.PI / 2;
  let paths = "";

  models.forEach((m) => {
    const frac = (m.total || 0) / total;
    if (frac <= 0) return;
    const sweep = frac * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + sweep);
    const y2 = cy + r * Math.sin(angle + sweep);
    const large = sweep > Math.PI ? 1 : 0;
    if (frac > 0.999) {
      paths += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${safeColor(m.color)}"><title>${escapeHtml(m.model)}: ${(m.total || 0).toLocaleString()} (100%)</title></circle>`;
    } else {
      paths += `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z" fill="${safeColor(m.color)}"><title>${escapeHtml(m.model)}: ${(m.total || 0).toLocaleString()} (${(frac * 100).toFixed(1)}%)</title></path>`;
    }
    angle += sweep;
  });

  paths += `<circle cx="${cx}" cy="${cy}" r="34" fill="#ffffff" />`;
  paths += `<text x="${cx}" y="${cy - 3}" text-anchor="middle" font-size="9" font-weight="600" fill="#64748b">总用量</text>`;
  paths += `<text x="${cx}" y="${cy + 13}" text-anchor="middle" font-size="12" font-weight="750" fill="#0f172a">${fmtNum(total)}</text>`;

  pieEl.innerHTML = `<svg viewBox="0 0 140 140" width="130" height="130">${paths}</svg>`;

  shareListEl.innerHTML = models
    .map((m) => {
      const sharePct = m.percent !== undefined ? m.percent : total > 0 ? Math.round(((m.total || 0) / total) * 1000) / 10 : 0;
      return `
        <div class="model-share-row" title="${escapeHtml(m.model)} 消耗 ${(m.total || 0).toLocaleString()} tokens">
          <div class="model-share-header">
            <div class="model-name-group">
              <span class="swatch" style="background:${safeColor(m.color)}"></span>
              <span class="model-title" title="${escapeHtml(m.model)}">${escapeHtml(m.model)}</span>
            </div>
            <div class="model-stat-group">
              <span class="model-share-pct">${sharePct}%</span>
              <span class="model-tokens-count muted small">(${fmtNum(m.total || 0)})</span>
            </div>
          </div>
          <div class="model-progress-bg">
            <div class="model-progress-fill" style="width:${Math.max(1, Math.min(100, sharePct))}%;background:${safeColor(m.color)}"></div>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderTokenTable(data: TokenSummary): void {
  const wrap = document.getElementById("token-table-wrap");
  const countBadge = document.getElementById("token-table-count");
  const titleEl = document.getElementById("token-table-title");
  if (!wrap) return;

  const models = data.by_model || [];
  const days = data.by_day || [];
  const t = data.totals;

  // Sync tab active states
  const modelTab = document.getElementById("tab-table-model");
  const dayTab = document.getElementById("tab-table-day");
  if (modelTab) modelTab.classList.toggle("active", state.tokenTableView === "model");
  if (dayTab) dayTab.classList.toggle("active", state.tokenTableView === "day");

  if (state.tokenTableView === "day") {
    if (titleEl) titleEl.textContent = "每日用量明细与走势";
    if (countBadge) countBadge.textContent = `${days.length} 天用量记录`;

    if (!days.length) {
      wrap.innerHTML = `<div class="empty" style="padding:2rem">当前时间尺度内暂无每日用量记录</div>`;
      return;
    }

    const rowsHtml = days.map((d) => {
      const dayTotal = d.total || 0;
      const sharePct = t.total > 0 ? Math.round((dayTotal / t.total) * 1000) / 10 : 0;
      const dInput = d.input !== undefined ? d.input : (d.by_model || []).reduce((s, m) => s + (m.input || 0), 0);
      const dOutput = d.output !== undefined ? d.output : (d.by_model || []).reduce((s, m) => s + (m.output || 0), 0);
      const dCache = d.cache_read !== undefined ? d.cache_read : (d.by_model || []).reduce((s, m) => s + (m.cache_read || 0), 0);
      const dPrompt = dInput >= dCache ? dInput : dInput + dCache;
      const hitRate = d.cache_hit_rate !== undefined ? d.cache_hit_rate : (dPrompt > 0 ? dCache / dPrompt : 0);
      const hitPct = (hitRate * 100).toFixed(1) + "%";

      let hitBadgeClass = "hit-none";
      if (hitRate >= 0.9) hitBadgeClass = "hit-high";
      else if (hitRate >= 0.7) hitBadgeClass = "hit-mid";
      else if (hitRate > 0) hitBadgeClass = "hit-low";

      const topModel = (d.by_model || [])[0];
      const topModelHtml = topModel
        ? `<div style="display:flex;align-items:center;gap:5px"><span class="swatch" style="background:${safeColor(topModel.color)}"></span><span style="font-size:11.5px">${escapeHtml(topModel.model)}</span></div>`
        : `<span class="muted small">-</span>`;

      return `
        <tr>
          <td><strong style="color:var(--ink)">${escapeHtml(d.date)}</strong></td>
          <td>
            <div style="display:flex;align-items:center;gap:6px">
              <span style="font-weight:700">${sharePct}%</span>
              <div style="width:46px;height:5px;background:var(--bg-subtle);border-radius:99px;overflow:hidden">
                <div style="width:${sharePct}%;height:100%;background:var(--primary)"></div>
              </div>
            </div>
          </td>
          <td>
            <span style="font-weight:700;font-size:13px">${fmtNum(dayTotal)}</span>
            <span class="muted small" style="margin-left:3px">(${dayTotal.toLocaleString()})</span>
          </td>
          <td><span>${fmtNum(dInput)}</span></td>
          <td><span>${fmtNum(dOutput)}</span></td>
          <td><span style="color:#059669;font-weight:600">${fmtNum(dCache)}</span></td>
          <td><span class="hit-pill ${hitBadgeClass}">${hitPct}</span></td>
          <td>${topModelHtml}</td>
        </tr>
      `;
    }).join("");

    const tHitPct = ((t.cache_hit_rate || 0) * 100).toFixed(1) + "%";
    const tHitBadgeClass = t.cache_hit_rate >= 0.9 ? "hit-high" : t.cache_hit_rate >= 0.7 ? "hit-mid" : t.cache_hit_rate > 0 ? "hit-low" : "hit-none";

    wrap.innerHTML = `
      <table class="token-table">
        <thead>
          <tr>
            <th>统计日期</th>
            <th>占周期比例</th>
            <th>每日总用量</th>
            <th>输入 (Prompt)</th>
            <th>输出 (Completion)</th>
            <th>缓存读取 (Cache)</th>
            <th>缓存命中率</th>
            <th>主要消耗模型</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
        <tfoot>
          <tr>
            <td><strong>全周期合计 (${days.length} 天)</strong></td>
            <td><strong>100.0%</strong></td>
            <td><strong>${fmtNum(t.total)} <span class="muted small">(${t.total.toLocaleString()})</span></strong></td>
            <td><strong>${fmtNum(t.input)}</strong></td>
            <td><strong>${fmtNum(t.output)}</strong></td>
            <td><strong style="color:#059669">${fmtNum(t.cache_read)}</strong></td>
            <td><span class="hit-pill ${tHitBadgeClass}">${tHitPct}</span></td>
            <td><span class="muted small">${models.length} 个模型</span></td>
          </tr>
        </tfoot>
      </table>
    `;
    return;
  }

  // Otherwise: model view
  if (titleEl) titleEl.textContent = "各模型详细数据与缓存命中率";
  if (countBadge) countBadge.textContent = `${models.length} 个模型统计`;

  if (!models.length) {
    wrap.innerHTML = `<div class="empty" style="padding:2rem">当前时间尺度内暂无各模型明细数据</div>`;
    return;
  }

  const rowsHtml = models.map((m) => {
    const sharePct = m.percent !== undefined ? m.percent : t.total > 0 ? Math.round(((m.total || 0) / t.total) * 1000) / 10 : 0;
    const hitRate = m.cache_hit_rate || 0;
    const hitPct = (hitRate * 100).toFixed(1) + "%";

    let hitBadgeClass = "hit-none";
    let statusText = "常规 / 无缓存";
    if (hitRate >= 0.9) {
      hitBadgeClass = "hit-high";
      statusText = "极佳 ⚡";
    } else if (hitRate >= 0.7) {
      hitBadgeClass = "hit-mid";
      statusText = "良好";
    } else if (hitRate > 0) {
      hitBadgeClass = "hit-low";
      statusText = "偏低";
    }

    const inRatio = m.total > 0 ? Math.round((m.input / m.total) * 100) : 0;
    const outRatio = m.total > 0 ? Math.round((m.output / m.total) * 100) : 0;

    return `
      <tr>
        <td>
          <div style="display:flex;align-items:center;gap:6px">
            <span class="swatch" style="background:${safeColor(m.color)}"></span>
            <strong style="font-family:monospace;font-size:12px;color:var(--ink)">${escapeHtml(m.model)}</strong>
          </div>
        </td>
        <td>
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-weight:700">${sharePct}%</span>
            <div style="width:46px;height:5px;background:var(--bg-subtle);border-radius:99px;overflow:hidden">
              <div style="width:${sharePct}%;height:100%;background:${safeColor(m.color)}"></div>
            </div>
          </div>
        </td>
        <td>
          <span style="font-weight:700;font-size:13px">${fmtNum(m.total)}</span>
          <span class="muted small" style="margin-left:3px">(${m.total.toLocaleString()})</span>
        </td>
        <td>
          <span>${fmtNum(m.input)}</span>
          <span class="muted small" style="margin-left:2px">${inRatio}%</span>
        </td>
        <td>
          <span>${fmtNum(m.output)}</span>
          <span class="muted small" style="margin-left:2px">${outRatio}%</span>
        </td>
        <td>
          <span style="color:#059669;font-weight:600">${fmtNum(m.cache_read)}</span>
        </td>
        <td>
          <span class="hit-pill ${hitBadgeClass}">${hitPct}</span>
        </td>
        <td>
          <span class="muted small">${statusText}</span>
        </td>
      </tr>
    `;
  }).join("");

  const tHitPct = ((t.cache_hit_rate || 0) * 100).toFixed(1) + "%";
  const tHitBadgeClass = t.cache_hit_rate >= 0.9 ? "hit-high" : t.cache_hit_rate >= 0.7 ? "hit-mid" : t.cache_hit_rate > 0 ? "hit-low" : "hit-none";

  wrap.innerHTML = `
    <table class="token-table">
      <thead>
        <tr>
          <th>模型名称</th>
          <th>用量占比</th>
          <th>总 Token</th>
          <th>输入 (Prompt)</th>
          <th>输出 (Completion)</th>
          <th>缓存读取 (Cache)</th>
          <th>缓存命中率</th>
          <th>效率评级</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
      <tfoot>
        <tr>
          <td><strong>全周期合计 (${models.length} 个模型)</strong></td>
          <td><strong>100.0%</strong></td>
          <td><strong>${fmtNum(t.total)} <span class="muted small">(${t.total.toLocaleString()})</span></strong></td>
          <td><strong>${fmtNum(t.input)}</strong></td>
          <td><strong>${fmtNum(t.output)}</strong></td>
          <td><strong style="color:#059669">${fmtNum(t.cache_read)}</strong></td>
          <td><span class="hit-pill ${tHitBadgeClass}">${tHitPct}</span></td>
          <td><span class="muted small">整体效率</span></td>
        </tr>
      </tfoot>
    </table>
  `;
}

function setTokenRange(range: string): void {
  state.tokenRange = range;
  document.querySelectorAll(".scale-tab").forEach((tab) => {
    const r = (tab as HTMLElement).dataset.range;
    tab.classList.toggle("active", r === range);
  });
  const sel = document.querySelector<HTMLSelectElement>("#token-range");
  if (sel) sel.value = range;
  void loadTokens();
}

async function loadTokens(): Promise<void> {
  const range = state.tokenRange || ($("#token-range") as HTMLSelectElement)?.value || "7d";
  const refreshIcon = document.getElementById("token-refresh-icon");
  if (refreshIcon) refreshIcon.classList.add("spinning");
  try {
    const data = await api.tokens(state.edition, range);
    state.tokenData = data;
    renderKpis(data);
    renderBar(data);
    renderPie(data);
    renderTokenTable(data);
  } catch (e) {
    toast((e as Error).message);
  } finally {
    if (refreshIcon) refreshIcon.classList.remove("spinning");
  }
}

async function openExternal(url: string): Promise<void> {
  try {
    await api.openUrl(url);
  } catch {
    if (typeof window !== "undefined") {
      window.open(url, "_blank");
    }
  }
}

async function doCheckUpdate(manual: boolean): Promise<void> {
  if (state.isCheckingUpdate) return;
  state.isCheckingUpdate = true;

  const spinAbout = document.getElementById("update-spin-icon");
  const updateBadge = document.getElementById("update-badge");
  const statusText = document.getElementById("update-status-text");

  if (spinAbout) spinAbout.classList.add("spinning");
  if (updateBadge) {
    updateBadge.textContent = "检查中...";
    updateBadge.className = "badge soft";
  }

  try {
    const res = await api.checkUpdate();
    state.latestUpdate = res;

    if (res.has_update) {
      if (updateBadge) {
        updateBadge.textContent = `发现新版 v${res.latest_version}`;
        updateBadge.className = "badge ok";
      }
      if (statusText) {
        statusText.textContent = `发现新版本：v${res.latest_version} (当前 v${APP_VERSION})`;
      }

      openUpdateModal(res);

      const banner = document.getElementById("global-update-banner");
      if (banner) {
        banner.innerHTML = `
          <div class="banner-info">
            <span>🎉 发现 WorkBuddy Tools 新版本 <b>v${escapeHtml(res.latest_version)}</b>！</span>
          </div>
          <button class="btn-banner-view" id="btn-banner-update-view">立即查看更新 →</button>
        `;
        banner.classList.remove("hidden");
        const btn = document.getElementById("btn-banner-update-view");
        if (btn) btn.onclick = () => openUpdateModal(res);
      }

      if (manual) {
        toast(`发现新版本 v${res.latest_version}！`);
      }
    } else if (res.error) {
      if (updateBadge) {
        updateBadge.textContent = "检查失败";
        updateBadge.className = "badge warn";
      }
      if (statusText) {
        statusText.textContent = `检查更新异常：${res.error}`;
      }
      if (manual) {
        toast(res.error);
      }
    } else {
      if (updateBadge) {
        updateBadge.textContent = "已是最新版 ✓";
        updateBadge.className = "badge ok";
      }
      if (statusText) {
        statusText.textContent = `当前已是最新版本 (v${APP_VERSION})`;
      }
      if (manual) {
        toast(`当前已是最新版本 (v${APP_VERSION})`);
      }
    }
  } catch (e) {
    if (manual) {
      toast("检查更新失败: " + (e as Error).message);
    }
    if (updateBadge) {
      updateBadge.textContent = "检查失败";
      updateBadge.className = "badge warn";
    }
  } finally {
    state.isCheckingUpdate = false;
    if (spinAbout) spinAbout.classList.remove("spinning");
  }
}

function openUpdateModal(res: UpdateCheckResult): void {
  const modal = document.getElementById("update-modal");
  if (!modal) return;

  const verEl = document.getElementById("update-modal-ver");
  const dateEl = document.getElementById("update-modal-date");
  const nameEl = document.getElementById("update-modal-name");
  const notesEl = document.getElementById("update-modal-notes");
  const dlBtn = document.getElementById("btn-update-download") as HTMLButtonElement | null;
  const modalAutoCheck = document.getElementById("check-modal-auto-update") as HTMLInputElement | null;

  if (verEl) verEl.textContent = `v${res.latest_version}`;
  if (dateEl) dateEl.textContent = res.published_at ? new Date(res.published_at).toLocaleDateString() : "";
  if (nameEl) nameEl.textContent = res.release_name || `WorkBuddy Tools v${res.latest_version}`;
  if (notesEl) notesEl.textContent = res.release_notes || "暂无详细更新说明，建议访问 GitHub Releases 查看完整日志。";

  if (modalAutoCheck) {
    const pref = localStorage.getItem("wbt_auto_check_update");
    modalAutoCheck.checked = pref !== "false";
  }

  if (dlBtn) {
    dlBtn.onclick = () => {
      const url = res.download_url || res.html_url || `${GITHUB_REPO_URL}/releases`;
      void openExternal(url);
    };
  }

  modal.classList.remove("hidden");
}

function bind(): void {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => setPage((btn as HTMLElement).dataset.page!));
  });
  $("#btn-refresh").addEventListener("click", async () => {
    try {
      await loadEditions();
      await loadAccounts();
      if (state.page === "tokens") await loadTokens();
      if (state.page === "migrate") await loadBackups();
    } catch (e) {
      toast((e as Error).message);
    }
  });
  ($("#edition-select") as HTMLSelectElement).addEventListener("change", async (e) => {
    state.edition = (e.target as HTMLSelectElement).value;
    state.backupsEdition = state.edition;
    renderPill();
    await loadAccounts();
    if (state.page === "tokens") await loadTokens();
    if (state.page === "migrate") await loadBackups();
  });
  ($("#mig-from") as HTMLSelectElement).addEventListener("change", () => void fillMigrateSelects());
  ($("#mig-to") as HTMLSelectElement).addEventListener("change", () => void fillMigrateSelects());
  $("#btn-plan").addEventListener("click", () => void loadPlan());
  $("#btn-run").addEventListener("click", () => void runMigrate());
  $("#btn-token").addEventListener("click", () => void loadTokens());
  ($("#token-range") as HTMLSelectElement).addEventListener("change", (e) => {
    const val = (e.target as HTMLSelectElement).value;
    setTokenRange(val);
  });
  document.querySelectorAll(".scale-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const r = (tab as HTMLElement).dataset.range;
      if (r) setTokenRange(r);
    });
  });

  // Table view tabs (Model vs Day)
  const tabModel = document.getElementById("tab-table-model");
  const tabDay = document.getElementById("tab-table-day");
  if (tabModel) {
    tabModel.addEventListener("click", () => {
      state.tokenTableView = "model";
      if (state.tokenData) renderTokenTable(state.tokenData);
    });
  }
  if (tabDay) {
    tabDay.addEventListener("click", () => {
      state.tokenTableView = "day";
      if (state.tokenData) renderTokenTable(state.tokenData);
    });
  }


  // GitHub graphical buttons (About page)
  ["#btn-about-github-main", "#gh-link-repo"].forEach((sel) => {
    const el = document.querySelector(sel);
    if (el) el.addEventListener("click", () => void openExternal(GITHUB_REPO_URL));
  });
  const ghReleases = document.querySelector("#gh-link-releases");
  if (ghReleases) ghReleases.addEventListener("click", () => void openExternal(`${GITHUB_REPO_URL}/releases`));
  const ghIssues = document.querySelector("#gh-link-issues");
  if (ghIssues) ghIssues.addEventListener("click", () => void openExternal(`${GITHUB_REPO_URL}/issues`));

  // Update check buttons (About page)
  const checkUpdateBtn = document.querySelector("#btn-check-update");
  if (checkUpdateBtn) checkUpdateBtn.addEventListener("click", () => void doCheckUpdate(true));

  // Auto-check on startup checkboxes (synchronized between About page and Update Modal)
  const autoCheckInput = document.querySelector<HTMLInputElement>("#check-auto-update");
  const modalAutoCheck = document.querySelector<HTMLInputElement>("#check-modal-auto-update");

  const syncAutoCheck = (checked: boolean) => {
    localStorage.setItem("wbt_auto_check_update", checked ? "true" : "false");
    if (autoCheckInput) autoCheckInput.checked = checked;
    if (modalAutoCheck) modalAutoCheck.checked = checked;
    toast(checked ? "已开启「每次打开自动检查更新」" : "已关闭「每次打开自动检查更新」");
  };

  if (autoCheckInput) {
    const pref = localStorage.getItem("wbt_auto_check_update");
    autoCheckInput.checked = pref !== "false";
    autoCheckInput.addEventListener("change", () => syncAutoCheck(autoCheckInput.checked));
  }
  if (modalAutoCheck) {
    const pref = localStorage.getItem("wbt_auto_check_update");
    modalAutoCheck.checked = pref !== "false";
    modalAutoCheck.addEventListener("change", () => syncAutoCheck(modalAutoCheck.checked));
  }

  // Update modal dismiss buttons and backdrop click
  const cancelUpdate = document.querySelector("#btn-update-cancel");
  const updateModalClose = document.querySelector("#btn-update-modal-close");
  const updateModal = document.querySelector("#update-modal");

  const closeUpdateModal = () => {
    if (updateModal) updateModal.classList.add("hidden");
  };

  if (cancelUpdate) cancelUpdate.addEventListener("click", closeUpdateModal);
  if (updateModalClose) updateModalClose.addEventListener("click", closeUpdateModal);
  if (updateModal) {
    updateModal.addEventListener("click", (e) => {
      if (e.target === updateModal) closeUpdateModal();
    });
  }
  $("#btn-add").addEventListener("click", async () => {
    const uid = ($("#add-uid") as HTMLInputElement).value.trim();
    const label = ($("#add-label") as HTMLInputElement).value.trim();
    if (!uid) {
      toast("请输入账号 ID");
      return;
    }
    try {
      await api.addProfile(state.edition, uid, label);
      toast("已保存");
      ($("#add-uid") as HTMLInputElement).value = "";
      ($("#add-label") as HTMLInputElement).value = "";
      await loadAccounts();
    } catch (e) {
      toast((e as Error).message);
    }
  });
  $("#btn-open").addEventListener("click", async () => {
    try {
      await api.openClient(state.edition);
      toast("正在打开客户端…");
    } catch (e) {
      toast((e as Error).message);
    }
  });

  const resetTrackerBtn = document.getElementById("btn-reset-tracker");
  if (resetTrackerBtn) {
    resetTrackerBtn.addEventListener("click", () => {
      state.currentJob = null;
      renderTracker();
      const resPanel = document.getElementById("mig-result-panel");
      if (resPanel) resPanel.classList.add("hidden");
    });
  }

  const bkEdSelect = document.getElementById("backup-edition-select") as HTMLSelectElement | null;
  if (bkEdSelect) {
    bkEdSelect.addEventListener("change", async (e) => {
      state.backupsEdition = (e.target as HTMLSelectElement).value;
      await loadBackups();
    });
  }

  // Manual Backup Creation Button
  const createBkBtn = document.querySelector("#btn-create-backup");
  if (createBkBtn) {
    createBkBtn.addEventListener("click", async () => {
      const btn = createBkBtn as HTMLButtonElement;
      btn.disabled = true;
      btn.textContent = "创建中…";
      try {
        const res = await api.createBackup(state.edition, undefined, "manual");
        toast(`快照创建成功: ${res.backup_id}`);
        await loadBackups();
      } catch (e) {
        const err = e as ApiError;
        if (err.code === "busy") {
          toast("已有任务正在进行中，请稍后再试");
        } else if (err.code === "client_running" || err.status === 409) {
          toast("客户端正在运行，请先完全退出客户端再创建快照");
        } else {
          toast("创建快照失败: " + (e as Error).message);
        }
      } finally {
        btn.textContent = "+ 创建即时快照";
        btn.disabled = false;
      }
    });
  }

  const restoreConfirmCheck = document.getElementById("restore-confirm-check") as HTMLInputElement | null;
  const doRestoreBtn = document.getElementById("btn-do-restore") as HTMLButtonElement | null;
  const cancelRestoreBtn = document.getElementById("btn-cancel-restore");
  const restoreModal = document.getElementById("restore-modal");

  if (restoreConfirmCheck && doRestoreBtn) {
    restoreConfirmCheck.addEventListener("change", () => {
      doRestoreBtn.disabled = !restoreConfirmCheck.checked;
    });
  }

  if (cancelRestoreBtn && restoreModal) {
    cancelRestoreBtn.addEventListener("click", () => {
      restoreModal.classList.add("hidden");
      state.pendingRestoreBackup = null;
    });
  }

  if (doRestoreBtn && restoreModal) {
    doRestoreBtn.addEventListener("click", async () => {
      if (!state.pendingRestoreBackup) return;
      const bk = state.pendingRestoreBackup;
      doRestoreBtn.disabled = true;
      doRestoreBtn.textContent = "还原中...";
      try {
        const res = await api.restoreBackup(bk.edition, bk.backup_id);
        restoreModal.classList.add("hidden");
        state.pendingRestoreBackup = null;
        toast(`快照还原成功！已恢复 ${res.restored_files?.length || 0} 个文件，请重启客户端。`);
        await Promise.all([loadAccounts(), loadBackups()]);
      } catch (e) {
        const err = e as ApiError;
        if (err.code === "busy") {
          toast("已有任务正在进行中，请稍后再试");
        } else if (err.code === "client_running" || err.status === 409) {
          toast("客户端正在运行，请先退出客户端再还原");
        } else {
          toast("还原失败: " + (e as Error).message);
        }
      } finally {
        doRestoreBtn.textContent = "确认执行还原";
        doRestoreBtn.disabled = false;
      }
    });
  }
}

async function init(): Promise<void> {
  // Clear any legacy demo mode flag so production always uses real data
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem("wbt_demo_mode");
  }
  const params = new URLSearchParams(window.location.search);
  renderShell();
  bind();
  try {
    await loadEditions();
    await loadAccounts();
  } catch (e) {
    toast("无法连接本地服务：" + (e as Error).message);
  }

  // Restore active job from sessionStorage if reload occurred
  const savedJobId = sessionStorage.getItem("wbt_active_job_id");
  if (savedJobId) {
    state.activeJobId = savedJobId;
    state.isMigrating = true;
    const savedStart = sessionStorage.getItem("wbt_job_start_time");
    if (savedStart) state.jobStartTime = Number(savedStart);
    const savedItems = sessionStorage.getItem("wbt_selected_items");
    if (savedItems) {
      try {
        state.selectedItems = JSON.parse(savedItems);
      } catch {}
    }
    startJobPolling(savedJobId);
  }

  window.addEventListener("focus", () => {
    if (state.isMigrating && state.activeJobId) {
      void api.migrateGetJob(state.activeJobId).then((job) => {
        state.currentJob = job;
        renderTracker();
        applyConcurrencyLock();
      }).catch(() => {});
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.isMigrating && state.activeJobId) {
      void api.migrateGetJob(state.activeJobId).then((job) => {
        state.currentJob = job;
        renderTracker();
        applyConcurrencyLock();
      }).catch(() => {});
    }
  });

  // Support direct URL routing for screenshots / demo links
  const targetPage = params.get("page");
  if (targetPage && ["accounts", "migrate", "tokens", "about"].includes(targetPage)) {
    setPage(targetPage);
  }
  if (targetPage === "migrate") {
    const fromParam = params.get("from");
    const toParam = params.get("to");
    if (fromParam) ($("#mig-from") as HTMLSelectElement).value = fromParam;
    if (toParam) ($("#mig-to") as HTMLSelectElement).value = toParam;
    await fillMigrateSelects();
    const sourceParam = params.get("source");
    const targetParam = params.get("target");
    if (sourceParam) ($("#mig-source") as HTMLSelectElement).value = sourceParam;
    if (targetParam) ($("#mig-target") as HTMLSelectElement).value = targetParam;
    if (params.has("plan")) {
      await loadPlan();
    }
    await loadBackups();
  }
  if (targetPage === "tokens") {
    const rangeParam = params.get("range");
    if (rangeParam && ["today", "24h", "7d", "30d", "90d"].includes(rangeParam)) {
      setTokenRange(rangeParam);
    } else {
      await loadTokens();
    }
  }

  // Auto-check for updates on startup if enabled
  const autoCheckEnabled = localStorage.getItem("wbt_auto_check_update") !== "false";
  if (autoCheckEnabled) {
    window.setTimeout(() => {
      void doCheckUpdate(false);
    }, 1200);
  }
}

void init();
