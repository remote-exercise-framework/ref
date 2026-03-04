//! SSH server implementation using russh.

use crate::api::ApiClient;
use crate::channel::{ChannelForwarder, ContainerEvent, DirectTcpIpForwarder, RemoteForwardManager, ShellForwarder, X11ForwardState, channel_msg_to_event};
use russh::ChannelReadHalf;
use crate::config::Config;
use anyhow::Result;
use russh::keys::PrivateKey;
use russh::server::{self, Auth, Handle, Msg, Server, Session};
use russh::{Channel, ChannelId, CryptoVec};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{debug, error, info, warn};

/// Per-connection state stored in the SSH server.
pub struct ConnectionState {
    /// The exercise name (parsed from SSH username)
    pub exercise_name: String,
    /// The authenticated user's public key
    pub pubkey: Option<String>,
    /// Container IP after provisioning
    pub container_ip: Option<String>,
    /// Whether to connect as root
    pub as_root: bool,
    /// Whether TCP forwarding is allowed
    pub tcp_forwarding_allowed: bool,
    /// Whether X11 forwarding is allowed
    pub x11_forwarding_allowed: bool,
    /// Welcome message to display
    pub welcome_message: Option<String>,
    /// Active channels
    pub channels: HashMap<ChannelId, ChannelContext>,
    /// Remote port forwarding manager
    pub remote_forward_manager: Option<RemoteForwardManager>,
    /// X11 forwarding state per channel
    pub x11_states: HashMap<ChannelId, X11ForwardState>,
}

/// Context for a single channel, including its forwarder.
pub struct ChannelContext {
    /// Channel type (session, direct-tcpip, etc.)
    pub channel_type: ChannelType,
    /// The forwarder for this channel (if active)
    pub forwarder: Option<Box<dyn ChannelForwarder>>,
    /// PTY parameters (stored until shell is requested)
    pub pty_params: Option<PtyParams>,
}

/// PTY parameters from pty_request.
#[derive(Clone)]
pub struct PtyParams {
    pub term: String,
    pub col_width: u32,
    pub row_height: u32,
    pub pix_width: u32,
    pub pix_height: u32,
}

#[derive(Debug, Clone)]
pub enum ChannelType {
    Session,
    DirectTcpIp { host: String, port: u32 },
}

impl Default for ConnectionState {
    fn default() -> Self {
        Self {
            exercise_name: String::new(),
            pubkey: None,
            container_ip: None,
            as_root: false,
            tcp_forwarding_allowed: false,
            x11_forwarding_allowed: false,
            welcome_message: None,
            channels: HashMap::new(),
            remote_forward_manager: None,
            x11_states: HashMap::new(),
        }
    }
}

/// Container authentication keys.
pub struct ContainerKeys {
    pub user_key: Arc<PrivateKey>,
    pub root_key: Arc<PrivateKey>,
}

impl ContainerKeys {
    /// Load container keys from a directory.
    pub fn load(keys_dir: &Path) -> Result<Self> {
        let user_key_path = keys_dir.join("user_key");
        let root_key_path = keys_dir.join("root_key");

        info!("Loading container keys from {:?}", keys_dir);

        let user_key = PrivateKey::read_openssh_file(&user_key_path)
            .map_err(|e| anyhow::anyhow!("Failed to load user_key: {}", e))?;
        let root_key = PrivateKey::read_openssh_file(&root_key_path)
            .map_err(|e| anyhow::anyhow!("Failed to load root_key: {}", e))?;

        Ok(Self {
            user_key: Arc::new(user_key),
            root_key: Arc::new(root_key),
        })
    }

    /// Get the appropriate key based on whether root access is needed.
    pub fn get_key(&self, as_root: bool) -> Arc<PrivateKey> {
        if as_root {
            Arc::clone(&self.root_key)
        } else {
            Arc::clone(&self.user_key)
        }
    }
}

/// SSH server handler.
pub struct SshServer {
    api_client: ApiClient,
    config: Config,
    /// Cache of valid public keys (refreshed periodically)
    valid_keys: Arc<Mutex<Vec<String>>>,
    /// Container authentication keys
    container_keys: Arc<ContainerKeys>,
}

impl SshServer {
    pub fn new(config: Config, api_client: ApiClient, container_keys: ContainerKeys) -> Self {
        Self {
            api_client,
            config,
            valid_keys: Arc::new(Mutex::new(Vec::new())),
            container_keys: Arc::new(container_keys),
        }
    }

