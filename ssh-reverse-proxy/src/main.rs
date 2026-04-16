//! REF SSH Proxy - Custom SSH server for the Remote Exercise Framework.
//!
//! This replaces the patched OpenSSH server with a pure Rust implementation
//! using the russh crate.

mod api;
mod channel;
mod config;
mod server;

use anyhow::Result;
use config::Config;
use std::io::Write;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<()> {
    // Force stdout to be line-buffered (important for Docker container logs)
    // This ensures logs appear immediately in docker logs output
    eprintln!("[SSH-PROXY] Starting initialization...");
    std::io::stderr().flush().ok();

    // Initialize logging with line-buffered output
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "ref_ssh_proxy=info,russh=warn".into()),
        )
        .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
        .init();

    eprintln!("[SSH-PROXY] Tracing initialized");
    std::io::stderr().flush().ok();
    info!("REF SSH Proxy starting...");

    // Load configuration
    eprintln!("[SSH-PROXY] Loading configuration...");
    std::io::stderr().flush().ok();

    let config = match std::env::args().nth(1) {
        Some(config_path) => {
            eprintln!("[SSH-PROXY] Loading config from file: {}", config_path);
            std::io::stderr().flush().ok();
            Config::load(&config_path)?
        }
        None => {
            eprintln!("[SSH-PROXY] Loading config from environment");
            std::io::stderr().flush().ok();
            Config::from_env()?
        }
    };

    eprintln!("[SSH-PROXY] Config loaded:");
    eprintln!("[SSH-PROXY]   Listen: {}", config.server.listen_addr);
    eprintln!("[SSH-PROXY]   API: {}", config.api.base_url);
    eprintln!("[SSH-PROXY]   Container port: {}", config.container.ssh_port);
    std::io::stderr().flush().ok();

    info!("Configuration loaded:");
    info!("  Listen address: {}", config.server.listen_addr);
    info!("  API base URL: {}", config.api.base_url);
    info!("  Container SSH port: {}", config.container.ssh_port);

    // Run the server
    eprintln!("[SSH-PROXY] Starting server...");
    std::io::stderr().flush().ok();

    if let Err(e) = server::run_server(config).await {
        eprintln!("[SSH-PROXY] Server error: {}", e);
        std::io::stderr().flush().ok();
        error!("Server error: {}", e);
        return Err(e);
    }

    Ok(())
}
