use tauri::utils::config::BundleType;

pub fn configure(config: &mut tauri::Config, bundle: Option<BundleType>) {
  // Quiet MSI cannot request elevation and can fail after the app has exited.
  // Keep MSI unattended but allow the system installer to request permission.
  // Current-user NSIS retains quiet mode with no installer window.
  if bundle == Some(BundleType::Msi) {
    if let Some(windows) = config.plugins.0.get_mut("updater")
      .and_then(|updater| updater.get_mut("windows"))
      .and_then(|windows| windows.as_object_mut()) {
      windows.insert("installMode".into(), "passive".into());
    }
  }
}