    /// Refresh the cache of valid public keys.
    pub async fn refresh_keys(&self) -> Result<()> {
        let keys = self.api_client.get_keys().await?;
        let mut cache = self.valid_keys.lock().await;
        *cache = keys;
        info!("Refreshed {} public keys", cache.len());
        Ok(())
    }
}

impl server::Server for SshServer {
    type Handler = SshConnection;

    fn new_client(&mut self, _peer_addr: Option<std::net::SocketAddr>) -> Self::Handler {
        SshConnection {
            state: ConnectionState::default(),
            api_client: self.api_client.clone(),
            config: self.config.clone(),
            valid_keys: Arc::clone(&self.valid_keys),
            container_keys: Arc::clone(&self.container_keys),
        }
    }
}

/// Handler for a single SSH connection.
pub struct SshConnection {
    state: ConnectionState,
    api_client: ApiClient,
    config: Config,
    valid_keys: Arc<Mutex<Vec<String>>>,
    container_keys: Arc<ContainerKeys>,
}

impl SshConnection {
    /// Format a public key as a string for API calls.
    fn format_pubkey(key: &russh::keys::PublicKey) -> String {
        // Use the standard OpenSSH format
        key.to_string()
    }

    /// Spawn a task to forward events from container to client.
    fn spawn_event_forwarder(
        mut read_half: ChannelReadHalf,
        session_handle: Handle,
        client_channel_id: ChannelId,
    ) {
        tokio::spawn(async move {
            while let Some(msg) = read_half.wait().await {
                let event = match channel_msg_to_event(msg) {
                    Some(e) => e,
                    None => continue, // Skip ignored messages
                };

                let result: Result<(), String> = match event {
                    ContainerEvent::Data(data) => {
                        session_handle
                            .data(client_channel_id, CryptoVec::from_slice(&data))
                            .await
                            .map_err(|e| format!("data: {:?}", e))
                    }
                    ContainerEvent::ExtendedData { ext_type, data } => {
                        session_handle
                            .extended_data(client_channel_id, ext_type, CryptoVec::from_slice(&data))
                            .await
                            .map_err(|e| format!("extended_data: {:?}", e))
                    }
                    ContainerEvent::Eof => {
                        session_handle.eof(client_channel_id).await
                            .map_err(|_| "eof".to_string())
                    }
                    ContainerEvent::Close => {
                        session_handle.close(client_channel_id).await
                            .map_err(|_| "close".to_string())
                    }
                    ContainerEvent::ExitStatus(status) => {
                        session_handle.exit_status_request(client_channel_id, status).await
                            .map_err(|_| "exit_status".to_string())
                    }
                    ContainerEvent::ExitSignal {
                        signal_name,
                        core_dumped,
                        error_message,
                        lang_tag,
                    } => {
                        // Convert signal name to russh::Sig
                        let sig = match signal_name.as_str() {
                            "ABRT" => russh::Sig::ABRT,
                            "ALRM" => russh::Sig::ALRM,
                            "FPE" => russh::Sig::FPE,
                            "HUP" => russh::Sig::HUP,
                            "ILL" => russh::Sig::ILL,
                            "INT" => russh::Sig::INT,
                            "KILL" => russh::Sig::KILL,
                            "PIPE" => russh::Sig::PIPE,
                            "QUIT" => russh::Sig::QUIT,
                            "SEGV" => russh::Sig::SEGV,
                            "TERM" => russh::Sig::TERM,
                            "USR1" => russh::Sig::USR1,
                            _ => russh::Sig::TERM,
                        };
                        session_handle
                            .exit_signal_request(
                                client_channel_id,
                                sig,
                                core_dumped,
                                error_message,
                                lang_tag,
                            )
                            .await
                            .map_err(|_| "exit_signal".to_string())
                    }
                    ContainerEvent::WindowAdjusted(_) => {
                        // No action needed for window adjustments
                        Ok(())
                    }
                };

                if let Err(e) = result {
                    error!("Failed to forward event to client: {}", e);
                    break;
                }
            }
            debug!("Event forwarder task ended for channel {:?}", client_channel_id);
        });
    }
}

impl server::Handler for SshConnection {
    type Error = anyhow::Error;

