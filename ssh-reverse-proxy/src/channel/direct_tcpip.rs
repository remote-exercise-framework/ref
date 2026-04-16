//! Direct TCP/IP forwarding for local port forwarding (ssh -L).
//!
//! This module handles the forwarding of TCP connections from the client
//! through the SSH proxy to a target host:port via the container SSH.

use crate::channel::forwarder::ChannelForwarder;
use anyhow::{anyhow, Result};
use async_trait::async_trait;
use russh::client::{self, Msg};
use russh::keys::{PrivateKey, PrivateKeyWithHashAlg};
use russh::server::Handle;
use russh::{ChannelId, ChannelMsg, ChannelWriteHalf, CryptoVec};
use std::sync::Arc;
use tokio::io::AsyncWriteExt;
use tracing::{debug, info};

/// Handler for container SSH client events.
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

/// Forwarder for direct TCP/IP connections (local port forwarding).
///
/// This forwarder tunnels TCP connections through the container's SSH server
/// using the `direct-tcpip` channel type, so "localhost" refers to the container.
pub struct DirectTcpIpForwarder {
    /// The write half of the SSH channel to the container
    write_half: ChannelWriteHalf<Msg>,
    /// The container channel ID
    channel_id: ChannelId,
}

impl DirectTcpIpForwarder {
    /// Create a new DirectTcpIpForwarder by connecting through the container SSH.
    ///
    /// Opens a direct-tcpip channel through the container SSH server,
    /// so the target host:port is resolved relative to the container.
    pub async fn connect(
        container_ip: &str,
        container_port: u16,
        auth_key: Arc<PrivateKey>,
        username: &str,
        target_host: &str,
        target_port: u32,
        session_handle: Handle,
        client_channel_id: ChannelId,
    ) -> Result<Self> {
        let config = client::Config {
            inactivity_timeout: Some(std::time::Duration::from_secs(3600)),
            ..Default::default()
        };

        let addr = format!("{}:{}", container_ip, container_port);
        debug!("Connecting to container at {} for direct-tcpip", addr);

        // Connect to container SSH
        let mut handle = client::connect(Arc::new(config), &addr, ContainerHandler).await?;

        // Authenticate with public key
        let key_with_alg = PrivateKeyWithHashAlg::new(auth_key, None);
        let auth_result = handle
            .authenticate_publickey(username, key_with_alg)
            .await?;

        if !auth_result.success() {
            return Err(anyhow!(
                "Failed to authenticate to container as {}",
                username
            ));
        }

        info!(
            "Authenticated to container at {} for direct-tcpip to {}:{}",
            addr, target_host, target_port
        );

        // Open direct-tcpip channel through the container
        let channel = handle
            .channel_open_direct_tcpip(
                target_host,
                target_port,
                "127.0.0.1", // originator address
                0,           // originator port
            )
            .await?;

        let channel_id = channel.id();
        debug!(
            "Opened direct-tcpip channel {} to {}:{} through container",
            channel_id, target_host, target_port
        );

        // Split the channel
        let (read_half, write_half) = channel.split();

        // Spawn a task to forward data from container to client
        Self::spawn_channel_forwarder(read_half, session_handle, client_channel_id);

        Ok(Self {
            write_half,
            channel_id,
        })
    }

    /// Spawn a task to read from the container channel and forward to the client.
    fn spawn_channel_forwarder(
        mut read_half: russh::ChannelReadHalf,
        session_handle: Handle,
        client_channel_id: ChannelId,
    ) {
        tokio::spawn(async move {
            while let Some(msg) = read_half.wait().await {
                let should_break = match msg {
                    ChannelMsg::Data { data } => {
                        session_handle
                            .data(client_channel_id, CryptoVec::from_slice(&data))
                            .await
                            .is_err()
                    }
                    ChannelMsg::Eof => {
                        let _ = session_handle.eof(client_channel_id).await;
                        false
                    }
                    ChannelMsg::Close => {
                        let _ = session_handle.close(client_channel_id).await;
                        true
                    }
                    _ => {
                        debug!("Ignoring message in direct-tcpip channel: {:?}", msg);
                        false
                    }
                };

                if should_break {
                    break;
                }
            }
            debug!("Direct-tcpip channel forwarder ended");
        });
    }
}

#[async_trait]
impl ChannelForwarder for DirectTcpIpForwarder {
    async fn forward_data(&mut self, data: &[u8]) -> Result<()> {
        let mut writer = self.write_half.make_writer();
        writer.write_all(data).await?;
        writer.flush().await?;
        Ok(())
    }

    async fn window_change(
        &mut self,
        _col_width: u32,
        _row_height: u32,
        _pix_width: u32,
        _pix_height: u32,
    ) -> Result<()> {
        // Window changes don't apply to TCP connections
        Ok(())
    }

    async fn eof(&mut self) -> Result<()> {
        self.write_half.eof().await?;
        debug!("Direct-tcpip EOF sent to container");
        Ok(())
    }

    async fn close(&mut self) -> Result<()> {
        self.write_half.close().await?;
        debug!("Direct-tcpip channel closed");
        Ok(())
    }

    fn container_channel_id(&self) -> ChannelId {
        self.channel_id
    }
}
