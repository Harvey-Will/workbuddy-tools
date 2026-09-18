# WorkBuddy Tools 发布说明

- 当前版本：**v0.1.4**
- 运行平台：Windows 10 / 11 (x86_64)
- 软件形态：单文件绿色免安装便携版（开箱即用，内置完整独立运行时）
- 完整更新日志与多版本演进历程：详见 [CHANGELOG.md](CHANGELOG.md)

> [!IMPORTANT]
> **GitHub Releases 命名强制准则**：Release Title 必须且仅包含版本号（如 `v0.1.4`），杜绝追加任何中文描述或标语，确保 GitHub 左侧「Release list」目录树整洁纯净，不被折叠或截断。详细说明一律写入 Release 说明正文。

---

## 快速构建指南

```powershell
# 1. 编译前端
npm run ui:build && node scripts/copy-ui-dist.mjs

# 2. 编译 Python Sidecar 二进制
powershell -ExecutionPolicy Bypass -File scripts/build_sidecar.ps1

# 3. 构建单文件便携版发布包
powershell -ExecutionPolicy Bypass -File scripts/build_portable.ps1
```

---

## v0.1.4 发行校验清单

| 文件名 | 文件大小 | SHA256 校验码 |
| :--- | :--- | :--- |
| `workbuddy-tools.exe` | 19.46 MB | `379a69b71ded6029d3c73edc1bc98be6eb2ebafc0fe25d71ed74a64d595276e1` |
| `WorkBuddyTools-portable-win64.zip` | 17.51 MB | `a012690c73f03ca32a7c06127a7040db18839729bb6d57b46623afeb7378a950` |
| `WorkBuddyTools-portable-win64-v0.1.4.zip` | 17.51 MB | `a012690c73f03ca32a7c06127a7040db18839729bb6d57b46623afeb7378a950` |
