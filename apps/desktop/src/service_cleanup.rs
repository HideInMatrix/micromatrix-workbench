use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::{Duration, Instant};
use tauri_plugin_shell::process::CommandChild;

fn request(port: u16, method: &str, path: &str, body: &str, deadline: Instant) -> Option<String> {
  let remaining = deadline.checked_duration_since(Instant::now())?;
  let address: SocketAddr = format!("127.0.0.1:{port}").parse().ok()?;
  let mut stream = TcpStream::connect_timeout(&address, remaining.min(Duration::from_millis(300))).ok()?;
  stream.set_read_timeout(Some(remaining)).ok()?;
  stream.set_write_timeout(Some(remaining)).ok()?;
  let payload = format!("{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}", body.len());
  stream.write_all(payload.as_bytes()).ok()?;
  let mut response = Vec::new(); let mut buffer = [0u8; 1024];
  loop {
    stream.set_read_timeout(Some(deadline.checked_duration_since(Instant::now())?)).ok()?;
    let count = stream.read(&mut buffer).ok()?;
    if count == 0 { break; }
    response.extend_from_slice(&buffer[..count]);
    if response.len() > 8192 { return None; }
  }
  String::from_utf8(response).ok()
}

fn stop_owned(port: u16, pid: u32) {
  // Never stop a different service that happens to occupy the same port.
  // Owned stdio/process-tree cleanup and a status+off Tailscale transaction
  // can run sequentially. Do not SIGKILL the service halfway through them.
  let deadline = Instant::now() + Duration::from_secs(12);
  let Some(health) = request(port, "GET", "/healthz", "", deadline) else { return; };
  let Some((_, body)) = health.split_once("\r\n\r\n") else { return; };
  let Ok(health) = serde_json::from_str::<serde_json::Value>(body) else { return; };
  if health.get("process_id").and_then(|value| value.as_u64()) != Some(u64::from(pid)) { return; }
  let _ = request(port, "POST", "/api/desktop", r#"{"method":"stop_runtime","args":[]}"#, deadline);
}

pub fn close(child: CommandChild) {
  let port = std::env::var("MICROMATRIX_CONTROL_PORT").ok().and_then(|value| value.parse::<u16>().ok()).unwrap_or(8233);
  stop_owned(port, child.pid());
  let _ = child.kill(); // Only after bounded graceful cleanup; crash fallback remains bounded.
}
