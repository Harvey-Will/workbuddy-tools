# WorkBuddy Tools 发布说明与指南

本仓库为开源桌面工具 **WorkBuddy Tools**。

- 当前版本：**v0.1.3**
- 开源许可：**MIT License**
- 完整更新日志与多版本演进说明请参阅：[CHANGELOG.md](CHANGELOG.md)

---

## 快速发布指南 (Release Workflow)

### 1. 本地打包构建
```powershell
# 1. 编译前端并拷贝 dist
npm run ui:build && node scripts/copy-ui-dist.mjs

# 2. 编译嵌入式 Python Sidecar 二进制
powershell -ExecutionPolicy Bypass -File scripts/build_sidecar.ps1

# 3. 构建单文件便携绿色版 (Portable Release)
powershell -ExecutionPolicy Bypass -File scripts/build_portable.ps1
```

构建完成后产物位于 `release/` 目录：
- `workbuddy-tools.exe`（单文件便携绿色可执行程序）
- `WorkBuddyTools-portable-win64.zip`（便携分发压缩包）
- `SHA256SUMS.txt`（SHA256 校验清单）

### 2. 自动化测试套件
在提交与发布前确保所有测试通过：
```powershell
python -m unittest discover -s tests
npm run build --prefix ui
cargo check --manifest-path src-tauri/Cargo.toml
```

---

## v0.1.3 发行校验清单

| 文件名 | 文件大小 | SHA256 校验和 |
| :--- | :--- | :--- |
| `workbuddy-tools.exe` | 19.45 MB | `fed647e71897f218b34d4483511024561be3b0b054995ac52bfbd53e8da8e63a` |
| `WorkBuddyTools-portable-win64.zip` | 17.51 MB | `3cccc22418e407f877a78ab8f2189af258aec493dd376fc14881dc6a11a381fb` |
| `WorkBuddyTools-portable-win64-v0.1.3.zip` | 17.51 MB | `3cccc22418e407f877a78ab8f2189af258aec493dd376fc14881dc6a11a381fb` |
