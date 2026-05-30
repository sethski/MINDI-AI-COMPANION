use base64::Engine;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tauri::{
    AppHandle, Listener, LogicalPosition, LogicalSize, Manager, PhysicalPosition, WebviewWindow,
};

const ORB_LABEL: &str = "orb";
const MAIN_LABEL: &str = "main";

#[derive(Serialize, Deserialize, Default, Clone)]
struct OrbPosition {
    x: f64,
    y: f64,
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
    let workspace_path =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../debug-4cfb89.log");
    let mut paths = vec![workspace_path];
    if let Ok(app_data) = app.path().app_data_dir() {
        paths.push(app_data.join("debug-e8d849.log"));
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

fn configure_orb_window(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let Some(window) = orb_window(app) else {
        return Ok(());
    };

    window.set_background_color(Some(tauri::window::Color(0, 0, 0, 0)))?;

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            configure_orb_window(app.handle())?;
            hide_main_window_on_startup(app.handle());
            register_exit_on_close(app.handle());
            register_debug_log_listener(app.handle());
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
