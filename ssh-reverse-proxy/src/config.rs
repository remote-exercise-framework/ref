//! Configuration loading for the SSH proxy.

use serde::Deserialize;
use std::path::PathBuf;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub server: ServerConfig,
    pub api: ApiConfig,
    pub container: ContainerConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ServerConfig {
    /// Address to listen on (e.g., "0.0.0.0:2222")
    pub listen_addr: String,

    /// Path to the server's host key
    pub host_key_path: PathBuf,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ApiConfig {
    /// Base URL of the web API (e.g., "http://web:8000")
    pub base_url: String,

    /// Environment variable name containing the signing key
    #[serde(default = "default_signing_key_env")]
    pub signing_key_env: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ContainerConfig {
    /// SSH port on containers
    #[serde(default = "default_ssh_port")]
    pub ssh_port: u16,

    /// Directory containing container authentication keys (user_key, root_key)
    pub keys_dir: PathBuf,

    /// Connection timeout in seconds
    #[serde(default = "default_connection_timeout")]
    pub connection_timeout_secs: u64,

    /// Keepalive interval in seconds
    #[serde(default = "default_keepalive_interval")]
    pub keepalive_interval_secs: u64,
}

fn default_signing_key_env() -> String {
    "SSH_TO_WEB_KEY".to_string()
}

fn default_ssh_port() -> u16 {
    13370
}

fn default_connection_timeout() -> u64 {
    10
}

fn default_keepalive_interval() -> u64 {
    60
}

impl Config {
    /// Load configuration from a TOML file.
    pub fn load(path: &str) -> anyhow::Result<Self> {
        let contents = std::fs::read_to_string(path)?;
        let config: Config = toml::from_str(&contents)?;
        Ok(config)
    }

    /// Load configuration from environment variables with defaults.
    pub fn from_env() -> anyhow::Result<Self> {
        Ok(Config {
            server: ServerConfig {
                listen_addr: std::env::var("SSH_LISTEN_ADDR")
                    .unwrap_or_else(|_| "0.0.0.0:2222".to_string()),
                host_key_path: std::env::var("SSH_HOST_KEY_PATH")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| PathBuf::from("/data/host_key")),
            },
            api: ApiConfig {
                base_url: std::env::var("API_BASE_URL")
                    .unwrap_or_else(|_| "http://web:8000".to_string()),
                signing_key_env: "SSH_TO_WEB_KEY".to_string(),
            },
            container: ContainerConfig {
                ssh_port: std::env::var("CONTAINER_SSH_PORT")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(13370),
                keys_dir: std::env::var("CONTAINER_KEYS_DIR")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| PathBuf::from("/keys")),
                connection_timeout_secs: 10,
                keepalive_interval_secs: 60,
            },
        })
    }
}
