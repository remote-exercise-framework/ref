//! Channel forwarder trait and common types.
//!
//! This module defines the abstraction for forwarding SSH channels
//! to containers, supporting shell sessions, X11 forwarding, and
//! port forwarding in a unified way.

use anyhow::Result;
use async_trait::async_trait;
use russh::ChannelId;

/// Events from a container that need to be forwarded to the client.
#[derive(Debug, Clone)]
pub enum ContainerEvent {
    /// Data received from container stdout
    Data(Vec<u8>),

    /// Extended data (e.g., stderr) with type code
    ExtendedData { ext_type: u32, data: Vec<u8> },

    /// End of file on the channel
    Eof,

    /// Channel was closed
    Close,

    /// Process exit status
    ExitStatus(u32),

    /// Process exit signal
    ExitSignal {
        signal_name: String,
        core_dumped: bool,
        error_message: String,
        lang_tag: String,
    },

    /// Window size change acknowledgment (for future use)
    WindowAdjusted(u32),
}

/// Trait for SSH channel forwarders.
///
/// Implementations of this trait handle the forwarding of a specific
/// SSH channel type (shell, exec, X11, direct-tcpip, etc.) to a container.
///
/// The forwarder manages both directions:
/// - Client → Container: via the methods on this trait
/// - Container → Client: via ContainerEvent sent through an mpsc channel
#[async_trait]
pub trait ChannelForwarder: Send + Sync {
    /// Forward data from the client to the container.
    async fn forward_data(&mut self, data: &[u8]) -> Result<()>;

    /// Forward a PTY window change request to the container.
    async fn window_change(
        &mut self,
        col_width: u32,
        row_height: u32,
        pix_width: u32,
        pix_height: u32,
    ) -> Result<()>;

    /// Handle EOF from the client.
    async fn eof(&mut self) -> Result<()>;

    /// Close the channel and clean up resources.
    async fn close(&mut self) -> Result<()>;

    /// Get the container channel ID (for logging/debugging).
    fn container_channel_id(&self) -> ChannelId;
}
