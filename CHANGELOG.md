# WorkBuddy Tools 更新日志 (Changelog)

本文档记录 WorkBuddy Tools 的所有版本迭代与更新说明。所有版本均遵循 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/) 语义化版本规范。

---

## 📋 更新说明格式与编写细则 (WBT-RNS)

为保障多版本迭代记录的严谨性、专业性与一致性，本项目制定以下更新说明格式细则：

1. **版本标头**：统一采用 `## [vX.Y.Z] - YYYY-MM-DD` 格式，附带该版本的核心主题定位标签。
2. **分类模块**：
   - 🚀 **新增功能 (Features)**：全新引入的用户可见功能或核心架构支撑。
   - ⚡ **体验与交互优化 (UX & Visual Polish)**：界面排版、动画、响应性能或交互细节提升。
   - 🛠️ **问题修复与算法校准 (Bug Fixes & Corrections)**：缺陷修复、计算逻辑修正、异常兼容处理。
   - 🛡️ **安全与可靠性 (Security & Reliability)**：数据隔离防护、进程生命周期绑定、防重入互斥等。
   - 📦 **发行文件与校验清单 (Artifacts & Checksums)**：正式发行产物的文件名、体积、SHA256 校验和。
3. **条目细则**：
   - 统一使用 `[模块前缀]` 标明改动范围：`[Core]`、`[Backend]`、`[UI]`、`[Desktop]`、`[CI]`。
   - 算法与计算逻辑改动须明确给出修复前后的公式比对与实际数据验证指标。
   - 涉及安全策略的改动须注明防护机制（如 Fail-Closed、进程级互斥）。

---

## [v0.1.3] - 2026-09-17

> **版本主题：长任务迁移体验 (Migration UX Flow)、现代化 Token 统计大盘与系统级更新体系**

### 🚀 新增功能 (Features)
- **[UI/Backend] 多阶段长任务异步迁移引擎**：
  - 前端无缝集成 `/api/migrate/jobs` 异步轮询模型（600ms 平滑轮询），长任务执行期间界面不阻塞、不断流；
  - 提供 10 个阶段（Preflight 预检、Backup 备份、Sessions 会话、Session Content 内容、User Memory 记忆、MCP Connectors 连接器、Tasks 任务、Skills 技能、Shared Plugins 共享插件、Session Usage 用量）的实时流水线追踪器；
  - 支持多状态指示（未开始、运行中、已完成、已跳过）、进度百分比平滑动画与实时耗时计时器；
  - 引入 `sessionStorage` 状态保持与 `visibilitychange`/`focus` 监听，页面刷新或后台切回后可自动重连轮询。
- **[UI/Core] 快照备份管理与一键安全还原**：
  - 新增即时快照创建入口（`POST /api/backups/create`），支持自定义标签或自动分配 UID 标识；
  - 备份管理面板全面升级，支持快照列表展示、创建时间格式化、包含文件总数与物理体积汇总；
  - 引入快照一键还原体系与二级防误触确认弹窗，必须勾选「我已了解覆盖风险」后方可执行还原；
  - 还原完成后自动触发双端账号状态重载与即时反馈。
- **[Core/Backend/UI] 系统级检查更新与开源生态关联**：
  - 新建 `core/update.py` 模块，支持 GitHub Latest Release API 与 Raw 仓库版本清单双重降级探测，解决 API 请求频次受限或网络受限问题；
  - 支持 SemVer 规范对比与正式版升级感知；
  - 新增「每次打开自动检查更新」打勾可选项，偏好设置双向持久化至 `localStorage`；
  - 新增 GitHub 开源项目图形按钮与 Releases/Issues 直达链接，后端 `/api/system/open-url` 强制仅允许 `http(s)://` 协议安全唤起系统默认浏览器。
- **[Core/UI] 深度重构现代化 Token 统计大盘**：
  - **多时间尺度缩放**：支持 5 档时间尺度快捷切换（`每日`、`24H`、`7天`、`30天`、`90天`），并支持 URL 参数联动；
  - **双视图自由切换**：支持「📊 按模型汇总」与「📅 按日期每日明细」双视图，清晰呈现每日总用量与各模型消耗占比；
  - **各模型份额环形图 (Donut Chart)**：基于 SVG 动态绘制环形占比图与彩色色阶标签，消耗份额一目了然；
  - **自适应每日用量堆叠柱状图**：按模型分段堆叠绘制，在大时间尺度（30D/90D）下动态调整柱宽与间距，杜绝元素碰撞。

