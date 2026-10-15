# WorkBuddy Tools 更新日志 (Changelog)

本文档记录 WorkBuddy Tools 各版本的核心演进历程与更新说明。

---

## [Unreleased] - macOS 支持

### 🍎 新增：原生 macOS 支持
- **构建产物升级为跨平台**：`bundle.targets` 增加 `app` / `dmg`，可直接产出 `WorkBuddy Tools.app` 与 DMG 安装包，最低支持 macOS 11.0。
- **新增 `scripts/build_sidecar.sh`**：macOS 版 Python sidecar 构建脚本（PyInstaller onefile + 对应 target triple 命名），与原有 PowerShell 脚本等价。
- **新增 `scripts/build_portable.sh` / `scripts/dev_desktop.sh`**：macOS 便携打包与本地开发脚本。
- **新增平台派发器**：`npm run build:sidecar` / `build:portable` / `dev:desktop` 现在会自动选择当前平台的实现，亦可显式使用 `:win` / `:mac` 后缀。
- **新增 `scripts/make_icns.py`**：从品牌图形生成 `icon.icns`（仓库原本只有最大 256px 的 PNG，不足 macOS iconset 的 1024px 需求）。

### 🔧 修复：macOS 下的客户端识别
- **`find_client_executables()` 支持 .app bundle**：macOS 客户端为 Electron 应用，真实可执行文件名为 `Electron`（位于 `WorkBuddy.app/Contents/MacOS/`）。此前非 Windows 分支只在 `/usr/bin` 等目录查找，必然落空；现在会扫描 `/Applications`、`~/Applications` 等常见位置。
- **`client_looks_running()` 按进程身份精确判定**：原先使用 `pgrep -f <名称>`，会匹配到任何命令行里"提到"该名称的进程，在 macOS 上导致**已退出客户端后仍提示"客户端正在运行，无法备份/迁移"**。具体误报来源有三类，现均被正确排除：
  - 本工具自身的窗口（`WorkBuddy Tools.app/...` 路径含 `WorkBuddy`）
  - Electron 的 helper 进程（GPU / Renderer / `chrome_crashpad_handler`）、sandbox 工作进程、daemon 子进程
  - 客户端退出后仍常驻的 CLI 预热进程（`codebuddy --prewarm`）
  
  现在只有「bundle 主可执行文件、且未附加任何子命令参数」的进程才算客户端在运行（例如 `/Applications/WorkBuddy.app/Contents/MacOS/Electron`），并改用 `pgrep -lf` 获取完整命令行以便判定。新增 `tests/test_client_detection.py` 固化这 6 组真实进程样本。
- **路径去重**：`/Applications` 与 `/System/Volumes/Data/Applications` 在 macOS 上指向同一位置，现在会去重避免重复展示。

### 🗄 修复：迁移/备份在 macOS 上静默失败（数据库打不开）
- **新增 `editions.connect_readonly()` 并统一所有只读用途**：原先代码用 `sqlite3.connect(路径)` 打开 WorkBuddy 数据库。该调用是惰性的，`connect()` 本身不报错，等第一次真正查询时 SQLite 需要创建 journal/WAL 文件；若数据目录不可写（macOS TCC 受保护的家目录、或客户端自持的目录），即以 `unable to open database file` 失败。

  更糟的是多处调用点用 `except sqlite3.Error: return []` 静默吞掉异常，于是表现为**「点击迁移无效」而没有任何错误提示**。实际影响：
  - 账号列表 sessions 统计为 0（真实为 421）
  - 迁移计划 sessions / session_content / tasks / session_usage 全部为 0
  - `validate_minimum_schema` 直接抛错中断迁移流程

  `connect_readonly()` 依次尝试 mode=ro → mode=ro&immutable=1 → 普通连接，并在函数内部立即执行一次真实读取，把失败点前移到连接阶段。已应用到 accounts.py / migrate.py / sessions.py 中全部只读场景（源库读取、schema 校验、会话与用量查询、SQLite 快照）。目标库（写入侧）仍保持普通连接。新增 `tests/test_readonly_db.py` 固化该契约。