    /// Called when a client authenticates with a public key.
    async fn auth_publickey(
        &mut self,
        user: &str,
        public_key: &russh::keys::PublicKey,
    ) -> Result<Auth, Self::Error> {
        use std::io::Write;
        eprintln!("[SSH-PROXY] auth_publickey called: user={}", user);
        std::io::stderr().flush().ok();
        info!("[AUTH] Auth attempt started: user={}", user);

        // Store the exercise name from the username
        self.state.exercise_name = user.to_string();

        // Format the public key for comparison
        eprintln!("[SSH-PROXY] Formatting public key...");
        std::io::stderr().flush().ok();
        let key_str = Self::format_pubkey(public_key);
        eprintln!("[SSH-PROXY] Client public key: {}", key_str);
        std::io::stderr().flush().ok();
        info!("[AUTH] Client public key: {}", key_str);

        // Helper to check if key is in cache
        let check_key_in_cache = |cache: &[String], key: &str| -> bool {
            let key_parts: Vec<&str> = key.split_whitespace().collect();
            eprintln!("[SSH-PROXY] Client key parts count: {}", key_parts.len());
            std::io::stderr().flush().ok();
            if key_parts.len() >= 2 {
                eprintln!("[SSH-PROXY] Client key type: {}, data (first 40): {}...",
                    key_parts[0],
                    &key_parts[1][..std::cmp::min(40, key_parts[1].len())]);
                std::io::stderr().flush().ok();
            }

            for (i, k) in cache.iter().enumerate() {
                let cached_parts: Vec<&str> = k.split_whitespace().collect();
                if cached_parts.len() >= 2 {
                    eprintln!("[SSH-PROXY] Cached key {}: type={}, data (first 40): {}...",
                        i, cached_parts[0],
                        &cached_parts[1][..std::cmp::min(40, cached_parts[1].len())]);
                    std::io::stderr().flush().ok();
                    if key_parts.len() >= 2 && key_parts[1] == cached_parts[1] {
                        eprintln!("[SSH-PROXY] Found matching key at index {}", i);
                        std::io::stderr().flush().ok();
                        return true;
                    }
                } else {
                    eprintln!("[SSH-PROXY] Cached key {} has {} parts: {:?}", i, cached_parts.len(), k);
                    std::io::stderr().flush().ok();
                }
            }
            eprintln!("[SSH-PROXY] No matching key found in cache");
            std::io::stderr().flush().ok();
            false
        };

        // Check if the key is in our valid keys cache
        eprintln!("[SSH-PROXY] Checking key against cache...");
        std::io::stderr().flush().ok();
        let mut is_valid = {
            let cache = self.valid_keys.lock().await;
            eprintln!("[SSH-PROXY] Cache has {} keys", cache.len());
            std::io::stderr().flush().ok();
            info!("[AUTH] Checking key against {} cached keys", cache.len());
            check_key_in_cache(&cache, &key_str)
        };

        // If not found, refresh keys and try again (for newly registered users)
        if !is_valid {
            eprintln!("[SSH-PROXY] Key not in cache, refreshing on-demand...");
            std::io::stderr().flush().ok();
            info!("[AUTH] Key not in cache, refreshing keys on-demand");
            match self.api_client.get_keys().await {
                Ok(keys) => {
                    let mut cache = self.valid_keys.lock().await;
                    eprintln!("[SSH-PROXY] On-demand refresh got {} keys", keys.len());
                    std::io::stderr().flush().ok();
                    info!("[AUTH] On-demand refresh got {} keys", keys.len());
                    *cache = keys;
                    is_valid = check_key_in_cache(&cache, &key_str);
                }
                Err(e) => {
                    eprintln!("[SSH-PROXY] Failed to refresh keys: {}", e);
                    std::io::stderr().flush().ok();
                    error!("[AUTH] Failed to refresh keys on-demand: {}", e);
                }
            }
        }

        if !is_valid {
            eprintln!("[SSH-PROXY] REJECTED: Invalid public key for user {}", user);
            std::io::stderr().flush().ok();
            error!("[AUTH] REJECTED: Invalid public key for user {}", user);
            return Ok(Auth::Reject {
                proceed_with_methods: None,
                partial_success: false,
            });
        }
        eprintln!("[SSH-PROXY] Key validation passed for user {}", user);
        std::io::stderr().flush().ok();
        info!("[AUTH] Key validation passed for user {}", user);

        // Store the authenticated key
        self.state.pubkey = Some(key_str.clone());

        // Get user permissions from API
        eprintln!("[SSH-PROXY] Calling ssh_authenticated API...");
        std::io::stderr().flush().ok();
        match self
            .api_client
            .ssh_authenticated(&self.state.exercise_name, &key_str)
            .await
        {
            Ok(auth_response) => {
                eprintln!("[SSH-PROXY] ssh_authenticated succeeded: instance_id={}", auth_response.instance_id);
                std::io::stderr().flush().ok();
                // TODO: Use API response for permissions when webapp supports it
                // For now, mock all permissions as allowed (per user request)
                self.state.tcp_forwarding_allowed = true;  // Mocked: always allow
                self.state.x11_forwarding_allowed = true;  // Mocked: always allow
                debug!(
                    "User authenticated: instance_id={}, forwarding={}, x11={} (mocked: always allowed)",
                    auth_response.instance_id, self.state.tcp_forwarding_allowed, self.state.x11_forwarding_allowed
                );
            }
            Err(e) => {
                eprintln!("[SSH-PROXY] ssh_authenticated FAILED: {}", e);
                std::io::stderr().flush().ok();
                error!("Failed to get user permissions: {}", e);
                return Ok(Auth::Reject {
                    proceed_with_methods: None,
                    partial_success: false,
                });
            }
        }

        // Provision the container
        eprintln!("[SSH-PROXY] Calling provision API...");
        std::io::stderr().flush().ok();
        match self
            .api_client
            .provision(&self.state.exercise_name, &key_str)
            .await
        {
            Ok(provision) => {
                eprintln!("[SSH-PROXY] Provisioned container at {} (as_root={})", provision.ip, provision.as_root);
                std::io::stderr().flush().ok();
                self.state.container_ip = Some(provision.ip.clone());
                self.state.as_root = provision.as_root;
                self.state.welcome_message = provision.welcome_message;
                info!(
                    "Provisioned container at {} for exercise {} (as_root={})",
                    provision.ip, self.state.exercise_name, provision.as_root
                );
            }
            Err(e) => {
                eprintln!("[SSH-PROXY] Provision FAILED: {}", e);
                std::io::stderr().flush().ok();
                error!("Failed to provision container: {}", e);
                return Ok(Auth::Reject {
                    proceed_with_methods: None,
                    partial_success: false,
                });
            }
        }

        eprintln!("[SSH-PROXY] Auth complete - returning Accept");
        std::io::stderr().flush().ok();
        Ok(Auth::Accept)
    }

