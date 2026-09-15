# WorkBuddy Tools

[English](README.en.md) · 简体中文

[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-blue?style=flat)](#安装指南)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green?style=flat)](https://www.python.org/)
[![Tauri](https://img.shields.io/badge/Tauri-2-24C8DB?style=flat)](https://tauri.app)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

一款 **WorkBuddy 本地账号与数据管理工具**：支持国内版 WorkBuddy 与国际版 WorkBuddyAI，提供账号查看与一键切换、选择性数据迁移、Token 用量可视化统计。

> 本工具在**本机**读取 WorkBuddy 数据目录，帮助你在多账号、双版本之间整理会话、记忆、技能与 MCP 配置，并看清各模型的 Token 消耗。**数据不上传云端。**

**功能**：账号总览 · 一键切号 · 选择性迁移 · 会话/记忆/技能/MCP · Token 统计 · 双版本支持 · 桌面端 / 命令行

**平台**：桌面端 Windows；CLI / Core 支持 Windows · Linux（macOS 路径已预留）

---

## 功能概览

### 1. 账号中心

- **双端识别**：自动发现国内版（`~/.workbuddy`）与国际版（`~/.workbuddy-ai`）
- **账号卡片**：显示名、Sessions / Memory / MCP、最近活跃时间
- **一键切换**：改写本机登录身份，重启客户端后生效
- **添加用户**：登记备注、打开客户端登录后刷新即可

### 2. 迁移 / 复制

支持**按需勾选**，copy 模式下目标已有内容会保留并合并。**仅执行显式勾选的项目**（fail-closed）。

| 项目 | 说明 |
| :--- | :--- |
| 聊天会话 | `sessions` 表；**仅跨版本**复制到目标库 |
| 会话内容 | `projects/**/*.jsonl` 正文、附件、blobs（仅跨版本） |
| 用户记忆 | Memory Profile 结构合并 |
| 历史任务 | `tasks/{session}` 目录（仅跨版本；无关联 session 时不迁） |
| 技能 Skills | 全局目录，只补缺失 |
| MCP 连接器 | `mcp.json` 深度合并 |
| 插件市场 | connectors-marketplace 等 |
| 用量记录 | `session_usage` 表（仅跨版本） |

**安全边界（v0.1.1）**：

- 同版本不同账号之间**暂不支持**会话相关数据迁移（需要 Session ID 重映射，当前版本拒绝执行以免修改源账号）
- 源/目标 WorkBuddy **任一在运行**时禁止迁移与切换账号
- 非法 UID / 路径穿越 / 账号不存在 / 数据库结构不兼容 → **第一次写盘前拒绝**
- 目标 JSON 损坏时不会被空对象覆盖
- **自动备份**：迁移前写入 `{数据目录}/.workbuddy-tools/backups/`

### 3. Token 用量统计

- **时间范围**：今天 / 24 小时 / 7 天 / 30 天 / 90 天 / 自定义
- **指标**：总 Token、输入、输出、缓存读取、**缓存命中率**
- **模型分色柱状图** + **占比环图**，同模型颜色一致
- 数据来源：本机会话转写中的用量字段，不请求第三方

### 4. 桌面应用

- **Tauri 2** 桌面壳 + 本地 API sidecar
- **便携版**：解压双击即可，无需安装 Python
- **安装包**：NSIS（Windows）

---

## 安全性与隐私（简明版）

- **纯本地工具**：不需要注册本工具账号，也没有项目自建云来存你的数据。
- **数据只在本机读写**：
  - `~/.workbuddy`：国内版 WorkBuddy
  - `~/.workbuddy-ai`：国际版 WorkBuddyAI
  - `{上述目录}/.workbuddy-tools/`：本工具的备份与本地备注
- **API 仅监听本机**：`127.0.0.1:18765`。桌面版会生成会话 Token，非本工具发起的调用会被拒绝。
- **什么时候不会联网**：账号扫描、本地迁移、Token 统计均不依赖外网。
- **备份**：迁移前写入 `{数据目录}/.workbuddy-tools/backups/`，可能包含完整数据库与记忆，请自行定期清理。
- **实用建议**：
  1. 迁移前**完全退出** WorkBuddy / WorkBuddyAI
  2. 不要打包分享整个用户目录或 backups
  3. 公共电脑用完后清理备份与本工具配置目录

---

## 安装指南

### 选项 A：便携版（推荐）

从 [Releases](../../releases) 下载 `WorkBuddyTools-portable-win64-v0.1.1.zip`（或对应版本）：

1. 解压到任意目录  
2. 双击 **单个** `workbuddy-tools.exe`  
3. 首次启动会在临时目录释放内置 API（无额外黑窗）  

**单文件分发，无需安装 Python / Node。**

### 选项 B：安装包

下载 `WorkBuddy Tools_*_x64-setup.exe`，按向导安装。

### 选项 C：仅命令行（开发者）

```bash
git clone <本仓库>
cd workbuddy-tools
python -m venv .venv

# Windows
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\dev.py

# Linux / macOS
source .venv/bin/activate
pip install -r requirements.txt
python scripts/dev.py
```

浏览器打开 `http://127.0.0.1:18765`。

---

## 快速上手

```text
1. 打开 WorkBuddy Tools
2. 顶部选择「国内版」或「国际版」
3. 账号中心查看账号 → 需要时「一键切换」
4. 迁移页：选源/目标 → 预览 → 勾选类别 → 执行
5. Token 统计页：切换时间范围查看模型用量
```

迁移前请**退出 WorkBuddy 客户端**，迁移完成后**重启客户端**。源端与目标端任一在运行时，本工具会拒绝迁移与切换。

---

## 版本说明

### v0.1.1 — Safety Hotfix

- 所有不安全迁移必须在**第一次磁盘写入之前**失败关闭（fail closed）
- 修复同版本库内会话“复制”实为改写归属的问题：同版本会话相关迁移直接拒绝
- 修复空 session 列表误迁全部 tasks 的问题
- UID / 路径穿越校验、真实账号存在性校验、客户端运行硬阻断
- 迁移只执行显式勾选项目；结果区分 success / skipped / failed

### ⚠️ v0.1.0 已知问题

请勿使用 v0.1.0 执行**同版本不同账号**之间的会话相关数据迁移。其实现可能修改源账号的会话归属，而非安全复制。请升级至 v0.1.1 后再使用迁移功能。

---

## 常见问题

**Q：切换账号后客户端里还是旧数据？**  
A：请完全退出 WorkBuddy（含托盘）再启动；客户端有内存缓存。

**Q：迁移后打开会话一直转圈？**  
A：需同时迁移「会话内容」（jsonl）。本工具默认勾选；若曾只迁表结构，请重新执行并勾选会话内容。

**Q：Token 统计数字从哪来？**  
A：本机 `projects/` 下会话转写中的 usage 字段，不是云端账单，可能与官方计费口径略有差异。

**Q：会不会把我的账号传到网上？**  
A：不会。扫描、迁移、统计均在本机完成。

---

## 开发与构建

### 前置要求

- Python 3.10+
- Node.js 18+
- Rust（仅打包 Tauri 桌面时需要）

### 桌面开发

```powershell
powershell -File scripts/setup_rust.ps1
npm install
cd ui; npm install; cd ..
npm run dev:desktop
```

### 打包

```powershell
# Python sidecar
powershell -File scripts/build_sidecar.ps1

# 便携版 zip
npm run build:portable

# 安装包（需先退出正在运行的应用）
npm run build:desktop:installer
```

### 测试

```bash
.venv/Scripts/python -m unittest discover -s tests
```

### 项目结构

```text
core/        领域逻辑（账号 / 迁移 / Token）
backend/     FastAPI
ui/          桌面前端（Vite + TS）
src-tauri/   Tauri 2 壳
scripts/     本地开发与打包脚本
docs/        规格与 Logo 等
```

---

## 致谢

- WorkBuddy 数据隔离与迁移方案参考社区讨论与本仓库早期 CLI 版本  
- 桌面技术栈：[Tauri](https://tauri.app) · [FastAPI](https://fastapi.tiangolo.com) · [Vite](https://vite.dev)

若本项目对你有帮助，欢迎点个 ⭐ Star。

---

## 许可证

[MIT](LICENSE)

---

## 免责声明

本工具仅在**用户本机**读取与修改 WorkBuddy 本地数据文件，请遵守 WorkBuddy / 腾讯相关服务条款。  
使用前请自行备份重要数据；作者不对数据丢失或账号异常承担责任。  
本项目与 WorkBuddy / 腾讯官方无隶属关系。
