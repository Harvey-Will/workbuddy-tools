# Tauri 壳（预留）

v1 以本地 Web（FastAPI + frontend）交付。具备 Rust 后可将本目录补全为 Tauri 2 应用，把 `http://127.0.0.1:18765` 或打包后的静态资源嵌入窗口。

## 建议步骤

1. 安装 rustup、Node、`@tauri-apps/cli`
2. 在仓库根执行 `npm create tauri-app` 或手动添加 `src-tauri`
3. `tauri.conf.json` 将 devUrl 指向本地后端，或 build 时嵌入 `frontend/`
4. `tauri build` 产出 Windows `.msi/.exe` 与 Linux `.AppImage/.deb`

## 打包注意

- 后端 Python 可用 PyInstaller 打成 sidecar，由 Tauri `externalBin` 拉起
- 默认端口 `18765`，避免与常见服务冲突
- Linux 发行优先 AppImage（免 root）