    /// Called when a channel is opened.
    async fn channel_open_session(
        &mut self,
        channel: Channel<Msg>,
        _session: &mut Session,
    ) -> Result<bool, Self::Error> {
        let channel_id = channel.id();
        debug!("Session channel opened: {:?}", channel_id);

        self.state.channels.insert(
            channel_id,
            ChannelContext {
                channel_type: ChannelType::Session,
                forwarder: None,
                pty_params: None,
            },
        );

        Ok(true)
    }

    /// Called when a PTY is requested.
    async fn pty_request(
        &mut self,
        channel_id: ChannelId,
        term: &str,
        col_width: u32,
        row_height: u32,
        pix_width: u32,
        pix_height: u32,
        _modes: &[(russh::Pty, u32)],
        _session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!(
            "PTY requested: term={}, size={}x{}",
            term, col_width, row_height
        );

        // Store PTY params for when shell is requested
        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            ctx.pty_params = Some(PtyParams {
                term: term.to_string(),
                col_width,
                row_height,
                pix_width,
                pix_height,
            });
        }

        Ok(())
    }

    /// Called when a shell is requested.
    async fn shell_request(
        &mut self,
        channel_id: ChannelId,
        session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!("Shell requested on channel {:?}", channel_id);

        let container_ip = match &self.state.container_ip {
            Some(ip) => ip.clone(),
            None => {
                error!("No container IP available");
                return Ok(());
            }
        };

        // Get container SSH port from config
        let container_port = self.config.container.ssh_port;
        let username = if self.state.as_root { "root" } else { "user" };
        let auth_key = self.container_keys.get_key(self.state.as_root);

        // Connect to container SSH
        info!(
            "Connecting to container {}:{} as {}",
            container_ip, container_port, username
        );

        let mut forwarder = match ShellForwarder::connect(
            &container_ip,
            container_port,
            auth_key,
            username,
        )
        .await
        {
            Ok(f) => f,
            Err(e) => {
                error!("Failed to connect to container: {}", e);
                let msg = format!("Error: Failed to connect to container: {}\r\n", e);
                session.data(channel_id, CryptoVec::from_slice(msg.as_bytes()))?;
                return Ok(());
            }
        };

        // Request PTY on container if we have params
        if let Some(ctx) = self.state.channels.get(&channel_id) {
            if let Some(ref pty) = ctx.pty_params {
                if let Err(e) = forwarder
                    .request_pty(&pty.term, pty.col_width, pty.row_height, pty.pix_width, pty.pix_height)
                    .await
                {
                    error!("Failed to request PTY on container: {}", e);
                }
            }
        }

        // Request shell on container
        if let Err(e) = forwarder.request_shell().await {
            error!("Failed to request shell on container: {}", e);
            let msg = format!("Error: Failed to start shell: {}\r\n", e);
            session.data(channel_id, CryptoVec::from_slice(msg.as_bytes()))?;
            return Ok(());
        }

        // Get read half and spawn forwarder task
        if let Some(read_half) = forwarder.take_read_half() {
            let session_handle = session.handle();
            Self::spawn_event_forwarder(read_half, session_handle, channel_id);
        }

        // Store forwarder in channel context
        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            ctx.forwarder = Some(Box::new(forwarder));
        }

        // Send welcome message if we have one
        if let Some(ref welcome) = self.state.welcome_message {
            // Note: The welcome message will appear after the shell prompt
            // because the container is now connected
            debug!("Welcome message available: {}", welcome.len());
        }

        info!(
            "Shell session established for exercise '{}' on container {}",
            self.state.exercise_name, container_ip
        );

        Ok(())
    }

    /// Called when a command execution is requested.
    async fn exec_request(
        &mut self,
        channel_id: ChannelId,
        data: &[u8],
        session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!("Exec requested on channel {:?}: {:?}", channel_id, String::from_utf8_lossy(data));

        let container_ip = match &self.state.container_ip {
            Some(ip) => ip.clone(),
            None => {
                error!("No container IP available");
                session.channel_failure(channel_id)?;
                return Ok(());
            }
        };

        // Get container SSH port from config
        let container_port = self.config.container.ssh_port;
        let username = if self.state.as_root { "root" } else { "user" };
        let auth_key = self.container_keys.get_key(self.state.as_root);

        // Connect to container SSH
        let mut forwarder = match ShellForwarder::connect(
            &container_ip,
            container_port,
            auth_key,
            username,
        )
        .await
        {
            Ok(f) => f,
            Err(e) => {
                error!("Failed to connect to container: {}", e);
                session.channel_failure(channel_id)?;
                return Ok(());
            }
        };

        // Execute command on container
        if let Err(e) = forwarder.exec(data).await {
            error!("Failed to execute command on container: {}", e);
            session.channel_failure(channel_id)?;
            return Ok(());
        }

        // Get read half and spawn forwarder task
        if let Some(read_half) = forwarder.take_read_half() {
            let session_handle = session.handle();
            Self::spawn_event_forwarder(read_half, session_handle, channel_id);
        }

        // Store forwarder in channel context
        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            ctx.forwarder = Some(Box::new(forwarder));
        }

        // Signal success to client
        session.channel_success(channel_id)?;

        info!(
            "Exec request for '{}' on container {}",
            String::from_utf8_lossy(data), container_ip
        );

        Ok(())
    }

    /// Called when a subsystem is requested (e.g., SFTP).
    async fn subsystem_request(
        &mut self,
        channel_id: ChannelId,
        name: &str,
        session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!("Subsystem '{}' requested on channel {:?}", name, channel_id);

        let container_ip = match &self.state.container_ip {
            Some(ip) => ip.clone(),
            None => {
                error!("No container IP available");
                session.channel_failure(channel_id)?;
                return Ok(());
            }
        };

        // Get container SSH port from config
        let container_port = self.config.container.ssh_port;
        let username = if self.state.as_root { "root" } else { "user" };
        let auth_key = self.container_keys.get_key(self.state.as_root);

        // Connect to container SSH
        let mut forwarder = match ShellForwarder::connect(
            &container_ip,
            container_port,
            auth_key,
            username,
        )
        .await
        {
            Ok(f) => f,
            Err(e) => {
                error!("Failed to connect to container: {}", e);
                session.channel_failure(channel_id)?;
                return Ok(());
            }
        };

        // Request subsystem on container
        if let Err(e) = forwarder.request_subsystem(name).await {
            error!("Failed to request subsystem '{}' on container: {}", name, e);
            session.channel_failure(channel_id)?;
            return Ok(());
        }

        // Get read half and spawn forwarder task
        if let Some(read_half) = forwarder.take_read_half() {
            let session_handle = session.handle();
            Self::spawn_event_forwarder(read_half, session_handle, channel_id);
        }

        // Store forwarder in channel context
        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            ctx.forwarder = Some(Box::new(forwarder));
        }

        // Signal success to client
        session.channel_success(channel_id)?;

        info!(
            "Subsystem '{}' started on container {}",
            name, container_ip
        );

        Ok(())
    }

    /// Called when X11 forwarding is requested.
    async fn x11_request(
        &mut self,
        channel_id: ChannelId,
        single_connection: bool,
        x11_auth_protocol: &str,
        x11_auth_cookie: &str,
        x11_screen_number: u32,
        session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!(
            "X11 forwarding requested on channel {:?}: protocol={}, screen={}",
            channel_id, x11_auth_protocol, x11_screen_number
        );

        if !self.state.x11_forwarding_allowed {
            warn!("X11 forwarding not allowed for this user");
            session.channel_failure(channel_id)?;
            return Ok(());
        }

        // Store X11 state for this channel
        let x11_state = X11ForwardState::new(
            single_connection,
            x11_auth_protocol,
            x11_auth_cookie,
            x11_screen_number,
        );
        self.state.x11_states.insert(channel_id, x11_state);

        // Signal success to client
        session.channel_success(channel_id)?;

        info!(
            "X11 forwarding enabled for channel {:?}",
            channel_id
        );

        Ok(())
    }

    /// Called when data is received on a channel.
    async fn data(
        &mut self,
        channel_id: ChannelId,
        data: &[u8],
        _session: &mut Session,
    ) -> Result<(), Self::Error> {
        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            if let Some(ref mut forwarder) = ctx.forwarder {
                if let Err(e) = forwarder.forward_data(data).await {
                    error!("Failed to forward data to container: {}", e);
                }
            } else {
                debug!("No forwarder for channel {:?}, dropping {} bytes", channel_id, data.len());
            }
        }
        Ok(())
    }

    /// Called when window size changes.
    async fn window_change_request(
        &mut self,
        channel_id: ChannelId,
        col_width: u32,
        row_height: u32,
        pix_width: u32,
        pix_height: u32,
        _session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!(
            "Window change: {}x{} on channel {:?}",
            col_width, row_height, channel_id
        );

        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            if let Some(ref mut forwarder) = ctx.forwarder {
                if let Err(e) = forwarder
                    .window_change(col_width, row_height, pix_width, pix_height)
                    .await
                {
                    error!("Failed to forward window change: {}", e);
                }
            }
        }
        Ok(())
    }

    /// Called when EOF is received on a channel.
    async fn channel_eof(
        &mut self,
        channel_id: ChannelId,
        _session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!("Channel EOF: {:?}", channel_id);

        if let Some(ctx) = self.state.channels.get_mut(&channel_id) {
            if let Some(ref mut forwarder) = ctx.forwarder {
                if let Err(e) = forwarder.eof().await {
                    error!("Failed to forward EOF to container: {}", e);
                }
            }
        }
        Ok(())
    }

    /// Called when a channel is closed.
    async fn channel_close(
        &mut self,
        channel_id: ChannelId,
        _session: &mut Session,
    ) -> Result<(), Self::Error> {
        debug!("Channel closed: {:?}", channel_id);

        if let Some(mut ctx) = self.state.channels.remove(&channel_id) {
            if let Some(ref mut forwarder) = ctx.forwarder {
                if let Err(e) = forwarder.close().await {
                    error!("Failed to close container channel: {}", e);
                }
            }
        }
        Ok(())
    }

    /// Called when a direct TCP/IP channel is requested (local port forwarding).
    async fn channel_open_direct_tcpip(
        &mut self,
        channel: Channel<Msg>,
        host_to_connect: &str,
        port_to_connect: u32,
        originator_address: &str,
        originator_port: u32,
        session: &mut Session,
    ) -> Result<bool, Self::Error> {
        debug!(
            "Direct TCP/IP requested: {}:{} from {}:{}",
            host_to_connect, port_to_connect, originator_address, originator_port
        );

        if !self.state.tcp_forwarding_allowed {
            warn!("TCP forwarding not allowed for this user");
            return Ok(false);
        }

        let container_ip = match &self.state.container_ip {
            Some(ip) => ip.clone(),
            None => {
                error!("No container IP available for direct-tcpip");
                return Ok(false);
            }
        };

        let channel_id = channel.id();
        let container_port = self.config.container.ssh_port;
        let username = if self.state.as_root { "root" } else { "user" };
        let auth_key = self.container_keys.get_key(self.state.as_root);

        // Connect to the target host:port through the container SSH
        let session_handle = session.handle();
        let forwarder = match DirectTcpIpForwarder::connect(
            &container_ip,
            container_port,
            auth_key,
            username,
            host_to_connect,
            port_to_connect,
            session_handle,
            channel_id,
        )
        .await
        {
            Ok(f) => f,
            Err(e) => {
                error!(
                    "Failed to open direct-tcpip to {}:{} through container: {}",
                    host_to_connect, port_to_connect, e
                );
                return Ok(false);
            }
        };

        self.state.channels.insert(
            channel_id,
            ChannelContext {
                channel_type: ChannelType::DirectTcpIp {
                    host: host_to_connect.to_string(),
                    port: port_to_connect,
                },
                forwarder: Some(Box::new(forwarder)),
                pty_params: None,
            },
        );

        info!(
            "Direct TCP/IP channel opened to {}:{} through container {} for channel {:?}",
            host_to_connect, port_to_connect, container_ip, channel_id
        );

        Ok(true)
    }

    /// Called when a TCP/IP forwarding request is made (remote port forwarding).
    async fn tcpip_forward(
        &mut self,
        address: &str,
        port: &mut u32,
        session: &mut Session,
    ) -> Result<bool, Self::Error> {
        debug!("TCP/IP forward requested: {}:{}", address, port);

        if !self.state.tcp_forwarding_allowed {
            warn!("TCP forwarding not allowed for this user");
            return Ok(false);
        }

        let container_ip = match &self.state.container_ip {
            Some(ip) => ip.clone(),
            None => {
                error!("No container IP available for tcpip_forward");
                return Ok(false);
            }
        };

        let container_port = self.config.container.ssh_port;
        let username = if self.state.as_root { "root" } else { "user" };
        let auth_key = self.container_keys.get_key(self.state.as_root);

        // Initialize remote forward manager if needed
        if self.state.remote_forward_manager.is_none() {
            self.state.remote_forward_manager = Some(RemoteForwardManager::new(
                session.handle(),
                container_ip.clone(),
                container_port,
                auth_key,
                username.to_string(),
            ));
        }

        // Request the forward
        let manager = self.state.remote_forward_manager.as_mut().unwrap();
        match manager.request_forward(address, *port).await {
            Ok(bound_port) => {
                *port = bound_port;
                info!(
                    "Remote port forwarding established: {}:{} -> bound port {}",
                    address, port, bound_port
                );
                Ok(true)
            }
            Err(e) => {
                error!("Failed to establish remote port forwarding: {}", e);
                Ok(false)
            }
        }
    }

    /// Called when a TCP/IP forwarding request is cancelled.
    async fn cancel_tcpip_forward(
        &mut self,
        address: &str,
        port: u32,
        _session: &mut Session,
    ) -> Result<bool, Self::Error> {
        debug!("Cancel TCP/IP forward requested: {}:{}", address, port);

        if let Some(ref mut manager) = self.state.remote_forward_manager {
            match manager.cancel_forward(address, port).await {
                Ok(()) => {
                    info!("Remote port forwarding cancelled: {}:{}", address, port);
                    Ok(true)
                }
                Err(e) => {
                    error!("Failed to cancel remote port forwarding: {}", e);
                    Ok(false)
                }
            }
        } else {
            warn!("No remote forward manager for cancel request");
            Ok(false)
        }
    }
}

