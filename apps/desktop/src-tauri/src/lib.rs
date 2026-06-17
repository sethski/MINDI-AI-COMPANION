use base64::Engine;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tauri::{
    AppHandle, Emitter, Listener, LogicalPosition, LogicalSize, Manager, PhysicalPosition, WebviewWindow,
};

const ORB_LABEL: &str = "orb";
const MAIN_LABEL: &str = "main";

#[derive(Serialize, Deserialize, Clone)]
struct MindiInputEvent {
    kind: String,
    text: String,
}

#[derive(Serialize, Deserialize, Default, Clone)]
struct OrbPosition {
    x: f64,
    y: f64,
}

fn emit_mindi_input(app: &AppHandle, kind: &str, text: String) {
    let payload = MindiInputEvent {
        kind: kind.to_string(),
        text,
    };
    let _ = app.emit("mindi-input", payload);
}

fn read_clipboard_text() -> Result<String, String> {
    let mut clipboard = arboard::Clipboard::new().map_err(|error| error.to_string())?;
    clipboard
        .get_text()
        .map_err(|error| error.to_string())
}

fn write_clipboard_text(text: &str) -> Result<(), String> {
    let mut clipboard = arboard::Clipboard::new().map_err(|error| error.to_string())?;
    clipboard
        .set_text(text)
        .map_err(|error| error.to_string())
}

#[cfg(windows)]
fn simulate_copy() -> Result<(), String> {
    use std::thread;
    use std::time::Duration;
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VIRTUAL_KEY,
        VK_CONTROL, VK_C,
    };

    fn key_input(vk: VIRTUAL_KEY, key_up: bool) -> INPUT {
        INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: vk,
                    wScan: 0,
                    dwFlags: if key_up { KEYEVENTF_KEYUP } else { Default::default() },
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        }
    }

    let inputs = [
        key_input(VK_CONTROL, false),
        key_input(VK_C, false),
        key_input(VK_C, true),
        key_input(VK_CONTROL, true),
    ];
    unsafe {
        let sent = SendInput(&inputs, std::mem::size_of::<INPUT>() as i32);
        if sent != inputs.len() as u32 {
            return Err("send_input_failed".to_string());
        }
    }
    thread::sleep(Duration::from_millis(140));
    Ok(())
}

#[cfg(not(windows))]
fn simulate_copy() -> Result<(), String> {
    Err("selection_copy_unsupported".to_string())
}

fn capture_selected_text() -> Result<String, String> {
    let saved = read_clipboard_text().unwrap_or_default();
    simulate_copy()?;
    let selected = read_clipboard_text().unwrap_or_default();
    if !saved.is_empty() {
        let _ = write_clipboard_text(&saved);
    }
    Ok(selected)
}

fn show_main_window_sync(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn handle_input_shortcut(app: &AppHandle, kind: &str, use_selection: bool) {
    let text = if use_selection {
        match capture_selected_text() {
            Ok(value) => value,
            Err(_) => return,
        }
    } else {
        match read_clipboard_text() {
            Ok(value) => value,
            Err(_) => return,
        }
    };
    if text.trim().is_empty() {
        return;
    }
    emit_mindi_input(app, kind, text);
    show_main_window_sync(app);
}

fn register_input_shortcuts(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

    let selection = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
    let summarize = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyU);
    let translate = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyT);
    let explain = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyE);
    let screen_help = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyS);

    app.global_shortcut().on_shortcut(selection, move |app, _shortcut, event| {
        if event.state != ShortcutState::Pressed {
            return;
        }
        handle_input_shortcut(app, "selection", true);
    })?;

    app.global_shortcut().on_shortcut(summarize, move |app, _shortcut, event| {
        if event.state != ShortcutState::Pressed {
            return;
        }
        handle_input_shortcut(app, "clipboard_summarize", false);
    })?;

    app.global_shortcut().on_shortcut(translate, move |app, _shortcut, event| {
        if event.state != ShortcutState::Pressed {
            return;
        }
        handle_input_shortcut(app, "clipboard_translate", false);
    })?;

    app.global_shortcut().on_shortcut(explain, move |app, _shortcut, event| {
        if event.state != ShortcutState::Pressed {
            return;
        }
        handle_input_shortcut(app, "clipboard_explain", false);
    })?;

    app.global_shortcut().on_shortcut(screen_help, move |app, _shortcut, event| {
        if event.state != ShortcutState::Pressed {
            return;
        }
        show_main_window_sync(app);
        let _ = app.emit("mindi-screen-help", ());
    })?;

    Ok(())
}

