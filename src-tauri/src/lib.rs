use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct ServiceChild(Mutex<Option<CommandChild>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_opener::init())
    .plugin(tauri_plugin_shell::init())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
        app.manage(ServiceChild(Mutex::new(None)));
      } else {
        let (mut events, child) = app.shell().sidecar("micromatrix-service")?.spawn()?;
        app.manage(ServiceChild(Mutex::new(Some(child))));
        tauri::async_runtime::spawn(async move {
          while let Some(event) = events.recv().await {
            log::debug!("service sidecar event: {event:?}");
          }
        });
      }
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building Tauri application");

  app.run(|handle, event| {
    if matches!(event, tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }) {
      if let Some(child) = handle.state::<ServiceChild>().0.lock().expect("sidecar state").take() {
        let _ = child.kill();
      }
    }
  });
}
