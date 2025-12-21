//! Remote port forwarding (ssh -R) implementation.
//!
//! Handles forwarding connections from the container back to the client.

use anyhow::{anyhow, Result};
use russh::client::{self, Session as ClientSession};
use russh::keys::{PrivateKey, PrivateKeyWithHashAlg};
use russh::server::Handle as ServerHandle;
use russh::{Channel, ChannelId, ChannelMsg, CryptoVec};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::io::AsyncWriteExt;
use tracing::{debug, error, info};

/// Tracks active remote port forwards for a connection.
pub struct RemoteForwardManager {
    /// Container SSH connection handle (if any)
    container_handle: Option<russh::client::Handle<ContainerForwardHandler>>,
    /// Active forwards: (address, port) -> bound port
    active_forwards: HashMap<(String, u32), u32>,
    /// Server handle to open channels back to client
    server_handle: ServerHandle,
    /// Container connection info
    container_ip: String,
    container_port: u16,
    auth_key: Arc<PrivateKey>,
    username: String,
}

impl RemoteForwardManager {
    /// Create a new RemoteForwardManager.
    pub fn new(
        server_handle: ServerHandle,
        container_ip: String,
        container_port: u16,
        auth_key: Arc<PrivateKey>,
        username: String,
    ) -> Self {
        Self {
            container_handle: None,
            active_forwards: HashMap::new(),
            server_handle,
            container_ip,
            container_port,
            auth_key,
            username,
        }
    }

    /// Ensure we have a connection to the container.
    async fn ensure_connected(&mut self) -> Result<()> {
        if self.container_handle.is_some() {
            return Ok(());
        }

        let config = client::Config {
            inactivity_timeout: Some(std::time::Duration::from_secs(3600)),
            ..Default::default()
        };

        let addr = format!("{}:{}", self.container_ip, self.container_port);
        debug!("Connecting to container at {} for remote forwarding", addr);

        let handler = ContainerForwardHandler {
            server_handle: self.server_handle.clone(),
        };

        let mut handle = client::connect(Arc::new(config), &addr, handler).await?;

        // Authenticate
        let key_with_alg = PrivateKeyWithHashAlg::new(Arc::clone(&self.auth_key), None);
        let auth_result = handle
            .authenticate_publickey(&self.username, key_with_alg)
            .await?;

        if !auth_result.success() {
            return Err(anyhow!(
                "Failed to authenticate to container as {}",
                self.username
            ));
        }

        info!(
            "Connected to container at {} for remote forwarding",
            addr
        );

        self.container_handle = Some(handle);
        Ok(())
    }

    /// Request remote port forwarding.
    pub async fn request_forward(&mut self, address: &str, port: u32) -> Result<u32> {
        self.ensure_connected().await?;

        let handle = self.container_handle.as_mut().unwrap();

        // Request the forward on the container
        let bound_port = handle.tcpip_forward(address, port).await?;

        info!(
            "Remote forward established: {}:{} -> bound port {}",
            address, port, bound_port
        );

        self.active_forwards
            .insert((address.to_string(), port), bound_port);

        Ok(bound_port)
    }

    /// Cancel remote port forwarding.
    pub async fn cancel_forward(&mut self, address: &str, port: u32) -> Result<()> {
        if let Some(handle) = self.container_handle.as_mut() {
            handle.cancel_tcpip_forward(address, port).await?;
            self.active_forwards.remove(&(address.to_string(), port));
            info!("Remote forward cancelled: {}:{}", address, port);
        }
        Ok(())
    }
}

/// Handler for container SSH client events (for remote forwarding).
struct ContainerForwardHandler {
    server_handle: ServerHandle,
}

impl client::Handler for ContainerForwardHandler {
    type Error = anyhow::Error;

    async fn check_server_key(
        &mut self,
        _server_public_key: &russh::keys::PublicKey,
    ) -> Result<bool, Self::Error> {
        // Accept any server key from containers (internal network)
        Ok(true)
    }

    /// Called when the container opens a forwarded-tcpip channel (connection arrived at forwarded port).
    async fn server_channel_open_forwarded_tcpip(
        &mut self,
        channel: Channel<client::Msg>,
        connected_address: &str,
        connected_port: u32,
        originator_address: &str,
        originator_port: u32,
        _session: &mut ClientSession,
    ) -> Result<(), Self::Error> {
        info!(
            "Container forwarded connection: {}:{} from {}:{}",
            connected_address, connected_port, originator_address, originator_port
        );

        // Open a corresponding forwarded-tcpip channel to the client
        let client_channel = match self
            .server_handle
            .channel_open_forwarded_tcpip(
                connected_address,
                connected_port,
                originator_address,
                originator_port,
            )
            .await
        {
            Ok(ch) => ch,
            Err(e) => {
                error!("Failed to open forwarded-tcpip channel to client: {:?}", e);
                return Err(anyhow!("Failed to open forwarded-tcpip channel: {:?}", e));
            }
        };

        let client_channel_id = client_channel.id();
        debug!(
            "Opened forwarded-tcpip channel {} to client",
            client_channel_id
        );

        // Split the client channel for bidirectional forwarding
        let (client_read, client_write) = client_channel.split();

        // Split the container channel
        let (container_read, container_write) = channel.split();

        // Spawn bidirectional forwarding tasks
        let server_handle = self.server_handle.clone();
        spawn_bidirectional_forwarder(
            container_read,
            container_write,
            client_read,
            client_write,
            server_handle,
            client_channel_id,
        );

        Ok(())
    }
}

/// Spawn bidirectional forwarding between container and client channels.
fn spawn_bidirectional_forwarder(
    mut container_read: russh::ChannelReadHalf,
    mut container_write: russh::ChannelWriteHalf<russh::client::Msg>,
    mut client_read: russh::ChannelReadHalf,
    _client_write: russh::ChannelWriteHalf<russh::server::Msg>,
    server_handle: ServerHandle,
    client_channel_id: ChannelId,
) {
    // Container -> Client
    tokio::spawn(async move {
        while let Some(msg) = container_read.wait().await {
            let should_break = match msg {
                ChannelMsg::Data { data } => {
                    server_handle
                        .data(client_channel_id, CryptoVec::from_slice(&data))
                        .await
                        .is_err()
                }
                ChannelMsg::Eof => {
                    let _ = server_handle.eof(client_channel_id).await;
                    false
                }
                ChannelMsg::Close => {
                    let _ = server_handle.close(client_channel_id).await;
                    true
                }
                _ => false,
            };
            if should_break {
                break;
            }
        }
        debug!("Container->Client forwarder ended");
    });

    // Client -> Container
    tokio::spawn(async move {
        while let Some(msg) = client_read.wait().await {
            let should_break = match msg {
                ChannelMsg::Data { data } => {
                    let mut writer = container_write.make_writer();
                    if writer.write_all(&data).await.is_err() {
                        true
                    } else {
                        writer.flush().await.is_err()
                    }
                }
                ChannelMsg::Eof => {
                    let _ = container_write.eof().await;
                    false
                }
                ChannelMsg::Close => {
                    let _ = container_write.close().await;
                    true
                }
                _ => false,
            };
            if should_break {
                break;
            }
        }
        debug!("Client->Container forwarder ended");
    });
}
