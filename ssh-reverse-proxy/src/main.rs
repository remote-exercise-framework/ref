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
use tracing::{debug, error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<()> {
    // Pre-init eprintln: tracing isn't up yet, so we cannot use info! here.
    // Kept so a misconfigured RUST_LOG can't fully silence the binary at startup.
    eprintln!("[SSH-PROXY] Starting initialization...");
    std::io::stderr().flush().ok();

    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "ssh_reverse_proxy=info,russh=warn".into()),
        )
        .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
        .init();

    info!("REF SSH Proxy starting...");

    let config = match std::env::args().nth(1) {
        Some(config_path) => {
            info!("Loading config from file: {}", config_path);
            Config::load(&config_path)?
        }
        None => {
            info!("Loading config from environment");
            Config::from_env()?
        }
    };

    info!("Configuration loaded:");
    info!("  Listen address: {}", config.server.listen_addr);
    info!("  API base URL: {}", config.api.base_url);
    info!("  Container SSH port: {}", config.container.ssh_port);

    debug!("Starting server task");
    if let Err(e) = server::run_server(config).await {
        error!("Server error: {}", e);
        return Err(e);
    }

    Ok(())
}