### 🔐 修复：写入数据目录失败时报裸 500，用户看不到原因
- **新增 `DataDirNotWritable` 异常**：此前 `create_backup()` 里的 `mkdir()` 抛出 `PermissionError`，它既不是 `SafetyError` 子类、也没被 API 层捕获，最终以 `Internal Server Error` 呈现，UI 上只显示「迁移失败: Internal Server Error」，用户完全无法判断该做什么。
- **新增 `_write_hint()`**：在 macOS 上把 `PermissionError` 转成可执行的中文指引（提示前往「系统设置 → 隐私与安全性 → 完全磁盘访问权限」授权后重试），其他平台则提示检查目录权限。
- **API 映射为 403**：`_map_safety()` 为 `DataDirNotWritable` 增加 403 分支，错误码 `data_dir_not_writable` 会一路带到前端。
- **UI 三处错误处理补齐**：迁移启动、创建即时快照、按账号创建快照的 catch 分支都新增该错误码的专门提示，直接展示后端给出的完整指引。

> 说明：这是 macOS TCC 的预期行为——WorkBuddy 自身是沙盒应用（带 `com.apple.security.files.user-selected.read-write`），其数据目录会被标记为受保护位置，第三方工具需要用户手动授予「完全磁盘访问权限」才能写入。该权限只能由用户在系统设置中授予，工具无法代为获取。

### 🎨 修复：提示信息被弹窗遮挡
- **Toast 层级提升**：`.toast` 原本 `z-index: 50`，而 `.modal-backdrop` 为 `z-index: 100` 且带有 `backdrop-filter: blur(4px)` 与半透明深色背景。结果任何在弹窗打开时触发的提示（例如点击备份后提示"客户端正在运行"）都被压在遮罩下方，文字被模糊化后完全无法阅读。现将层级提升至 `z-index: 300`。
- **弹窗打开时 Toast 改到顶部居中**：原来固定在右下角，在弹窗覆盖屏幕时容易处于对话框后方被忽视。现在由 `toast()` 检测 `.modal-backdrop:not(.hidden)` 并切换 `toast--modal` 类，将提示移到顶部居中。使用 JS 判断而非 CSS `:has()` 选择器，以保证 macOS 11 上较旧的 WKWebView 行为一致。
- **显示时长自适应**：按消息长度在 2.8s～6s 之间调整，长文案（如完整的错误说明）不会一闪而过。
- **可读性细节**：补充 `line-height`、`word-break`，为 toast 加入淡入动画与 `aria-live="polite"` 无障碍标注。

### 🔧 修复：桌面外壳的跨平台化
- **内嵌 sidecar 按目标平台编译**：`include_bytes!` 原先仅针对 `x86_64-pc-windows-msvc`，现按 `target_os` + `target_arch` 分支覆盖 Windows / macOS / Linux 各目标三元组。
- **提取的 sidecar 自动补可执行权限**：非 Windows 平台提取后补 `0o755`，否则 `exec` 会以 `EACCES` 失败。
- **提取目录按用户隔离**：临时目录路径加入 `$USER`，避免多用户共用同一台机器时互相覆盖。
- **sidecar 查找目录扩展**：除可执行文件同级目录外，macOS 上还会查找 `Contents/`、`Contents/Resources`、`Contents/MacOS`。
- **`windows_subsystem` 属性限定到 Windows**：避免非 Windows 目标下的无谓属性。

### 🔒 安全
- **熵源升级**：非 Windows 平台的 token 生成改用 `/dev/urandom`（CSPRNG），原先使用时间戳派生的伪随机序列，仅作为最后的兜底保留。

### 🤖 CI
- **构建矩阵扩展**：Python 单测、前端构建、Rust cargo check 三项任务均在 `windows-latest` 与 `macos-latest` 上运行。
- **新增 macOS 打包任务**：产出 `.app` bundle 并上传为构建产物。

### 📝 说明
- Python 核心逻辑（账号扫描、会话解析、迁移、Token 统计、备份恢复）本身即为跨平台实现，本次未做改动；77 项单元测试在 macOS 上全部通过。

---

## [v0.1.5.1] - 2026-09-21

### 💡 核心更新与体验优化
- **迁移面板交互升级（预览按钮改为刷新）**：将原迁移配置左侧的「预览」按钮重构升级为「刷新」按钮，点击即时触发环境检测与配置更新。
- **账号与版本下拉联动即时自动刷新**：源版本、目标版本、源账号、目标账号任何一项变更时，系统自动联动刷新，无需繁琐重复点击。
- **客户端关闭状态智能感应与解锁**：刷新时实时重新探测 WorkBuddy / WorkBuddyAI 客户端运行状态；一旦检测到客户端退出关闭，系统自动消除运行中警告，解禁全部迁移复选项，激活「执行迁移」模式，进入就绪迁移复制状态。
- **窗口生命周期智能感知**：在用户关闭外部客户端并切换回 WorkBuddy Tools 窗口时（Window Focus / Visibility Change），自动静默触发最新状态探测与面板流转。

