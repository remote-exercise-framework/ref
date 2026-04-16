//! Shell session forwarding to container SSH.
//!
//! This module handles the bidirectional forwarding of shell sessions
//! between the client and a container's SSH server.

use crate::channel::forwarder::{ChannelForwarder, ContainerEvent};
use anyhow::{anyhow, Result};
use async_trait::async_trait;
use russh::client::{self, Msg};
use russh::keys::{PrivateKey, PrivateKeyWithHashAlg};
use russh::{ChannelId, ChannelMsg, ChannelWriteHalf, ChannelReadHalf};
use std::sync::Arc;
use tokio::io::AsyncWriteExt;
use tracing::{debug, info};

/// Handler for container SSH client events.
///
/// This is a minimal handler - we use channel.wait() to receive
/// messages instead of Handler callbacks.
struct ContainerHandler;

impl client::Handler for ContainerHandler {
    type Error = anyhow::Error;

    async fn check_server_key(
        &mut self,
        _server_public_key: &russh::keys::PublicKey,
    ) -> Result<bool, Self::Error> {
        // Accept any server key from containers (internal network)
        Ok(true)
    }
}

/// Shell session forwarder.
///
/// Manages a shell session connection to a container SSH server,
/// forwarding data bidirectionally between the client and container.
pub struct ShellForwarder {
    /// The write half of the channel to the container
    write_half: ChannelWriteHalf<Msg>,

    /// The read half (taken when shell is requested)
    read_half: Option<ChannelReadHalf>,

    /// Channel ID (for debugging)
    channel_id: ChannelId,
}

impl ShellForwarder {
    /// Create a new shell forwarder and connect to the container.
    ///
    /// This establishes an SSH connection to the container, opens a session
    /// channel, and sets up the event forwarding infrastructure.
    pub async fn connect(
        container_ip: &str,
        container_port: u16,
        auth_key: Arc<PrivateKey>,
        username: &str,
    ) -> Result<Self> {
        let config = client::Config {
            inactivity_timeout: Some(std::time::Duration::from_secs(3600)),
            ..Default::default()
        };

        let addr = format!("{}:{}", container_ip, container_port);
        debug!("Connecting to container at {}", addr);

        // Create handler
        let handler = ContainerHandler;

        // Connect to container SSH
        let mut handle = client::connect(Arc::new(config), &addr, handler).await?;

        // Authenticate with public key
        let key_with_alg = PrivateKeyWithHashAlg::new(auth_key, None);
        let auth_result = handle
            .authenticate_publickey(username, key_with_alg)
            .await?;

        if !auth_result.success() {
            return Err(anyhow!("Failed to authenticate to container as {}", username));
        }

        info!("Connected and authenticated to container at {} as {}", addr, username);

        // Open a session channel
        let channel = handle.channel_open_session().await?;
        let channel_id = channel.id();
        debug!("Opened session channel {} on container", channel_id);

        // Split the channel
        let (read_half, write_half) = channel.split();

        Ok(Self {
            write_half,
            read_half: Some(read_half),
            channel_id,
        })
    }

    /// Take the read half of the channel for event forwarding.
    ///
    /// This should be called once to get the read half. The caller should
    /// spawn a task that calls `wait()` on it and forwards events to the client.
    pub fn take_read_half(&mut self) -> Option<ChannelReadHalf> {
        self.read_half.take()
    }

    /// Request a PTY on the container.
    pub async fn request_pty(
        &self,
        term: &str,
        col_width: u32,
        row_height: u32,
        pix_width: u32,
        pix_height: u32,
    ) -> Result<()> {
        self.write_half
            .request_pty(
                true,
                term,
                col_width,
                row_height,
                pix_width,
                pix_height,
                &[],
            )
            .await?;
        debug!("PTY requested on container: {}x{}", col_width, row_height);
        Ok(())
    }

    /// Request a shell on the container.
    pub async fn request_shell(&self) -> Result<()> {
        self.write_half.request_shell(true).await?;
        debug!("Shell requested on container");
        Ok(())
    }

    /// Execute a command on the container.
    pub async fn exec(&self, command: &[u8]) -> Result<()> {
        self.write_half.exec(true, command.to_vec()).await?;
        debug!("Exec requested on container: {:?}", String::from_utf8_lossy(command));
        Ok(())
    }

    /// Request a subsystem on the container (e.g., "sftp").
    pub async fn request_subsystem(&self, name: &str) -> Result<()> {
        self.write_half.request_subsystem(true, name).await?;
        debug!("Subsystem '{}' requested on container", name);
        Ok(())
    }
}

/// Convert ChannelMsg to ContainerEvent.
pub fn channel_msg_to_event(msg: ChannelMsg) -> Option<ContainerEvent> {
    match msg {
        ChannelMsg::Data { data } => {
            Some(ContainerEvent::Data(data.to_vec()))
        }
        ChannelMsg::ExtendedData { ext, data } => {
            Some(ContainerEvent::ExtendedData {
                ext_type: ext,
                data: data.to_vec(),
            })
        }
        ChannelMsg::Eof => {
            Some(ContainerEvent::Eof)
        }
        ChannelMsg::Close => {
            Some(ContainerEvent::Close)
        }
        ChannelMsg::ExitStatus { exit_status } => {
            Some(ContainerEvent::ExitStatus(exit_status))
        }
        ChannelMsg::ExitSignal { signal_name, core_dumped, error_message, lang_tag } => {
            Some(ContainerEvent::ExitSignal {
                signal_name: format!("{:?}", signal_name),
                core_dumped,
                error_message,
                lang_tag,
            })
        }
        ChannelMsg::WindowAdjusted { new_size } => {
            Some(ContainerEvent::WindowAdjusted(new_size))
        }
        _ => {
            debug!("Ignoring container message: {:?}", msg);
            None
        }
    }
}

#[async_trait]
impl ChannelForwarder for ShellForwarder {
    async fn forward_data(&mut self, data: &[u8]) -> Result<()> {
        let mut writer = self.write_half.make_writer();
        writer.write_all(data).await?;
        writer.flush().await?;
        Ok(())
    }

    async fn window_change(
        &mut self,
        col_width: u32,
        row_height: u32,
        pix_width: u32,
        pix_height: u32,
    ) -> Result<()> {
        self.write_half
            .window_change(col_width, row_height, pix_width, pix_height)
            .await?;
        debug!("Window change forwarded: {}x{}", col_width, row_height);
        Ok(())
    }

    async fn eof(&mut self) -> Result<()> {
        self.write_half.eof().await?;
        debug!("EOF forwarded to container");
        Ok(())
    }

    async fn close(&mut self) -> Result<()> {
        self.write_half.close().await?;
        debug!("Channel close forwarded to container");
        Ok(())
    }

    fn container_channel_id(&self) -> ChannelId {
        self.channel_id
    }
}
