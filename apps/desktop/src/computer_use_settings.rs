// User-opened permission UI, separate from short-lived MCP permission probes.
// No Runtime startup, TCC mutation, arbitrary path or model-supplied arguments.
#[derive(Default)]
pub struct PermissionWindow {
  #[cfg(target_os = "macos")]
  launcher: std::sync::Mutex<Option<std::process::Child>>,
}

#[cfg(target_os = "macos")]
const SETTINGS: &str = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility";

#[cfg(target_os = "macos")]
fn application() -> Result<std::path::PathBuf, String> {
  let application = if cfg!(debug_assertions) {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binaries/micromatrix Computer Use.app")
  } else {
    std::env::current_exe().map_err(|error| error.to_string())?.parent()
      .and_then(|directory| directory.parent()).ok_or("Invalid desktop application path")?
      .join("Helpers/micromatrix Computer Use.app")
  };
  if !application.join("Contents/MacOS/micromatrix-computer").is_file() {
    return Err("Computer Use application bundle is missing".into());
  }
  Ok(application)
}

#[cfg(target_os = "macos")]
fn permission_command(application: &std::path::Path) -> std::process::Command {
  let mut command = std::process::Command::new("/usr/bin/open");
  // -n isolates this visible window from existing headless IPC sessions.
  // -W keeps the launcher alive until this window exits, avoiding duplicate
  // onboarding windows on repeated clicks in the same desktop instance.
  command.args(["-n", "-W", "-a"]).arg(application).args(["--args", "--permission-settings"]);
  command
}

impl PermissionWindow {
  pub fn open(&self) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
      let application = application()?;
      let mut launcher = self.launcher.lock().map_err(|_| "Computer Use permission window is unavailable")?;
      if let Some(child) = launcher.as_mut() {
        if child.try_wait().map_err(|error| error.to_string())?.is_none() {
          return open::that_detached(SETTINGS).map_err(|error| error.to_string());
        }
      }
      *launcher = Some(permission_command(&application).spawn().map_err(|error| error.to_string())?);
      Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    { Err("Windows UI Automation requires an unlocked interactive desktop; no Accessibility grant or auto-elevation is available".into()) }
  }
}
