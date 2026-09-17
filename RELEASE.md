# WorkBuddy Tools 发布说明

- 当前版本：**v0.1.3**
- 运行平台：Windows 10 / 11 (x86_64)
- 软件形态：绿色免安装便携版（开箱即用，内置 Python 运行时）
- 完整更新日志：详见 [CHANGELOG.md](CHANGELOG.md)

---

## 快速构建指南

```powershell
# 1. 编译前端
npm run ui:build && node scripts/copy-ui-dist.mjs

# 2. 编译 Python Sidecar 二进制
powershell -ExecutionPolicy Bypass -File scripts/build_sidecar.ps1

# 3. 生成便携版发布包
powershell -ExecutionPolicy Bypass -File scripts/build_portable.ps1
```

---

## v0.1.3 发行校验清单

| 文件名 | 文件大小 | SHA256 校验码 |
| :--- | :--- | :--- |
| `workbuddy-tools.exe` | 19.45 MB | `fed647e71897f218b34d4483511024561be3b0b054995ac52bfbd53e8da8e63a` |
| `WorkBuddyTools-portable-win64.zip` | 17.51 MB | `3cccc22418e407f877a78ab8f2189af258aec493dd376fc14881dc6a11a381fb` |
| `WorkBuddyTools-portable-win64-v0.1.3.zip` | 17.51 MB | `3cccc22418e407f877a78ab8f2189af258aec493dd376fc14881dc6a11a381fb` |
