use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::process::Child;
use std::sync::Mutex;
use tauri::Manager;

static SIDECAR_CHILD: Mutex<Option<Child>> = Mutex::new(None);

#[cfg(target_os = "windows")]
mod win_rng {
    #[link(name = "bcrypt")]
    extern "system" {
        fn BCryptGenRandom(
            h_algorithm: *mut std::ffi::c_void,
            pb_buffer: *mut u8,
            cb_buffer: u32,
            dw_flags: u32,
        ) -> i32;
    }

    pub fn get_random_bytes(buf: &mut [u8]) -> bool {
        const BCRYPT_USE_SYSTEM_PREFERRED_RNG: u32 = 0x00000002;
        unsafe {
            BCryptGenRandom(
                std::ptr::null_mut(),
                buf.as_mut_ptr(),
                buf.len() as u32,
                BCRYPT_USE_SYSTEM_PREFERRED_RNG,
            ) == 0
        }
    }
}

#[cfg(target_os = "windows")]
mod win_job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(
            lp_job_attributes: *mut std::ffi::c_void,
            lp_name: *const u16,
        ) -> *mut std::ffi::c_void;
        fn SetInformationJobObject(
            h_job: *mut std::ffi::c_void,
            job_object_info_class: i32,
            lp_job_object_info: *const std::ffi::c_void,
            cb_job_object_info_length: u32,
        ) -> i32;
        fn AssignProcessToJobObject(
            h_job: *mut std::ffi::c_void,
            h_process: *mut std::ffi::c_void,
        ) -> i32;
        fn CloseHandle(h_object: *mut std::ffi::c_void) -> i32;
    }

    #[repr(C)]
    struct IO_COUNTERS {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        basic_limit_information: JOBOBJECT_BASIC_LIMIT_INFORMATION,
        io_info: IO_COUNTERS,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_limit: usize,
        peak_job_memory_limit: usize,
    }

    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x00002000;
    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: i32 = 9;

    static JOB_HANDLE: std::sync::Mutex<Option<usize>> = std::sync::Mutex::new(None);

    pub fn assign_child_to_kill_on_close_job(child: &Child) {
        unsafe {
            let mut lock = JOB_HANDLE.lock().unwrap();
            let job = if let Some(h) = *lock {
                h as *mut std::ffi::c_void
            } else {
                let h = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
                if h.is_null() {
                    return;
                }
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let ok = SetInformationJobObject(
                    h,
                    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                    &info as *const _ as *const std::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if ok == 0 {
                    CloseHandle(h);
                    return;
                }
                *lock = Some(h as usize);
                h
            };

            let proc_handle = child.as_raw_handle() as *mut std::ffi::c_void;
            AssignProcessToJobObject(job, proc_handle);
        }
    }
}

fn pick_unused_port() -> u16 {
    if let Ok(listener) = std::net::TcpListener::bind("127.0.0.1:0") {
        if let Ok(addr) = listener.local_addr() {
            let port = addr.port();
            drop(listener);
            return port;
        }
    }
    18765
}

pub fn api_port() -> u16 {
    static PORT: std::sync::OnceLock<u16> = std::sync::OnceLock::new();
    *PORT.get_or_init(|| {
        if let Ok(p_str) = std::env::var("WBT_PORT") {
            if let Ok(p) = p_str.trim().parse::<u16>() {
                if p > 0 {
                    return p;
                }
            }
        }
        pick_unused_port()
    })
}

fn api_healthy() -> bool {
    let port = api_port();
    let token = api_token();
    use std::io::{Read, Write};
    let Ok(mut stream) = std::net::TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    stream
        .set_read_timeout(Some(std::time::Duration::from_millis(600)))
        .ok();
    stream
        .set_write_timeout(Some(std::time::Duration::from_millis(600)))
        .ok();
    let req = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nX-WBT-Token: {token}\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = Vec::new();
    if stream.read_to_end(&mut buf).is_err() {
        return false;
    }
    let s = String::from_utf8_lossy(&buf);
    s.contains("200 OK") && s.contains("\"ok\":true")
}

fn wait_api() {
    for _ in 0..100 {
        if api_healthy() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

pub fn kill_sidecar() {
    if let Ok(mut lock) = SIDECAR_CHILD.lock() {
        if let Some(mut child) = lock.take() {
            let pid = child.id();
            eprintln!("[sidecar] terminating sidecar process PID {pid}");
            let _ = child.kill();
            let _ = child.wait();
            eprintln!("[sidecar] sidecar process PID {pid} cleaned up");
        }
    }
}

fn api_token() -> String {
    static TOKEN: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    TOKEN
        .get_or_init(|| {
            std::env::var("WBT_TOKEN").unwrap_or_else(|_| {
                let mut b = [0u8; 32];
                fill_entropy(&mut b);
                b.iter().map(|x| format!("{x:02x}")).collect::<String>()
            })
        })
        .clone()
}

fn fill_entropy(buf: &mut [u8]) {
    #[cfg(target_os = "windows")]
    {
        if win_rng::get_random_bytes(buf) {
            return;
        }
    }
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
static SIDECAR_BYTES: &[u8] = include_bytes!("../binaries/sidecar-x86_64-pc-windows-msvc.exe");

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
        let version = env!("CARGO_PKG_VERSION");
        let dir = std::env::temp_dir().join("workbuddy-tools").join(version);
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
    let port = api_port();
    cmd.env("WBT_TOKEN", api_token());
    cmd.env("WBT_HOST", "127.0.0.1");
    cmd.env("WBT_PORT", port.to_string());
    hide_console(&mut cmd);
    match cmd.spawn() {
        Ok(child) => {
            #[cfg(target_os = "windows")]
            {
                win_job::assign_child_to_kill_on_close_job(&child);
            }
            if let Ok(mut lock) = SIDECAR_CHILD.lock() {
                *lock = Some(child);
            }
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
        eprintln!("[sidecar] already listening and authenticated");
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
fn get_api_port() -> u16 {
    api_port()
}

#[tauri::command]
fn api_proxy(req: ApiRequest) -> Result<ApiResponse, String> {
    let method = req.method.unwrap_or_else(|| "GET".into()).to_uppercase();
    let path = if req.path.starts_with('/') {
        req.path.clone()
    } else {
        format!("/{}", req.path)
    };

    let port = api_port();
    use std::io::{Read, Write};
    let mut stream =
        std::net::TcpStream::connect(("127.0.0.1", port)).map_err(|e| format!("connect: {e}"))?;
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(30)))
        .ok();
    let body = req.body.unwrap_or_default();
    let mut head = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nX-WBT-Token: {}\r\n",
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
    if header
        .to_ascii_lowercase()
        .contains("transfer-encoding: chunked")
    {
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
        .invoke_handler(tauri::generate_handler![api_proxy, get_api_token, get_api_port])
        .setup(|app| {
            start_sidecar();
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("WorkBuddy Tools");
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    kill_sidecar();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit = event {
                kill_sidecar();
            }
        });
}
