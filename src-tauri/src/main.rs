// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
compile_error!("Desktop clients currently support macOS and Windows only; Linux is suspended");

fn main() {
  micromatrix_pi_mcp_lib::run();
}