### 🛠️ 问题修复与算法校准 (Bug Fixes & Corrections)
- **[Core/UI] 彻底修复 Prompt 缓存命中率计算严重偏低的问题**：
  - **根因修复**：深入分析真实 WorkBuddy 日志发现，标准日志中 `input_tokens`（Prompt Tokens）本身已包含 `cache_read_input_tokens`；旧算法由于将分母设为 `input + cache_read`，导致缓存读在分母中被重复计算，原本高达 ~97.6% 的命中率被误算为 ~48.9%；
  - **新计算公式**：
    $$\text{prompt} = \begin{cases} \text{inp}, & \text{if } \text{inp} \ge \text{cache} \\ \text{inp} + \text{cache}, & \text{if } \text{inp} < \text{cache} \end{cases}$$
    $$\text{Cache Hit Rate} = \min\left(1.0, \frac{\text{cache}}{\text{prompt}}\right)$$
    自适应兼容所有供应商日志，实现 $\text{Input} + \text{Output} = \text{Total}$ 且 $\text{Cache Hit Rate}$ 精准还原；
  - **测试验证**：针对用户真实 7 天 3.66 亿 Token 数据实测验证，缓存命中率精准修正为 **97.62%**。
- **[UI] 严格校准效率评级标准为 ≥ 90%**：
  - 重新调整综合缓存命中率效率评级阈值：仅当命中率 **≥ 90.0%** 时，才授予 `⚡ 高效命中` / `极佳 ⚡`（绿色高亮徽章）；
  - 梯队梯度：`≥ 90%`（高效/极佳）、`70% ~ 90%`（良好）、`> 0% ~ 70%`（偏低）、`0%`（常规/无缓存）；
  - KPI 卡片辅助说明更新为：`缓存读取 / 总输入 · ≥90% 为高效`。

### ⚡ 交互与体验优化 (UX & Visual Polish)
- **[UI] KPI 指标卡规范排版**：固定为 2 行 × 3 列标准网格（`repeat(3, 1fr)`），消灭单卡突兀或不对齐问题。
- **[UI] 消除柱状图悬停抖动**：将图表头部右侧摘要标签设为固定高度、固定最小宽度并设置 `white-space: nowrap`，彻底根除鼠标晃过柱条时文本过长换行导致的卡片抖动。
- **[UI] 界面纯净度升级**：
  - 去除除关于页面以外的所有版本号标签，侧边栏与顶栏回归纯净简约；
  - 移除关于界面重复的多余引导卡片；
  - 正式发布版本完全禁用演示模式与假数据切换功能，确保生产环境 100% 反映真实数据。

### 🛡️ 安全与可靠性 (Security & Reliability)
- **[Backend/Core] 全局写操作非阻塞并发互斥**：
  - 对账号切换（`/api/accounts/switch`）、任务创建（`/api/migrate/jobs`）、快照生成（`/api/backups/create`）、快照还原（`/api/backups/restore`）全部施加 `_migrate_lock` 非阻塞互斥锁，冲突时统一规范响应 HTTP 409 `busy`，彻底消除并发重入与 SQLite 写冲突隐患；
  - 全局迁移横幅（Banner）实时向各页面广播当前长任务状态，任务执行中联动禁用冲突按钮。
- **[Core] 路径穿越与合法性防御加固**：
  - 快照标签增加 `validate_path_component` 校验，路径创建增加 `ensure_within` 防越界断言。

### 📦 发行文件与校验清单 (Artifacts & Checksums)
- **运行平台**：Windows 10 / 11 (x86_64)
- **发布架构**：单文件便携绿色版（内嵌 Python Sidecar，临时自解压，零外部依赖）

| 文件名 | 文件大小 | SHA256 校验码 |
| :--- | :--- | :--- |
| `workbuddy-tools.exe` | 19.45 MB | `fed647e71897f218b34d4483511024561be3b0b054995ac52bfbd53e8da8e63a` |
| `WorkBuddyTools-portable-win64.zip` | 17.51 MB | `3cccc22418e407f877a78ab8f2189af258aec493dd376fc14881dc6a11a381fb` |
| `WorkBuddyTools-portable-win64-v0.1.3.zip` | 17.51 MB | `3cccc22418e407f877a78ab8f2189af258aec493dd376fc14881dc6a11a381fb` |

---

## [v0.1.2] - 2026-09-17

