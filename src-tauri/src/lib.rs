use std::sync::{Arc, Mutex};

use tauri::Manager;
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

mod saved_secrets;
mod service_cleanup;
mod updater_policy;

#[derive(Default)]
struct ServiceState {
  child: Option<CommandChild>,
  error: Option<String>,
}

struct ServiceChild(Arc<Mutex<ServiceState>>);

// Windows updater exits directly after cleanup_before_exit, bypassing RunEvent.
// Keep an app resource guard so its cleanup also releases the owned sidecar.
struct ServiceCleanup(Arc<Mutex<ServiceState>>);
impl tauri::Resource for ServiceCleanup {}
impl Drop for ServiceCleanup {
  fn drop(&mut self) {
    if let Ok(mut service) = self.0.lock() {
      if let Some(child) = service.child.take() { service_cleanup::close(child); }
    }
  }
}

#[tauri::command]
fn desktop_service_error(state: tauri::State<'_, ServiceChild>) -> Option<String> {
  state.0.lock().ok().and_then(|service| service.error.clone())
}

#[tauri::command]
fn show_permission_prompt(window: tauri::WebviewWindow) -> Result<(), String> {
  window.show().map_err(|error| error.to_string())?;
  window.unminimize().map_err(|error| error.to_string())?;
  window.request_user_attention(Some(tauri::UserAttentionType::Critical)).map_err(|error| error.to_string())?;
  window.set_focus().map_err(|error| error.to_string())
}

#[tauri::command]
fn runtime_saved_secrets(app: tauri::AppHandle) -> Result<saved_secrets::SavedSecrets, String> {
  let config_file = match std::env::var("MICROMATRIX_CONFIG_FILE").ok().filter(|value| !value.trim().is_empty()) {
    Some(value) => std::path::PathBuf::from(value.trim()),
    None => app.path().home_dir().map_err(|error| error.to_string())?.join(".micromatrix-pi-mcp/runtime.json"),
  };
  saved_secrets::read(&config_file, &std::env::vars().collect())
}

#[tauri::command]
fn open_authorization_url(url: String) -> Result<(), String> {
  let parsed = tauri::Url::parse(&url).map_err(|_| "Invalid OAuth URL")?;
  let loopback = matches!(parsed.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"));
  if !parsed.username().is_empty() || parsed.password().is_some()
    || !(parsed.scheme() == "https" || (parsed.scheme() == "http" && loopback)) {
    return Err("OAuth requires HTTPS or loopback HTTP".into());
  }
  open::that_detached(parsed.as_str()).map_err(|error| error.to_string())
}

#[tauri::command]
fn open_computer_use_settings() -> Result<(), String> {
  // Fixed destination only; never accept an arbitrary settings URL/command.
  #[cfg(target_os = "macos")]
  { open::that_detached("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility").map_err(|error| error.to_string()) }
  #[cfg(not(target_os = "macos"))]
  { Err("Windows UI Automation requires an unlocked interactive desktop; no Accessibility grant or auto-elevation is available".into()) }
}

#[tauri::command]
fn reveal_computer_use_app() -> Result<(), String> {
  #[cfg(target_os = "macos")]
  {
    let application = if cfg!(debug_assertions) {
      std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries/micromatrix Computer Use.app")
    } else {
      std::env::current_exe().map_err(|error| error.to_string())?.parent()
        .and_then(|directory| directory.parent()).ok_or("Invalid desktop application path")?
        .join("Helpers/micromatrix Computer Use.app")
    };
    if !application.join("Contents/MacOS/micromatrix-computer").is_file() { return Err("Computer Use application bundle is missing".into()); }
    std::process::Command::new("/usr/bin/open").arg("-R").arg(application).spawn().map_err(|error| error.to_string())?;
    Ok(())
  }
  #[cfg(not(target_os = "macos"))]
  { Err("Windows does not require an Accessibility application grant".into()) }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let mut context = tauri::generate_context!();
  updater_policy::configure(context.config_mut(), tauri::utils::platform::bundle_type());
  let app = tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_updater::Builder::new().build())
    .plugin(tauri_plugin_process::init())
    .invoke_handler(tauri::generate_handler![desktop_service_error, show_permission_prompt, runtime_saved_secrets, open_authorization_url, open_computer_use_settings, reveal_computer_use_app])
    .setup(|app| {
      let service = Arc::new(Mutex::new(ServiceState::default()));
      app.manage(ServiceChild(service.clone()));
      app.resources_table().add(ServiceCleanup(service));
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      } else {
        // This process only loads configuration and serves the control UI.
        // MCP and Tunnel execution remain behind the user's Start action.
        let spawned = app.shell().sidecar("micromatrix-service").and_then(|command| command.spawn());
        match spawned {
          Ok((mut events, child)) => {
            app.state::<ServiceChild>().0.lock().expect("sidecar state").child = Some(child);
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
              let mut last_stderr = String::new();
              while let Some(event) = events.recv().await {
                let error = match event {
                  CommandEvent::Stderr(bytes) => {
                    last_stderr = String::from_utf8_lossy(&bytes).chars().take(1000).collect();
                    None
                  }
                  CommandEvent::Error(error) => Some(format!("本地控制服务异常：{error}")),
                  CommandEvent::Terminated(exit) => Some(format!(
                    "本地控制服务已退出（code={:?}, signal={:?}）。{}", exit.code, exit.signal, last_stderr
                  )),
                  _ => None,
                };
                if let Some(error) = error {
                  handle.state::<ServiceChild>().0.lock().expect("sidecar state").error = Some(error);
                }
              }
            });
          }
          Err(error) => {
            app.state::<ServiceChild>().0.lock().expect("sidecar state").error = Some(format!("本地控制服务无法启动：{error}"));
          }
        }
      }
      Ok(())
    })
    .build(context)
    .expect("error while building Tauri application");

  app.run(|handle, event| {
    if let tauri::RunEvent::ExitRequested { api, .. } = event {
      let child = handle.state::<ServiceChild>().0.lock().expect("sidecar state").child.take();
      if let Some(child) = child {
        api.prevent_exit();
        let handle = handle.clone();
        tauri::async_runtime::spawn(async move {
          let _ = tauri::async_runtime::spawn_blocking(move || service_cleanup::close(child)).await;
          handle.exit(0);
        });
      }
    }
  });
}
