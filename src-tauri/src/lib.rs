use serde::{Deserialize, Serialize};
use tauri::Manager;
use tauri_plugin_shell::ShellExt;

fn api_healthy() -> bool {
    std::net::TcpStream::connect(("127.0.0.1", 18765)).is_ok()
}

fn wait_api() {
    for _ in 0..80 {
        if api_healthy() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

fn portable_sidecar_path() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let name = if cfg!(windows) {
        "sidecar-x86_64-pc-windows-msvc.exe"
    } else {
        "sidecar-x86_64-unknown-linux-gnu"
    };
    let p = dir.join(name);
    if p.is_file() {
        return Some(p);
    }
    // also try simple name
    let simple = if cfg!(windows) {
        dir.join("sidecar.exe")
    } else {
        dir.join("sidecar")
    };
    if simple.is_file() {
        return Some(simple);
    }
    None
}

fn spawn_portable_sidecar() -> bool {
    let Some(path) = portable_sidecar_path() else {
        return false;
    };
    eprintln!("[sidecar] portable spawn {}", path.display());
    match std::process::Command::new(&path)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(_child) => {
            wait_api();
            api_healthy()
        }
        Err(e) => {
            eprintln!("[sidecar] portable spawn failed: {e}");
            false
        }
    }
}

fn spawn_bundled_sidecar(app: &tauri::AppHandle) -> bool {
    let sidecar = app.shell().sidecar("sidecar");
    match sidecar {
        Ok(cmd) => match cmd.spawn() {
            Ok((mut rx, _child)) => {
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        if let tauri_plugin_shell::process::CommandEvent::Stderr(line) = event {
                            eprintln!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                    }
                });
                wait_api();
                api_healthy()
            }
            Err(e) => {
                eprintln!("[sidecar] spawn bundled failed: {e}");
                false
            }
        },
        Err(e) => {
            eprintln!("[sidecar] resolve bundled failed: {e}");
            false
        }
    }
}

fn start_sidecar(app: &tauri::AppHandle) {
    if api_healthy() {
        eprintln!("[sidecar] API already listening");
        return;
    }
    // 1) 便携版：与主 exe 同目录
    if spawn_portable_sidecar() {
        eprintln!("[sidecar] portable API ready");
        return;
    }
    // 2) 安装版：Tauri externalBin
    if spawn_bundled_sidecar(app) {
        eprintln!("[sidecar] bundled API ready");
        return;
    }
    eprintln!("[sidecar] all spawn strategies failed");
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ApiRequest {
    pub path: String,
    #[serde(default)]
    pub method: Option<String>,
    #[serde(default)]
    pub body: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ApiResponse {
    pub status: u16,
    pub body: String,
}

#[tauri::command]
fn api_proxy(req: ApiRequest) -> Result<ApiResponse, String> {
    let method = req.method.unwrap_or_else(|| "GET".into()).to_uppercase();
    let path = if req.path.starts_with('/') {
        req.path.clone()
    } else {
        format!("/{}", req.path)
    };

    use std::io::{Read, Write};
    let mut stream =
        std::net::TcpStream::connect(("127.0.0.1", 18765)).map_err(|e| format!("connect: {e}"))?;
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(30)))
        .ok();
    let body = req.body.unwrap_or_default();
    let mut head = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:18765\r\nConnection: close\r\n"
    );
    if !body.is_empty() {
        head.push_str("Content-Type: application/json\r\n");
        head.push_str(&format!("Content-Length: {}\r\n", body.len()));
    }
    head.push_str("\r\n");
    stream
        .write_all(head.as_bytes())
        .map_err(|e| format!("write: {e}"))?;
    if !body.is_empty() {
        stream
            .write_all(body.as_bytes())
            .map_err(|e| format!("write body: {e}"))?;
    }
    let mut buf = Vec::new();
    stream
        .read_to_end(&mut buf)
        .map_err(|e| format!("read: {e}"))?;
    let raw = String::from_utf8_lossy(&buf).into_owned();
    let split = raw
        .find("\r\n\r\n")
        .ok_or_else(|| "bad http response".to_string())?;
    let header = &raw[..split];
    let mut resp_body = raw[split + 4..].to_string();
    if header.to_ascii_lowercase().contains("transfer-encoding: chunked") {
        resp_body = dechunk(&resp_body);
    }
    let status = header
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u16>().ok())
        .unwrap_or(500);
    Ok(ApiResponse {
        status,
        body: resp_body,
    })
}

fn dechunk(input: &str) -> String {
    let mut out = String::new();
    let mut rest = input;
    while let Some(nl) = rest.find("\r\n") {
        let size_str = rest[..nl].trim();
        let Ok(size) = usize::from_str_radix(size_str, 16) else {
            break;
        };
        if size == 0 {
            break;
        }
        let start = nl + 2;
        let end = start + size;
        if end > rest.len() {
            break;
        }
        out.push_str(&rest[start..end]);
        rest = &rest[end.min(rest.len())..];
        rest = rest.strip_prefix("\r\n").unwrap_or(rest);
    }
    if out.is_empty() {
        input.to_string()
    } else {
        out
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![api_proxy])
        .setup(|app| {
            let handle = app.handle().clone();
            start_sidecar(&handle);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("WorkBuddy Tools");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
