import "./styles.css";
import logoUrl from "./assets/logo.svg";
import {
  api,
  type AccountInfo,
  type EditionInfo,
  type MigratePlan,
  type TokenSummary,
  type WorkspaceInfo,
} from "./api";

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
  tokenData: null as TokenSummary | null,
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
      <div class="side-foot"><span id="client-pill" class="pill">检测中…</span></div>
    </aside>
    <main class="main">
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
        <div class="panel">
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
          <div class="panel-head"><h2>结果</h2></div>
          <div id="mig-result" class="list"></div>
        </div>
      </section>

      <section id="page-tokens" class="page">
        <div class="panel">
          <div class="panel-head">
            <h2>Token 用量</h2>
            <div class="row">
              <select id="token-range" class="select">
                <option value="today">今天</option>
                <option value="24h">24 小时</option>
                <option value="7d" selected>7 天</option>
                <option value="30d">30 天</option>
                <option value="90d">90 天</option>
              </select>
              <button id="btn-token" class="btn">查询</button>
            </div>
          </div>
          <div class="kpi-row" id="token-kpis"></div>
          <div class="charts">
            <div class="chart-box"><h3>按日 · 模型</h3><div id="bar-chart" class="chart"></div></div>
            <div class="chart-box"><h3>模型占比</h3><div id="pie-chart" class="chart"></div><div id="pie-legend" class="legend"></div></div>
          </div>
        </div>
      </section>

      <section id="page-about" class="page">
        <div class="panel">
          <div class="panel-head"><h2>关于</h2></div>
          <p>WorkBuddy Tools 桌面版 — 本地管理账号、迁移与用量。</p>
          <ul class="muted" style="margin:0.5rem 0 0;padding-left:1.1rem;line-height:1.7">
            <li>数据仅在本机处理</li>
            <li>迁移前请退出 WorkBuddy / WorkBuddyAI</li>
            <li>迁移会自动备份</li>
          </ul>
        </div>
      </section>
    </main>
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
  if (page === "migrate") void fillMigrateSelects();
}