fn orb_window(app: &AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window(ORB_LABEL)
}

fn orb_position_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|path| path.join("orb-position.json"))
        .map_err(|error| error.to_string())
}

fn load_orb_position(app: &AppHandle) -> OrbPosition {
    let path = match orb_position_path(app) {
        Ok(path) => path,
        Err(_) => return OrbPosition::default(),
    };
    if !path.exists() {
        return OrbPosition::default();
    }
    fs::read_to_string(path)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

fn save_orb_position_file(app: &AppHandle, position: &OrbPosition) -> Result<(), String> {
    let path = orb_position_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(path, serde_json::to_string_pretty(position).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())
}

fn clamp_orb_to_monitor(window: &WebviewWindow) -> Result<(), String> {
    let position = window
        .outer_position()
        .map_err(|error| error.to_string())?;
    let size = window.outer_size().map_err(|error| error.to_string())?;
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "monitor_not_found".to_string())?;
    let mon_pos = monitor.position();
    let mon_size = monitor.size();
    let max_x = mon_pos.x + mon_size.width as i32 - size.width as i32;
    let max_y = mon_pos.y + mon_size.height as i32 - size.height as i32;
    let x = position.x.clamp(mon_pos.x, max_x.max(mon_pos.x));
    let y = position.y.clamp(mon_pos.y, max_y.max(mon_pos.y));
    if x != position.x || y != position.y {
        window
            .set_position(PhysicalPosition::new(x, y))
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn orb_save_position(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    save_orb_position_file(&app, &OrbPosition { x, y })
}

#[tauri::command]
async fn orb_set_size(app: AppHandle, width: f64, height: f64) -> Result<(), String> {
    let window = orb_window(&app).ok_or_else(|| "orb_window_not_found".to_string())?;
    window
        .set_size(LogicalSize::new(width, height))
        .map_err(|error| error.to_string())?;
    clamp_orb_to_monitor(&window)?;
    Ok(())
}

#[tauri::command]
async fn orb_start_drag(app: AppHandle) -> Result<(), String> {
    let window = orb_window(&app).ok_or_else(|| "orb_window_not_found".to_string())?;
    window
        .start_dragging()
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn orb_focus(app: AppHandle) -> Result<(), String> {
    let window = orb_window(&app).ok_or_else(|| "orb_window_not_found".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window
        .set_focus()
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn orb_clamp_position(app: AppHandle) -> Result<(), String> {
    let window = orb_window(&app).ok_or_else(|| "orb_window_not_found".to_string())?;
    clamp_orb_to_monitor(&window)
}

#[tauri::command]
async fn show_main_window(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_LABEL)
        .ok_or_else(|| "main_window_not_found".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().ok();
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

fn write_debug_session_log(app: &AppHandle, line: &str) {
    use std::io::Write;
    let workspace_root =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let mut paths = vec![
        workspace_root.join("debug-ddb680.log"),
        workspace_root.join(".cursor/debug-ddb680.log"),
    ];
    if let Ok(app_data) = app.path().app_data_dir() {
        paths.push(app_data.join("debug-ddb680.log"));
    }
    for path in paths {
        if let Ok(mut file) = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            let _ = writeln!(file, "{line}");
        }
    }
}

#[tauri::command]
fn debug_session_log(app: AppHandle, line: String) -> Result<(), String> {
    write_debug_session_log(&app, &line);
    Ok(())
}

fn register_debug_log_listener(app: &AppHandle) {
    let handle = app.clone();
    let _ = app.listen("debug-log", move |event| {
        write_debug_session_log(&handle, event.payload());
    });
}

#[tauri::command]
fn orb_save_audio_temp(app: AppHandle, data_base64: String, extension: String) -> Result<String, String> {
    let cleaned = data_base64
        .split_once(',')
        .map(|(_, payload)| payload.to_string())
        .unwrap_or(data_base64);
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(cleaned.trim())
        .map_err(|error| error.to_string())?;
    let ext = if extension.is_empty() {
        "webm".to_string()
    } else {
        extension
    };
    let dir = app
        .path()
        .temp_dir()
        .map_err(|error| error.to_string())?
        .join("mindi-orb-audio");
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let file_name = format!("capture-{}.{}", uuid::Uuid::new_v4(), ext);
    let file_path = dir.join(file_name);
    fs::write(&file_path, bytes).map_err(|error| error.to_string())?;
    Ok(file_path.to_string_lossy().to_string())
}

fn sanitize_upload_name(raw: &str) -> String {
    let trimmed = raw.trim();
    let base = trimmed
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(trimmed)
        .trim();
    let cleaned: String = base
        .chars()
        .map(|ch| if ch.is_alphanumeric() || matches!(ch, '.' | '-' | '_') { ch } else { '_' })
        .collect();
    if cleaned.is_empty() {
        "upload".to_string()
    } else {
        cleaned
    }
}

#[tauri::command]
fn save_upload_temp(app: AppHandle, data_base64: String, file_name: String) -> Result<String, String> {
    let cleaned = data_base64
        .split_once(',')
        .map(|(_, payload)| payload.to_string())
        .unwrap_or(data_base64);
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(cleaned.trim())
        .map_err(|error| error.to_string())?;
    let dir = app
        .path()
        .temp_dir()
        .map_err(|error| error.to_string())?
        .join("mindi-uploads");
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let unique = format!("{}-{}", uuid::Uuid::new_v4(), sanitize_upload_name(&file_name));
    let file_path = dir.join(unique);
    fs::write(&file_path, bytes).map_err(|error| error.to_string())?;
    Ok(file_path.to_string_lossy().to_string())
}

#[cfg(windows)]
fn allow_dev_microphone(window: &WebviewWindow) {
    let _ = window.with_webview(|platform| {
        use webview2_com::Microsoft::Web::WebView2::Win32::{
            ICoreWebView2Profile4, ICoreWebView2_13, COREWEBVIEW2_PERMISSION_KIND_MICROPHONE,
            COREWEBVIEW2_PERMISSION_STATE_ALLOW,
        };
        use windows::core::{Interface, PCWSTR};

        let controller = platform.controller();
        unsafe {
            let Ok(core) = controller.CoreWebView2() else {
                return;
            };
            let Ok(core13) = core.cast::<ICoreWebView2_13>() else {
                return;
            };
            let Ok(profile) = core13.Profile() else {
                return;
            };
            let Ok(profile4) = profile.cast::<ICoreWebView2Profile4>() else {
                return;
            };

            for origin in ["http://localhost:5173", "http://127.0.0.1:5173"] {
                let mut wide: Vec<u16> = origin.encode_utf16().collect();
                wide.push(0);
                let _ = profile4.SetPermissionState(
                    COREWEBVIEW2_PERMISSION_KIND_MICROPHONE,
                    PCWSTR::from_raw(wide.as_ptr()),
                    COREWEBVIEW2_PERMISSION_STATE_ALLOW,
                    None,
                );
            }
        }
    });
}

fn configure_orb_window(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let Some(window) = orb_window(app) else {
        return Ok(());
    };

    window.set_background_color(Some(tauri::window::Color(0, 0, 0, 0)))?;
    #[cfg(all(windows, debug_assertions))]
    allow_dev_microphone(&window);
    #[cfg(debug_assertions)]
    write_debug_session_log(
        app,
        r#"{"sessionId":"ddb680","runId":"post-remote-fix","hypothesisId":"P,C","location":"lib.rs:configure_orb_window","message":"orb window configured with mic allowlist","data":{"platform":"windows"}}"#,
    );

    let saved = load_orb_position(app);
    if saved.x > 0.0 || saved.y > 0.0 {
        let _ = window.set_position(LogicalPosition::new(saved.x, saved.y));
    }
    clamp_orb_to_monitor(&window).ok();
    Ok(())
}

fn hide_main_window_on_startup(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN_LABEL) {
        let _ = window.hide();
    }
}

fn register_exit_on_close(app: &AppHandle) {
    let handle = app.clone();
    for window in app.webview_windows().values() {
        let exit_handle = handle.clone();
        window.on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                exit_handle.exit(0);
            }
        });
    }
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn get_agent_token(app: AppHandle) -> Result<String, String> {
    let workspace_root =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let candidate = workspace_root.join("data/runtime/.agent-token");
    if candidate.exists() {
        return fs::read_to_string(&candidate)
            .map(|s| s.trim().to_string())
            .map_err(|e| e.to_string());
    }
    if let Ok(app_data) = app.path().app_data_dir() {
        let fallback = app_data.join("data/runtime/.agent-token");
        if fallback.exists() {
            return fs::read_to_string(&fallback)
                .map(|s| s.trim().to_string())
                .map_err(|e| e.to_string());
        }
    }
    Err("agent_token_not_found".to_string())
}

#[cfg(debug_assertions)]
fn local_port_open(port: u16) -> bool {
    use std::net::{SocketAddr, TcpStream};
    use std::time::Duration;

    let addr: SocketAddr = match format!("127.0.0.1:{port}").parse() {
        Ok(value) => value,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

#[cfg(debug_assertions)]
fn ensure_dev_agent_running(_app: &AppHandle) {
    use std::process::{Command, Stdio};

    if local_port_open(8765) {
        return;
    }

    let workspace_root =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let _ = Command::new("python")
        .args([
            "-m",
            "uvicorn",
            "mindi_agent.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--app-dir",
            "services/agent/src",
        ])
        .current_dir(&workspace_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

#[cfg(debug_assertions)]
fn ensure_dev_ai_runtime_running(_app: &AppHandle) {
    use std::process::{Command, Stdio};

    if local_port_open(8877) {
        return;
    }

    let workspace_root =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let _ = Command::new("python")
        .args([
            "-m",
            "uvicorn",
            "mindi_ai_runtime.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8877",
            "--app-dir",
            "services/ai_runtime/src",
        ])
        .current_dir(&workspace_root)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            #[cfg(debug_assertions)]
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Info)
                    .build(),
            )?;
            #[cfg(debug_assertions)]
            {
                ensure_dev_agent_running(app.handle());
                ensure_dev_ai_runtime_running(app.handle());
            }
            configure_orb_window(app.handle())?;
            hide_main_window_on_startup(app.handle());
            register_exit_on_close(app.handle());
            register_input_shortcuts(app.handle())?;
            #[cfg(debug_assertions)]
            register_debug_log_listener(app.handle());
            #[cfg(debug_assertions)]
            write_debug_session_log(
                app.handle(),
                r#"{"sessionId":"e8d849","location":"lib.rs:setup","message":"tauri app started","hypothesisId":"H"}"#,
            );
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            debug_session_log,
            orb_save_position,
            orb_set_size,
            orb_start_drag,
            orb_focus,
            orb_clamp_position,
            orb_save_audio_temp,
            show_main_window,
            save_upload_temp,
            quit_app,
            get_agent_token,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
