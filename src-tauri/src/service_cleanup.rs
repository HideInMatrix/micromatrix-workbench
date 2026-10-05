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
  let deadline = Instant::now() + Duration::from_secs(6);
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

#[cfg(test)]
mod tests {
  use super::*;
  use std::net::TcpListener;
  use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};
  #[test]
  fn only_stops_the_owned_service() {
    for same_pid in [false, true] {
      let listener = TcpListener::bind("127.0.0.1:0").unwrap();
      let port = listener.local_addr().unwrap().port();
      let calls = Arc::new(AtomicUsize::new(0)); let recorded = calls.clone();
      let thread = std::thread::spawn(move || {
        for i in 0..(if same_pid {2} else {1}) {
          let (mut socket, _) = listener.accept().unwrap();
          let mut input = Vec::new(); let mut buffer = [0u8; 1024];
          loop {
            let count = socket.read(&mut buffer).unwrap(); input.extend_from_slice(&buffer[..count]);
            let text = std::str::from_utf8(&input).unwrap();
            if let Some((header, body)) = text.split_once("\r\n\r\n") {
              let length = header.lines().find_map(|line| line.strip_prefix("Content-Length: ")).unwrap().parse::<usize>().unwrap();
              if body.len() >= length { break; }
            }
          }
          let request = std::str::from_utf8(&input).unwrap();
          if i == 0 { assert!(request.starts_with("GET /healthz")); }
          else { assert!(request.contains("stop_runtime")); recorded.fetch_add(1, Ordering::SeqCst); }
          let body = if i == 0 { format!("{{\"ok\":true,\"process_id\":{}}}", if same_pid {1234} else {5678}) } else {"true".into()};
          write!(socket,"HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
        }
      });
      stop_owned(port,1234);thread.join().unwrap();
      assert_eq!(calls.load(Ordering::SeqCst),if same_pid {1} else {0});
    }
  }
}
