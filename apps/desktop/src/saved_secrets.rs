use std::{collections::HashMap, fs, path::Path};
use serde::Serialize;
use serde_json::Value;

#[derive(Default, Serialize)]
pub struct SavedSecrets {
  oauth_password: String,
  provider: String,
  options: HashMap<String, String>,
}

fn first(env: &HashMap<String, String>, keys: &[&str]) -> Option<String> {
  keys.iter().find_map(|key| env.get(*key).map(|value| value.trim()).filter(|value| !value.is_empty()).map(str::to_owned))
}

// Native-only, fixed configuration path: no caller-selected file and no HTTP
// endpoint exporting credentials. The UI keeps these in memory, masked by default.
pub fn read(file: &Path, env: &HashMap<String, String>) -> Result<SavedSecrets, String> {
  let disk: Value = match fs::read_to_string(file) {
    Ok(text) => serde_json::from_str(&text).map_err(|_| "无法读取已保存的密钥：配置格式错误")?,
    Err(error) if error.kind() == std::io::ErrorKind::NotFound => Value::Null,
    Err(_) => return Err("无法读取已保存的密钥：配置文件不可读".into()),
  };
  let mut result = SavedSecrets {
    oauth_password: first(env, &["MICROMATRIX_OAUTH_PASSWORD"])
      .or_else(|| disk["oauthPassword"].as_str().map(str::to_owned)).unwrap_or_default(),
    provider: first(env, &["MICROMATRIX_NETWORK_PROVIDER", "AGENT_RUNTIME_NETWORK_PROVIDER"])
      .or_else(|| disk["network"]["provider"].as_str().map(str::to_owned)).unwrap_or_else(|| "external".into()).to_lowercase(),
    options: HashMap::new(),
  };
  for (key, keys) in [
    ("tunnel_token", &["MICROMATRIX_TUNNEL_TOKEN", "AGENT_RUNTIME_TUNNEL_TOKEN"][..]),
    ("auth_token", &["MICROMATRIX_NGROK_AUTH_TOKEN"][..]),
  ] {
    if let Some(value) = first(env, keys).or_else(|| disk["network"]["options"][key].as_str().map(str::to_owned)) {
      result.options.insert(key.into(), value);
    }
  }
  Ok(result)
}