/// Spawn a background task that periodically refreshes the key cache.
fn spawn_key_refresh_task(
    api_client: ApiClient,
    valid_keys: Arc<Mutex<Vec<String>>>,
    refresh_interval_secs: u64,
) {
    tokio::spawn(async move {
        let interval = std::time::Duration::from_secs(refresh_interval_secs);
        loop {
            tokio::time::sleep(interval).await;
            match api_client.get_keys().await {
                Ok(keys) => {
                    let mut cache = valid_keys.lock().await;
                    let old_count = cache.len();
                    *cache = keys;
                    if cache.len() != old_count {
                        info!(
                            "Key refresh: {} -> {} keys",
                            old_count,
                            cache.len()
                        );
                    }
                }
                Err(e) => {
                    warn!("Failed to refresh keys: {}", e);
                }
            }
        }
    });
}

/// Run the SSH server.
pub async fn run_server(config: Config) -> Result<()> {
    use std::io::Write;
    eprintln!("[SSH-PROXY] run_server: Creating API client...");
    std::io::stderr().flush().ok();

    let api_client = ApiClient::from_env(
        config.api.base_url.clone(),
        &config.api.signing_key_env,
    )?;

    eprintln!("[SSH-PROXY] run_server: Loading container keys...");
    std::io::stderr().flush().ok();

    // Load container keys
    let container_keys = ContainerKeys::load(&config.container.keys_dir)?;

    eprintln!("[SSH-PROXY] run_server: Creating server...");
    std::io::stderr().flush().ok();

    let mut server = SshServer::new(config.clone(), api_client.clone(), container_keys);

    // Initial key refresh with retries (web server may not be ready yet)
    eprintln!("[SSH-PROXY] run_server: Initial key refresh...");
    std::io::stderr().flush().ok();

    let max_retries = 30;
    let mut retry_count = 0;
    loop {
        match server.refresh_keys().await {
            Ok(_) => {
                eprintln!("[SSH-PROXY] run_server: Keys refreshed successfully");
                std::io::stderr().flush().ok();
                break;
            }
            Err(e) => {
                retry_count += 1;
                if retry_count >= max_retries {
                    eprintln!("[SSH-PROXY] run_server: Failed to fetch keys after {} retries: {}", max_retries, e);
                    std::io::stderr().flush().ok();
                    return Err(anyhow::anyhow!(
                        "Failed to fetch keys after {} retries: {}",
                        max_retries,
                        e
                    ));
                }
                eprintln!("[SSH-PROXY] run_server: Key refresh attempt {} failed: {}. Retrying...", retry_count, e);
                std::io::stderr().flush().ok();
                warn!(
                    "Failed to fetch keys (attempt {}/{}): {}. Retrying in 1s...",
                    retry_count, max_retries, e
                );
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            }
        }
    }

    // Spawn background task to periodically refresh keys (every 60 seconds)
    eprintln!("[SSH-PROXY] run_server: Spawning key refresh task...");
    std::io::stderr().flush().ok();
    spawn_key_refresh_task(api_client, Arc::clone(&server.valid_keys), 60);

    // Load host key
    let key_path = &config.server.host_key_path;
    let key = if key_path.exists() {
        eprintln!("[SSH-PROXY] run_server: Loading host key from {:?}", key_path);
        std::io::stderr().flush().ok();
        info!("Loading host key from {:?}", key_path);
        russh::keys::PrivateKey::read_openssh_file(key_path)?
    } else {
        eprintln!("[SSH-PROXY] run_server: Generating new host key");
        std::io::stderr().flush().ok();
        info!("Generating new host key");
        let key = russh::keys::PrivateKey::random(
            &mut rand::thread_rng(),
            russh::keys::Algorithm::Ed25519,
        )?;
        // TODO: Save for persistence
        key
    };

    let russh_config = russh::server::Config {
        inactivity_timeout: Some(std::time::Duration::from_secs(3600)),
        auth_rejection_time: std::time::Duration::from_secs(3),
        auth_rejection_time_initial: Some(std::time::Duration::from_secs(0)),
        keys: vec![key],
        ..Default::default()
    };

    let addr: std::net::SocketAddr = config.server.listen_addr.parse()?;
    eprintln!("[SSH-PROXY] run_server: Starting SSH server on {}...", addr);
    std::io::stderr().flush().ok();
    info!("Starting SSH server on {}", addr);

    server.run_on_address(Arc::new(russh_config), addr).await?;

    eprintln!("[SSH-PROXY] run_server: Server terminated");
    std::io::stderr().flush().ok();

    Ok(())
}
