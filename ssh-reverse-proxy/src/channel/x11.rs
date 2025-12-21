//! X11 forwarding implementation.
//!
//! Handles X11 display forwarding from container to client.

use anyhow::Result;
use russh::server::Handle as ServerHandle;
use russh::{ChannelId, ChannelMsg, CryptoVec};
use tokio::io::AsyncWriteExt;
use tracing::{debug, info};

/// X11 forwarding state for a session channel.
#[derive(Clone)]
pub struct X11ForwardState {
    /// Whether single connection mode is enabled
    pub single_connection: bool,
    /// X11 authentication protocol (e.g., "MIT-MAGIC-COOKIE-1")
    pub auth_protocol: String,
    /// X11 authentication cookie (hex string)
    pub auth_cookie: String,
    /// X11 screen number
    pub screen_number: u32,
}

impl X11ForwardState {
    pub fn new(
        single_connection: bool,
        auth_protocol: &str,
        auth_cookie: &str,
        screen_number: u32,
    ) -> Self {
        Self {
            single_connection,
            auth_protocol: auth_protocol.to_string(),
            auth_cookie: auth_cookie.to_string(),
            screen_number,
        }
    }
}

/// Handle an incoming X11 channel from the container.
///
/// Opens a corresponding X11 channel to the client and forwards data bidirectionally.
pub async fn handle_x11_channel(
    container_channel: russh::Channel<russh::client::Msg>,
    originator_address: &str,
    originator_port: u32,
    server_handle: ServerHandle,
) -> Result<()> {
    info!(
        "Container opened X11 channel from {}:{}",
        originator_address, originator_port
    );

    // Open X11 channel to the client
    let client_channel = server_handle
        .channel_open_x11(originator_address, originator_port)
        .await
        .map_err(|e| anyhow::anyhow!("Failed to open X11 channel to client: {:?}", e))?;

    let client_channel_id = client_channel.id();
    debug!("Opened X11 channel {} to client", client_channel_id);

    // Split channels for bidirectional forwarding
    let (container_read, container_write) = container_channel.split();
    let (client_read, client_write) = client_channel.split();

    // Spawn bidirectional forwarding
    spawn_x11_forwarder(
        container_read,
        container_write,
        client_read,
        client_write,
        server_handle,
        client_channel_id,
    );

    Ok(())
}

/// Spawn bidirectional X11 forwarding between container and client.
fn spawn_x11_forwarder(
    mut container_read: russh::ChannelReadHalf,
    mut container_write: russh::ChannelWriteHalf<russh::client::Msg>,
    mut client_read: russh::ChannelReadHalf,
    _client_write: russh::ChannelWriteHalf<russh::server::Msg>,
    server_handle: ServerHandle,
    client_channel_id: ChannelId,
) {
    // Container -> Client (X11 data from app to display)
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
        debug!("X11 Container->Client forwarder ended");
    });

    // Client -> Container (X11 events from display to app)
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
        debug!("X11 Client->Container forwarder ended");
    });
}