---

## [v0.1.5] - 2026-09-20

### 💡 核心更新与体验优化
- **全新「对话」管理标签页**：新增一级导航标签「对话」，实现双端（国内版 / 国际版）全部会话的集中统一看板与快捷管理。
- **分账号深度浏览与高效检索**：支持按版本与账号下拉筛选会话列表；支持标题、会话 ID、工作目录多字段即时关键字模糊搜索；支持按最后活跃时间、创建时间、Token 消耗量、Prompt 缓存命中率与对话轮数多维度排序。
- **会话级指标精准洞察**：直观展示单会话的总消耗 Token、输入 (Prompt)、缓存读取 (Cache Read)、输出 (Completion) 细分结构，精准统计对话轮数与消息总数；实时计算会话级 Prompt 缓存命中率并配备高效绿标与评级标识。
- **会话复制与备份（国服与国际服互通 + 本账号备份）**：
  - 支持将指定会话一键克隆为本账号备份副本（自动重映射全局唯一 UUID 并打上副本标识）。
  - 支持同版本跨账号复制，以及国内版 WorkBuddy 与国际版 WorkBuddyAI 双向跨端无损互通，深度重写 JSONL 历史消息、历史任务记录与 SQLite 用量记录，保障原会话数据 100% 完好。
  - 支持多会话批量快捷备份与跨账号迁移。
- **Markdown 格式专业导出（纯文本 / 带 Tool Call）**：
  - **纯文本输出 (Clean Text)**：提供极简清爽的纯净阅读体验，自动过滤底层系统指令与冗长工具调用入参，专注用户提问与助手核心回复。
  - **带 Tool Call 输出 (Full Technical)**：提供完整技术审计与复盘视图，包含模型深度思考过程 (Reasoning)、各步骤调用的工具名、格式化入参及实际执行返回结果。
  - 单个会话一键下载 `.md` 文件，多个会话一键自动打包导出为 `.zip` 压缩包。

### 📦 下载与使用
- **单文件免安装版**：直接下载 `workbuddy-tools.exe`，双击即可运行，无需配置 Python 等外部环境。
- **便携绿色压缩包**：下载 `WorkBuddyTools-portable-win64-v0.1.5.zip` 解压使用。
- **校验文件**：下载 `SHA256SUMS.txt` 对比文件完整性。

---

## [v0.1.4] - 2026-09-18

### 💡 核心更新与体验优化
- **同版本账号间全量数据互通**：彻底打破同版本（国内版 / 国际版）内不同账号之间的数据流转壁垒。引入会话 ID 独立重映射与正文深度同步机制，支持一键完整迁移聊天会话、正文附件、历史任务、用量记录与个性化配置，源账号数据 100% 保持完好，目标账号无缝接续。
- **账户卡片专属即时快照与一键还原**：在账号中心卡片操作栏全面开放「💾 备份」能力。支持为特定账号一键创建包含 SQLite 完整库、记忆文件与 MCP 配置的时间戳原子快照；支持按账号精准过滤历史快照并配备双重防误触安全还原，让每次数据调整都能进退自如。
- **账号中心与迁移联动体验升级**：同版本账号迁移预览全面放开会话类选项，解除原有置灰锁定，默认智能全选并提供专属安全保障提示。
- **全流程并发安全熔断与状态同步**：优化长任务执行期间的操作互斥保护，快照还原成功后自动同步刷新本地账号视图与快照时间轴。

### 📦 下载与使用
- **单文件免安装版**：直接下载 `workbuddy-tools.exe`，双击即可运行，无需配置 Python 等外部环境。
- **便携绿色压缩包**：下载 `WorkBuddyTools-portable-win64-v0.1.4.zip` 解压使用。
- **校验文件**：下载 `SHA256SUMS.txt` 对比文件完整性。

---

## [v0.1.3] - 2026-09-17