function fillEditionSelects(): void {
  const opts = state.editions
    .filter((e) => e.exists)
    .map((e) => `<option value="${e.key}">${escapeHtml(e.label)}</option>`)
    .join("");
  ["#edition-select", "#mig-from", "#mig-to"].forEach((sel) => {
    const el = $(sel) as HTMLSelectElement;
    const prev = el.value;
    el.innerHTML = opts || `<option value="">未检测到</option>`;
    if (prev && [...el.options].some((o) => o.value === prev)) el.value = prev;
    else if (state.edition) el.value = state.edition;
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
    const keys = [...new Set([...(plan.items || []).map((i) => i.key), ...Object.keys(MIGRATE_LABELS)])];
    $("#mig-items").innerHTML = keys
      .map((k) => {
        const item = plan.items?.find((i) => i.key === k);
        const checked = state.selectedItems[k] !== false;
        return `
        <label class="check-item">
          <input type="checkbox" data-item="${k}" ${checked ? "checked" : ""} />
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
    if (plan.client_running) {
      warn.textContent = "目标客户端可能正在运行，请先完全退出再执行迁移。";
      warn.classList.remove("hidden");
    } else warn.classList.add("hidden");
    ($("#btn-run") as HTMLButtonElement).disabled = false;
    $("#mig-hint").textContent = `${plan.source_uid.slice(0, 8)}… → ${plan.target_uid.slice(0, 8)}…`;
    $("#step2").classList.add("on");
    toast("已生成预览");
  } catch (e) {
    toast((e as Error).message);
  }
}

async function runMigrate(): Promise<void> {
  if (!state.migratePlan) return;
  if (!confirm("确认执行迁移？将自动备份。")) return;
  ($("#btn-run") as HTMLButtonElement).disabled = true;
  try {
    const r = await api.migrateRun({
      from_edition: state.migratePlan.from_edition,
      to_edition: state.migratePlan.to_edition,
      source_uid: state.migratePlan.source_uid,
      target_uid: state.migratePlan.target_uid,
      items: state.selectedItems,
    });
    $("#mig-result-panel").classList.remove("hidden");
    const warns = (r.warnings || []).map((w) => `<div class="banner warn">${escapeHtml(w)}</div>`).join("");
    const rows = (r.results || [])
      .map(
        (x) =>
          `<div class="list-item"><div><strong>${MIGRATE_LABELS[x.key] || x.key}</strong><div class="muted small">${escapeHtml(x.detail)}</div></div><span class="badge ${x.ok ? "ok" : ""}">${x.count}</span></div>`,
      )
      .join("");
    $("#mig-result").innerHTML =
      warns + rows + `<div class="muted small" style="margin-top:.5rem">${r.need_restart ? "请重启客户端后查看。" : "完成"}</div>`;
    $("#step3").classList.add("on");
    toast("迁移完成");
    await loadAccounts();
  } catch (e) {
    toast((e as Error).message);
  } finally {
    ($("#btn-run") as HTMLButtonElement).disabled = false;
  }
}

function renderKpis(data: TokenSummary): void {
  const t = data.totals;
  const items: Array<[string, string]> = [
    ["总 Token", fmtNum(t.total)],
    ["输入", fmtNum(t.input)],
    ["输出", fmtNum(t.output)],
    ["缓存读取", fmtNum(t.cache_read)],
    ["缓存命中率", ((t.cache_hit_rate || 0) * 100).toFixed(1) + "%"],
    ["事件", fmtNum(t.events)],
  ];
  $("#token-kpis").innerHTML = items
    .map(([l, v]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`)
    .join("");
}

function renderBar(data: TokenSummary): void {
  const days = data.by_day || [];
  if (!days.length) {
    $("#bar-chart").innerHTML = `<div class="muted" style="padding:2rem">区间内无数据</div>`;
    return;
  }
  const W = 720,
    H = 300,
    padL = 48,
    padB = 36,
    padT = 16,
    padR = 12;
  const max = Math.max(1, ...days.map((d) => d.total || 0));
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const groupW = innerW / days.length;
  const barW = Math.max(4, Math.min(16, (groupW * 0.7) / 6));
  let bars = "";
  days.forEach((d, di) => {
    let x0 = padL + di * groupW + groupW * 0.15;
    (d.by_model || []).forEach((m) => {
      const h = ((m.total || 0) / max) * innerH;
      const y = padT + innerH - h;
      bars += `<rect x="${x0}" y="${y}" width="${barW}" height="${Math.max(h, 1)}" rx="3" fill="${m.color}"><title>${d.date} ${m.model} ${fmtNum(m.total)}</title></rect>`;
      x0 += barW + 2;
    });
  });
  const labels = days
    .map((d, i) => {
      if (days.length > 10 && i % Math.ceil(days.length / 8) !== 0) return "";
      const x = padL + i * groupW + groupW / 2;
      return `<text x="${x}" y="${H - 10}" text-anchor="middle" font-size="10" fill="#64748b">${d.date.slice(5)}</text>`;
    })
    .join("");
  const yTicks = [0, 0.5, 1]
    .map((p) => {
      const y = padT + innerH - p * innerH;
      return `<line x1="${padL}" x2="${W - padR}" y1="${y}" y2="${y}" stroke="#e6eaf2"/><text x="${padL - 8}" y="${y + 3}" text-anchor="end" font-size="10" fill="#64748b">${fmtNum(max * p)}</text>`;
    })
    .join("");
  $("#bar-chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="260">${yTicks}${bars}${labels}</svg>`;
}

function renderPie(data: TokenSummary): void {
  const models = data.by_model || [];
  const total = models.reduce((s, m) => s + (m.total || 0), 0);
  if (!total) {
    $("#pie-chart").innerHTML = `<div class="muted" style="padding:2rem">区间内无数据</div>`;
    $("#pie-legend").innerHTML = "";
    return;
  }
  const cx = 120,
    cy = 120,
    r = 90;
  let angle = -Math.PI / 2;
  let paths = "";
  models.forEach((m) => {
    const frac = (m.total || 0) / total;
    const sweep = frac * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + sweep);
    const y2 = cy + r * Math.sin(angle + sweep);
    const large = sweep > Math.PI ? 1 : 0;
    if (frac > 0.999) paths += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${m.color}"/>`;
    else
      paths += `<path d="M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z" fill="${m.color}"><title>${m.model}</title></path>`;
    angle += sweep;
  });
  paths += `<circle cx="${cx}" cy="${cy}" r="48" fill="#fff"/>`;
  paths += `<text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="11" fill="#64748b">总 Token</text>`;
  paths += `<text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="13" font-weight="700" fill="#0f172a">${fmtNum(total)}</text>`;
  $("#pie-chart").innerHTML = `<svg viewBox="0 0 240 240" width="100%" height="230">${paths}</svg>`;
  $("#pie-legend").innerHTML = models
    .slice(0, 12)
    .map(
      (m) =>
        `<div class="legend-item"><span class="swatch" style="background:${m.color}"></span>${escapeHtml(m.model)} · ${fmtNum(m.total)}</div>`,
    )
    .join("");
}

async function loadTokens(): Promise<void> {
  const range = ($("#token-range") as HTMLSelectElement).value;
  try {
    const data = await api.tokens(state.edition, range);
    state.tokenData = data;
    renderKpis(data);
    renderBar(data);
    renderPie(data);
  } catch (e) {
    toast((e as Error).message);
  }
}

function bind(): void {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => setPage((btn as HTMLElement).dataset.page!));
  });
  $("#btn-refresh").addEventListener("click", async () => {
    try {
      await loadEditions();
      await loadAccounts();
    } catch (e) {
      toast((e as Error).message);
    }
  });
  ($("#edition-select") as HTMLSelectElement).addEventListener("change", async (e) => {
    state.edition = (e.target as HTMLSelectElement).value;
    renderPill();
    await loadAccounts();
  });
  ($("#mig-from") as HTMLSelectElement).addEventListener("change", () => void fillMigrateSelects());
  ($("#mig-to") as HTMLSelectElement).addEventListener("change", () => void fillMigrateSelects());
  $("#btn-plan").addEventListener("click", () => void loadPlan());
  $("#btn-run").addEventListener("click", () => void runMigrate());
  $("#btn-token").addEventListener("click", () => void loadTokens());
  ($("#token-range") as HTMLSelectElement).addEventListener("change", () => void loadTokens());
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
      await loadAccounts();
    } catch (e) {
      toast((e as Error).message);
    }
  });
  $("#btn-open").addEventListener("click", async () => {
    try {
      const r = await api.openClient(state.edition);
      toast("已启动客户端");
      void r;
    } catch (e) {
      toast((e as Error).message);
    }
  });
}

async function init(): Promise<void> {
  renderShell();
  bind();
  try {
    await loadEditions();
    await loadAccounts();
  } catch (e) {
    toast("无法连接本地服务：" + (e as Error).message);
  }
}

void init();