> **版本主题：运行时安全生命周期 (Runtime Safety & Lifecycle) 与事务级热备份**

### 🚀 新增功能 (Features)
- **[Core] SQLite 事务级物理热备份**：
  - 采用 SQLite 官方 `sqlite3.Connection.backup()` 物理流式备份机制，替代脆弱的文件级冷拷贝；
  - 自动生成完备的 `manifest.json` 清单，记录每个备份文件的相对路径、物理体积、SHA256 校验码及创建时间戳；
  - 增加可验证的 `restore_backup()` 还原引擎，还原时自动完成全量 SHA256 一致性校验与回滚防护。
- **[Core] 引用可达性 Blob 智能迁移**：
  - 解析会话与插件实际引用的媒体和资源哈希，仅复制真实可达的活跃 Blob，避免搬迁历史无用孤儿垃圾文件；
  - 对共享插件应用保守安全默认策略，自动排除无用缓存与瞬态持久化文件。
- **[Backend] 异步长任务迁移模型与进度汇报骨架**：
  - 建立后台长任务线程模型与阶段进度上报字典，为前端进度可视化铺平底座。

### 🛡️ 安全与可靠性 (Security & Reliability)
- **[Desktop] Windows Job Object 父子进程同生共死绑定**：
  - 使用 Windows 原生 Job Object API 并配置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 标志；
  - 保证主应用异常崩溃、任务管理器强制结束或正常退出时，底层 Python Sidecar 必定随之瞬间终止，彻底终结僵尸进程残留。
- **[Desktop/Backend] 动态环回端口与 CSPRNG 鉴权机制**：
  - 废弃静态固定端口，启动时由操作系统自动分配可用环回端口（`127.0.0.1:0`）；
  - 基于 Windows CNG 密码学随机数生成器生成高熵 CSPRNG Auth Token，通过命令行受控传递；
  - 后端中间件实施全量 `/api/` 请求 Bearer Token 强校验，有效阻断本机其他未授权进程的恶意越权调用。
- **[Desktop] Tauri 能力清单收缩**：
  - 严格收敛 `src-tauri/capabilities`，剥离宽泛的 shell 执行权限，仅保留必要的窗口与进程管控权限。

---

## [v0.1.1] - 2026-09-15

> **版本主题：数据热迁移第一阶段安全加固 (Migration Safety Hotfix)**

### 🛡️ 安全与可靠性 (Security & Reliability)
- **[Core/Backend] Fail-Closed 安全熔断机制**：
  - 引入完整的安全错误异常体系（`SafetyError`、`EditionError`、`ClientRunningError`、`SameEditionError`、`UIDError`、`PathTraversalError`、`WriteConflict`）；
  - 在执行任何写操作之前进行严格预检，任意条件不满足时立即中断并保持现场只读，绝不发生静默脏写入。
- **[Core] 运行状态互斥守护**：
  - 迁移与账号切换前强制检查客户端进程（`WorkBuddy.exe` / `WorkBuddyAI.exe`）是否运行；
  - 检测到运行中时立即阻断操作并明确提示退出客户端，防范 SQLite 数据库文件并发读写锁定损坏。
- **[Core] 严格的参数校验与防穿越边界**：
  - 严禁相同版本之间的会话级相互迁移，防范数据死循环覆盖；
  - 对用户 UID、文件路径、账号结构与 Session ID 进行严格正则校验与 `ensure_within` 路径防逃逸验证；
  - 读取损坏或非标准 JSON 文件时自动保留原始文件现场，严禁盲目覆盖损毁。

---

## [v0.1.0] - 2026-09-15

> **版本主题：WorkBuddy Tools 初始开源发布**

### 🚀 新增功能 (Features)
- **[Desktop] 双端版本自动识别**：
  - 自动检测并定位国内版（`WorkBuddy`）与国际版（`WorkBuddyAI`）安装与数据目录；
  - 支持快捷查看双端默认激活账号与状态。
- **[Core/UI] 多账号管理与一键切换**：
  - 自动识别多账号配置文件（`profiles`），提供本地双端账号卡片展示与一键无损热切换。
- **[Core/UI] 基础数据热迁移引擎**：
  - 支持在双端之间选择性复制会话历史、用户记忆（Memory）、MCP 插件配置与自定义技能（Skills）。
- **[UI] 基础 Token 统计展示**：
  - 初步支持解析本地日志并统计各模型消耗量。
