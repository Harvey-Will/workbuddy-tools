use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::Manager;

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

fn api_token() -> String {
    static TOKEN: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    TOKEN
        .get_or_init(|| {
            std::env::var("WBT_TOKEN").unwrap_or_else(|_| {
                let mut b = [0u8; 16];
                fill_entropy(&mut b);
                b.iter().map(|x| format!("{x:02x}")).collect::<String>()
            })
        })
        .clone()
}

fn fill_entropy(buf: &mut [u8]) {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0) as u64;
    let mut state = nanos ^ (std::process::id() as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
    for slot in buf.iter_mut() {
        state = state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        *slot = (state >> 33) as u8;
    }
}

fn sidecar_hash(bytes: &[u8]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    bytes.hash(&mut h);
    h.finish()
}

/// Embedded API sidecar (built by scripts/build_sidecar.ps1).
#[cfg(target_os = "windows")]
static SIDECAR_BYTES: &[u8] =
    include_bytes!("../binaries/sidecar-x86_64-pc-windows-msvc.exe");

fn hide_console(cmd: &mut std::process::Command) {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let _ = cmd;
}

fn extract_embedded_sidecar() -> Option<PathBuf> {
    #[cfg(not(target_os = "windows"))]
    {
        None
    }
    #[cfg(target_os = "windows")]
    {
        let dir = std::env::temp_dir().join("workbuddy-tools").join("0.1.0");
        std::fs::create_dir_all(&dir).ok()?;
        let path = dir.join("api-sidecar.exe");
        let want = format!("{:016x}", sidecar_hash(SIDECAR_BYTES));
        let stamp = dir.join("api-sidecar.hash");
        let ok = path.is_file()
            && std::fs::read_to_string(&stamp)
                .map(|s| s.trim() == want)
                .unwrap_or(false);
        if !ok {
            std::fs::write(&path, SIDECAR_BYTES).ok()?;
            let _ = std::fs::write(&stamp, &want);
        }
        Some(path)
    }
}

fn spawn_sidecar_exe(path: &std::path::Path) -> bool {
    let mut cmd = std::process::Command::new(path);
    cmd.stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    cmd.env("WBT_TOKEN", api_token());
    cmd.env("WBT_HOST", "127.0.0.1");
    hide_console(&mut cmd);
    match cmd.spawn() {
        Ok(_child) => {
            wait_api();
            api_healthy()
        }
        Err(e) => {
            eprintln!("[sidecar] spawn failed: {e}");
            false
        }
    }
}

fn start_sidecar() {
    if api_healthy() {
        eprintln!("[sidecar] already listening");
        return;
    }
    if let Some(path) = extract_embedded_sidecar() {
        if spawn_sidecar_exe(&path) {
            eprintln!("[sidecar] embedded API ready");
            return;
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in ["sidecar-x86_64-pc-windows-msvc.exe", "sidecar.exe"] {
                let p = dir.join(name);
                if p.is_file() && spawn_sidecar_exe(&p) {
                    eprintln!("[sidecar] sidecar file ready");
                    return;
                }
            }
        }
    }
    eprintln!("[sidecar] all strategies failed");
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
fn get_api_token() -> String {
    api_token()
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
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:18765\r\nConnection: close\r\nX-WBT-Token: {}\r\n",
        api_token()
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
        .invoke_handler(tauri::generate_handler![api_proxy, get_api_token])
        .setup(|app| {
            start_sidecar();
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("WorkBuddy Tools");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
