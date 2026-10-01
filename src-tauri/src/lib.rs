use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

#[derive(Default)]
struct ServiceState {
  child: Option<CommandChild>,
  error: Option<String>,
}

struct ServiceChild(Mutex<ServiceState>);

#[tauri::command]
fn desktop_service_error(state: tauri::State<'_, ServiceChild>) -> Option<String> {
  state.0.lock().ok().and_then(|service| service.error.clone())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![desktop_service_error])
    .setup(|app| {
      app.manage(ServiceChild(Mutex::new(ServiceState::default())));
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
    .build(tauri::generate_context!())
    .expect("error while building Tauri application");

  app.run(|handle, event| {
    if matches!(event, tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }) {
      if let Some(child) = handle.state::<ServiceChild>().0.lock().expect("sidecar state").child.take() {
        let _ = child.kill();
      }
    }
  });
}
