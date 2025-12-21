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
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "ref_ssh_proxy=info,russh=warn".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!("REF SSH Proxy starting...");

    // Load configuration
    let config = match std::env::args().nth(1) {
        Some(config_path) => {
            info!("Loading config from {}", config_path);
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

    // Run the server
    if let Err(e) = server::run_server(config).await {
        error!("Server error: {}", e);
        return Err(e);
    }

    Ok(())
}