### 💡 核心更新与体验优化
- **长任务迁移可视化流水线**：接入后台异步长任务引擎，提供 10 阶段实时进度追踪与耗时计时，支持页面刷新或前后台切换后断点恢复，告别不确定的等待。
- **即时快照与一键安全还原**：新增手动创建即时快照功能，清晰呈现文件数量与物理占用体积；加入防误触确认弹窗与一键安全回滚，为工作资产筑牢防线。
- **全新重构 Token 智能分析大盘**：支持每日/24H/7天/30天/90天多尺度缩放，提供 6 大核心 KPI 卡片、模型占比环形图、交互式每日柱状图，以及按模型/日期的双明细视图。
- **校准 Prompt 缓存命中率算法**：修复分母重复加算问题，命中率与真实接口日志精准吻合；严格调整高效命中评级标准为 ≥90%，真实呈现省流提速价值。
- **系统级检查更新与开源生态**：关于页新增一键检查更新与「开机自动检测」打勾选项；新增图形化 GitHub 仓库直达入口，方便快速反馈交流。
- **交互防抖动打磨与并发保护**：固定图表头部布局彻底消除鼠标悬停抖动；规范指标卡为 2×3 网格；对所有写操作增加全局非阻塞防重入并发锁，全面下线假数据。

### 📦 下载与使用
- **单文件免安装版**：直接下载 `workbuddy-tools.exe`，双击即可运行，无需配置 Python 等外部环境。
- **便携绿色压缩包**：下载 `WorkBuddyTools-portable-win64-v0.1.3.zip` 解压使用。
- **校验文件**：下载 `SHA256SUMS.txt` 对比文件完整性。

---

## [v0.1.2] - 2026-09-17

### 💡 核心更新与体验优化
- **后台进程生命周期增强**：引入 Windows Job Object 进程绑定机制，主程序退出或突发关闭时后台服务同步彻底销毁，杜绝端口与僵尸进程残留。
- **本地通信加密鉴权加固**：启用操作系统动态分配的环回端口与高熵 CSPRNG Auth Token 强鉴权，有效防御本地其他未授权软件跨界调用。
- **数据迁移原子级安全热备份**：升级采用 SQLite 官方 `Connection.backup()` 物理流式备份与 manifest 完整性校验，若迁移中途遭遇异常可安全回滚，保障数据完整。
- **按需打包与传输加速**：深度解析会话与插件实际引用的媒体和附件，仅迁移真实可达的活跃资源，自动跳过冗余无用缓存，跨账号迁移速度更快、占用更小。
- **长任务后台流式反馈骨架**：针对大数据量迁移任务提供了平滑的阶段进度汇报基础，提升操作确定性与稳定性。

### 📦 下载与使用
- **单文件免安装版**：直接下载 `workbuddy-tools.exe`，双击即可运行。
- **便携绿色压缩包**：下载 `WorkBuddyTools-portable-win64-v0.1.2.zip` 解压使用。
- **校验文件**：下载 `SHA256SUMS.txt` 对比文件完整性。

---

## [v0.1.1] - 2026-09-15

### 💡 核心更新与体验优化
- **Fail-Closed 数据熔断保护**：引入全流程安全熔断校验体系，遇到版本缺失、权限不足或异常时立即保持只读并中止操作，绝不产生脏写入，保障原数据安全。
- **客户端运行状态互斥守护**：切换账号与数据迁移前强制检查 WorkBuddy / WorkBuddyAI 运行状态，提醒先退出客户端再执行写入，防止数据库并发读写造成损坏。
- **严格加固路径与边界安全防御**：严格禁止相同版本之间的会话级相互迁移，对 UID 与文件路径进行正则白名单校验与防路径穿越（ensure_within）隔离断言，避免意外数据覆盖。
- **数据迁移容错与异常提示**：优化 Memory、MCP、Skills 等跨版本搬迁体验，修复部分场景下任务与 Token 记录迁移问题，提供更清晰的执行结果与回滚指引。

### 📦 下载与使用
- **便携绿色压缩包**：下载 `WorkBuddyTools-portable-win64-v0.1.1.zip`，解压后运行 `workbuddy-tools.exe`。
- **校验文件**：下载 `SHA256SUMS.txt` 对比文件完整性。

---

## [v0.1.0] - 2026-09-15

### 💡 核心更新与体验优化
- **双端环境自动感知**：提供对国内版（WorkBuddy）与国际版（WorkBuddyAI）的自动识别与环境定位，快捷掌握双端当前激活的默认账号。
- **本地配置文件多账号管理**：自动解析本地账号配置卡片，免去手动修改文件的繁琐流程，实现多账号之间的一键平滑无损热切换。
- **跨端数据资产选择性热迁移**：支持在双端之间自由勾选会话历史、用户记忆（Memory）、MCP 插件配置与自定义技能（Skills），助力工作资产平滑流转。
- **基础 Token 统计看板**：初步支持解析本地交互日志，提供各模型用量分布的基础统计视图。

### 📦 下载与使用
- **便携绿色压缩包**：下载 `WorkBuddyTools-portable-win64.zip`，解压后运行 `workbuddy-tools.exe`。
