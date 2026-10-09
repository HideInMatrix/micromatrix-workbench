use std::{fs, path::{Path, PathBuf}, time::Duration};
use serde::{Deserialize, Serialize};
use tauri::{Manager, Url};
use tauri_plugin_updater::UpdaterExt;

const DEFAULT_PREFIX: &str = "https://cdn.gh-proxy.org/";
const MANIFEST: &str = "https://github.com/HideInMatrix/micromatrix-workbench/releases/latest/download/latest.json";

#[derive(Serialize, Deserialize)]
pub struct UpdatePreferences {
  pub download_proxy_prefix: String,
}
impl Default for UpdatePreferences {
  fn default() -> Self { Self { download_proxy_prefix: DEFAULT_PREFIX.into() } }
}

pub fn normalize_prefix(value: &str) -> Result<String, String> {
  let value = value.trim();
  if value.is_empty() { return Ok(String::new()); }
  if value.len() > 1024 || value.contains('\\') || value.chars().any(char::is_whitespace) {
    return Err("加速前缀格式无效".into());
  }
  let url = Url::parse(value).map_err(|_| "加速前缀须为 HTTPS URL")?;
  if url.scheme() != "https" || url.host_str().is_none() || !url.username().is_empty()
    || url.password().is_some() || url.query().is_some() || url.fragment().is_some() {
    return Err("加速前缀须为 HTTPS URL，不含账号、密码、查询参数或片段".into());
  }
  Ok(format!("{}/", url.as_str().trim_end_matches('/')))
}

fn github_url(prefix: &str, original: &Url) -> Result<Url, String> {
  if original.scheme() != "https" || original.host_str() != Some("github.com")
    || !original.username().is_empty() || original.password().is_some()
    || original.port().is_some_and(|port| port != 443)
    || original.query().is_some() || original.fragment().is_some()
    || !original.path().starts_with("/HideInMatrix/micromatrix-workbench/releases/") {
    return Err("更新资源必须来自本项目的 GitHub Release".into());
  }
  if prefix.is_empty() { return Ok(original.clone()); }
  Url::parse(&format!("{}{}", normalize_prefix(prefix)?, original.as_str())).map_err(|_| "加速 URL 无效".into())
}

fn path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
  Ok(app.path().app_config_dir().map_err(|e| e.to_string())?.join("update-preferences.json"))
}
fn read(file: &Path) -> Result<UpdatePreferences, String> {
  if !file.exists() { return Ok(UpdatePreferences::default()); }
  if fs::metadata(file).map_err(|e| e.to_string())?.len() > 16384 { return Err("更新配置文件过大".into()); }
  let contents = fs::read_to_string(file).map_err(|e| e.to_string())?;
  let mut settings: UpdatePreferences = serde_json::from_str(&contents).map_err(|_| "更新配置格式无效")?;
  settings.download_proxy_prefix = normalize_prefix(&settings.download_proxy_prefix)?;
  Ok(settings)
}
fn write(file: &Path, prefix: &str) -> Result<UpdatePreferences, String> {
  let settings = UpdatePreferences { download_proxy_prefix: normalize_prefix(prefix)? };
  let parent = file.parent().ok_or("更新配置目录无效")?;
  fs::create_dir_all(parent).map_err(|e| e.to_string())?;
  let temporary = file.with_extension(format!("{}.tmp", std::process::id()));
  fs::write(&temporary, serde_json::to_vec_pretty(&settings).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
  fs::rename(&temporary, file).map_err(|e| e.to_string())?;
  Ok(settings)
}

#[tauri::command]
pub fn get_update_preferences(app: tauri::AppHandle) -> Result<UpdatePreferences, String> { read(&path(&app)?) }
#[tauri::command]
pub fn save_update_preferences(app: tauri::AppHandle, prefix: String) -> Result<UpdatePreferences, String> { write(&path(&app)?, &prefix) }

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateMetadata {
  rid: u32,
  current_version: String,
  version: String,
  #[serde(skip_serializing_if = "Option::is_none")]
  body: Option<String>,
  raw_json: serde_json::Value,
}

#[tauri::command]
pub async fn check_update_with_prefix(webview: tauri::Webview) -> Result<Option<UpdateMetadata>, String> {
  let settings = read(&path(webview.app_handle())?)?;
  let manifest = Url::parse(MANIFEST).map_err(|e| e.to_string())?;
  let accelerated = github_url(&settings.download_proxy_prefix, &manifest)?;
  let endpoints = if accelerated == manifest { vec![manifest] } else { vec![accelerated, manifest] };
  // Keep the plugin's pinned public key, version comparator and signed-version
  // requirement. The prefix changes transport URLs, never signature policy.
  let updater = webview.updater_builder().endpoints(endpoints).map_err(|e| e.to_string())?
    .timeout(Duration::from_secs(15)).build().map_err(|e| e.to_string())?;
  let Some(mut update) = updater.check().await.map_err(|e| e.to_string())? else { return Ok(None); };
  update.download_url = github_url(&settings.download_proxy_prefix, &update.download_url)?;
  let metadata = UpdateMetadata { rid: 0, current_version: update.current_version.clone(), version: update.version.clone(), body: update.body.clone(), raw_json: update.raw_json.clone() };
  // Register in the same Webview resource table as the official JS plugin. Its
  // download/install/close commands still own and verify this Update resource.
  Ok(Some(UpdateMetadata { rid: webview.resources_table().add(update), ..metadata }))
}

#[cfg(test)]
mod tests {
  use super::*;
  #[test]
  fn prefix_validation_and_resource_scope() {
    assert_eq!(normalize_prefix("https://mirror.example/base").unwrap(), "https://mirror.example/base/");
    assert_eq!(normalize_prefix(" ").unwrap(), "");
    for bad in ["http://mirror.example", "file:///tmp", "https://user:password@mirror.example/", "https://mirror.example/?token=x", "https://mirror.example/#x"] { assert!(normalize_prefix(bad).is_err()); }
    let url = Url::parse(MANIFEST).unwrap();
    assert_eq!(github_url("https://mirror.example/", &url).unwrap().as_str(), format!("https://mirror.example/{MANIFEST}"));
    assert_eq!(github_url("", &url).unwrap(), url);
    assert!(github_url("", &Url::parse("https://evil.example/app.zip").unwrap()).is_err());
    assert!(github_url("", &Url::parse("https://github.com/other/repo/releases/download/v1/app.zip").unwrap()).is_err());
  }
  #[test]
  fn settings_persist_direct_mode_without_resetting_the_default() {
    let folder = std::env::temp_dir().join(format!("mm-update-preferences-{}", std::process::id()));
    let file = folder.join("preferences.json");
    assert_eq!(read(&file).unwrap().download_proxy_prefix, DEFAULT_PREFIX);
    write(&file, "").unwrap(); assert_eq!(read(&file).unwrap().download_proxy_prefix, "");
    write(&file, "https://mirror.example/base").unwrap(); assert_eq!(read(&file).unwrap().download_proxy_prefix, "https://mirror.example/base/");
    fs::remove_dir_all(folder).unwrap();
  }
}
