# SSH Proxy Replacement Architecture

This document outlines the architecture for replacing the current patched OpenSSH server with a custom implementation.

## Current Implementation Problems

1. **Patched OpenSSH** - Maintaining a custom fork of OpenSSH is complex and requires tracking upstream security patches
2. **Two-tier proxy** - SOCKS5 proxy in containers adds latency and complexity
3. **Rust/C binding layer** - `ref-interface` library requires FFI bindings between Rust and C (OpenSSH)
4. **Multiple processes** - Connection flow spans `sshd` → `ssh-wrapper.py` → container SSH

## Library Comparison

| Feature | russh (Rust) | AsyncSSH (Python) |
|---------|--------------|-------------------|
| Sessions (shell/exec/subsystem) | ✓ | ✓ |
| Local Port Forwarding (-L) | ✓ direct-tcpip | ✓ |
| Remote Port Forwarding (-R) | ✓ forward-tcpip | ✓ |
| Unix Socket Forwarding | ✓ streamlocal | ✓ |
| SFTP | ✓ | ✓ |
| Agent Forwarding | ✓ | ✓ |
| X11 Forwarding | Not documented | ✓ |
| Dynamic SOCKS | Manual | ✓ built-in |
| Async Framework | tokio | asyncio |
| Performance | High | Good |
| Development Speed | Slower | Faster |
| Type Safety | Strong | Runtime |

### Recommendation

**Rust with russh** is recommended because:
1. The issue explicitly suggests `russh`
2. Existing Rust code in the project (`ref-interface`)
3. Better performance for a network-intensive proxy
4. Strong type safety for security-critical code
5. Single binary deployment

Python with AsyncSSH would be viable for faster prototyping but introduces runtime dependencies.

## Required SSH Features

### Must Have (Current Functionality)
- [x] Shell sessions (interactive PTY)
- [x] Command execution (`ssh host command`)
- [x] SFTP subsystem
- [x] Local port forwarding (`-L`)
- [x] Remote port forwarding (`-R`)
- [x] Public key authentication

### Currently Disabled (May Enable Later)
- [ ] Agent forwarding (`-A`)

### Recently Implemented
- [x] X11 forwarding (`-X`)

### Not Required
- Password authentication (keys only)
- GSSAPI/Kerberos

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     REF SSH Proxy (russh)                        │
│                        Port 2222                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │  SSH Server  │───▶│   Mapper     │───▶│  SSH Client Pool │   │
│  │  (russh)     │    │  (API calls) │    │  (russh client)  │   │
│  └──────────────┘    └──────────────┘    └──────────────────┘   │
│         │                   │                     │              │
│         ▼                   ▼                     ▼              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ Auth Handler │    │  Web API     │    │ Container SSH    │   │
│  │ (pub keys)   │    │  /api/*      │    │ port 13370       │   │
│  └──────────────┘    └──────────────┘    └──────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### 1. SSH Server (Entry Point)
- Accept incoming SSH connections on port 2222
- Handle SSH protocol negotiation
- Authenticate users via public keys (fetched from web API)
- Create channels for sessions, port forwarding, SFTP

#### 2. Mapper (Username + Key → Container)
- Parse connection username (exercise name)
- Query web API to resolve:
  - User identity (from public key)
  - Container IP (from exercise name + user)
  - Permissions (forwarding allowed, root access, etc.)
- Cache container connections for session reuse

#### 3. SSH Client Pool
- Maintain connections to container SSH servers (port 13370)
- Reuse connections for multiple channels from same user
- Handle reconnection on container restart

### Connection Flow

```
1. Client connects: ssh overflow@ref.example.com -p 2222
                          │
                          ▼
2. SSH Proxy receives connection
   ├─ Extract username: "overflow" (exercise name)
   ├─ Client presents public key for auth
   │
3. Auth Handler
   ├─ GET /api/getkeys → fetch all valid public keys
   ├─ Verify client key matches one in list
   ├─ POST /api/ssh-authenticated → get user info + permissions
   │       { "name": "overflow", "pubkey": "ssh-ed25519 ..." }
   │       → { "instance_id": 42, "tcp_forwarding_allowed": true }
   │
4. Mapper
   ├─ POST /api/provision → get container details
   │       { "exercise_name": "overflow", "pubkey": "..." }
   │       → { "ip": "172.20.1.5", "welcome_message": "..." }
   │
5. SSH Client Pool
   ├─ Connect to container SSH at 172.20.1.5:13370
   ├─ Authenticate with pre-shared key (/keys/user_key)
   │
6. Channel Forwarding
   ├─ Client opens channel (session, direct-tcpip, etc.)
   ├─ Proxy opens matching channel to container
   ├─ Bidirectional data relay between channels
```

### Channel Types Mapping

| Client Request | Proxy Behavior |
|---------------|----------------|
| Session (shell) | Forward to container session channel |
| Session (exec) | Forward to container exec channel |
| Session (subsystem:sftp) | Forward to container SFTP subsystem |
| direct-tcpip (local forward) | Connect to target:port via container* |
| tcpip-forward (remote forward) | Listen on proxy, forward to container |

*For local port forwarding, the proxy connects to the target through the container's network namespace, not directly.

## Implementation Details

### Core Types

| Type | Location | Purpose |
|------|----------|---------|
| `SshServer` | `server.rs` | Server factory implementing `russh::server::Server`, manages key cache |
| `SshConnection` | `server.rs` | Per-connection handler implementing `russh::server::Handler` |
| `ConnectionState` | `server.rs` | Session state: exercise_name, pubkey, container_ip, permissions, channels |
| `ChannelContext` | `server.rs` | Per-channel state with forwarder trait object and PTY params |
| `ContainerKeys` | `server.rs` | Loads and caches user_key/root_key for container authentication |
| `ApiClient` | `api.rs` | HTTP client with itsdangerous-compatible HMAC-SHA1 signing |

### Channel Forwarding Architecture

The `ChannelForwarder` trait (`channel/forwarder.rs`) provides a unified interface:

```rust
pub trait ChannelForwarder: Send + Sync {
    async fn forward_data(&mut self, data: &[u8]) -> Result<()>;
    async fn window_change(&mut self, col, row, pix_w, pix_h) -> Result<()>;
    async fn eof(&mut self) -> Result<()>;
    async fn close(&mut self) -> Result<()>;
}
```

Implementations:

| Forwarder | File | Handles |
|-----------|------|---------|
| `ShellForwarder` | `shell.rs` | Shell sessions, exec commands, subsystems (SFTP) |
| `DirectTcpIpForwarder` | `direct_tcpip.rs` | Local port forwarding (`ssh -L`) |
| `RemoteForwardManager` | `remote_forward.rs` | Remote port forwarding (`ssh -R`) |
| `X11ForwardState` | `x11.rs` | X11 auth parameters (protocol, cookie, screen) |

### Bidirectional Data Flow

SSH channels are split into independent read/write halves for concurrent operation:

```
Client → Proxy                      Proxy → Container
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
data() callback                     write_half.write_all()
  └─→ forwarder.forward_data() ───→   └─→ flush()

Container → Client (spawned tokio task)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
read_half.wait()
  └─→ channel_msg_to_event()
        └─→ ContainerEvent::Data
              └─→ session_handle.data()
```

`ContainerEvent` enum translates between russh `ChannelMsg` and client-facing events:
- `Data(Vec<u8>)` - stdout data
- `ExtendedData { ext_type, data }` - stderr
- `Eof` / `Close` - channel lifecycle
- `ExitStatus(u32)` / `ExitSignal { ... }` - process termination

## Implementation Phases

### Phase 1: Basic Proxy (MVP) ✅
**Goal:** Replace current SSH entry server for sessions only

Components:
1. SSH server accepting connections
2. Public key authentication via `/api/getkeys`
3. Username → container IP mapping via `/api/provision`
4. SSH client connection to container
5. Session channel forwarding (shell only)

**Status:** Completed

### Phase 2: Full Session Support ✅
- Command execution (`ssh host command`)
- Environment variables
- SFTP subsystem forwarding
- PTY handling (terminal size, signals)

**Status:** Completed

### Phase 3: Port Forwarding ✅
- Local port forwarding (`-L`)
- Remote port forwarding (`-R`)
- X11 forwarding (`-X`)
- Permission checking via `/api/ssh-authenticated`

**Status:** Completed

### Phase 4: Cleanup & Migration 🔄
- Remove patched OpenSSH
- Remove SOCKS5 proxy from containers
- Update documentation
- Performance testing

**Status:** In progress - E2E tests passing, ready for production testing

## Project Structure

```
ssh-reverse-proxy/
├── Cargo.toml            # Dependencies (russh, tokio, reqwest, etc.)
├── Dockerfile            # Two-stage build (Rust → Debian slim)
└── src/
    ├── main.rs           # Entry point, logging setup, config loading
    ├── config.rs         # TOML file + environment variable configuration
    ├── server.rs         # SSH server (implements russh::server::Handler)
    ├── api.rs            # Web API client with HMAC-SHA1 request signing
    └── channel/
        ├── mod.rs            # Module exports
        ├── forwarder.rs      # ChannelForwarder trait definition
        ├── shell.rs          # Shell, exec, and subsystem (SFTP) forwarding
        ├── direct_tcpip.rs   # Local port forwarding (-L)
        ├── remote_forward.rs # Remote port forwarding (-R)
        └── x11.rs            # X11 forwarding state management
```

Keys are mounted from the host at runtime:
- `/keys/host_key` - Server host key (ed25519)
- `/keys/user_key` - Container auth as non-root user
- `/keys/root_key` - Container auth as root user

## Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| `russh` | 0.55 | SSH server and client implementation |
| `tokio` | 1.x | Async runtime with full features |
| `reqwest` | 0.12 | HTTP client (rustls TLS, no OpenSSL) |
| `serde` / `serde_json` | 1.x | JSON serialization |
| `hmac` / `sha1` / `sha2` | - | itsdangerous-compatible request signing |
| `tracing` | 0.1 | Structured logging |
| `tracing-subscriber` | 0.3 | Log formatting with env-filter |
| `anyhow` / `thiserror` | - | Error handling |
| `async-trait` | 0.1 | Async trait support |
| `futures` | 0.3 | Async utilities |

## Configuration

Configuration can be provided via TOML file or environment variables.

### TOML File

```toml
# config.toml
[server]
listen_addr = "0.0.0.0:2222"
host_key_path = "/keys/host_key"

[api]
base_url = "http://web:8000"
signing_key_env = "SSH_TO_WEB_KEY"

[container]
ssh_port = 13370
keys_dir = "/keys"
connection_timeout_secs = 10
keepalive_interval_secs = 60
```

### Environment Variables

```bash
# Server settings
SSH_LISTEN_ADDR=0.0.0.0:2222
SSH_HOST_KEY_PATH=/keys/host_key

# API settings
API_BASE_URL=http://web:8000
SSH_TO_WEB_KEY=<shared-secret>

# Container settings
CONTAINER_SSH_PORT=13370
CONTAINER_KEYS_DIR=/keys

# Logging (tracing-subscriber)
RUST_LOG=ref_ssh_proxy=info,russh=warn
```

The proxy loads from a config file if passed as argument, otherwise uses environment variables.

## API Endpoints Required

The proxy needs these existing endpoints:

| Endpoint | Purpose | Request | Response |
|----------|---------|---------|----------|
| `/api/getkeys` | Fetch valid public keys | `{"username": "..."}` | `{"keys": [...]}` |
| `/api/ssh-authenticated` | Get user permissions | `{"name": "exercise", "pubkey": "..."}` | `{"instance_id": 42, "tcp_forwarding_allowed": true}` |
| `/api/provision` | Get container details | `{"exercise_name": "...", "pubkey": "..."}` | `{"ip": "...", "welcome_message": "..."}` |

## Security Considerations

1. **Request signing** - All API requests must be signed with `SSH_TO_WEB_KEY`
2. **Host key persistence** - Server host key must persist across restarts
3. **Container key isolation** - Consider per-container keys (currently shared)
4. **Rate limiting** - Limit auth attempts per IP
5. **Audit logging** - Log all connection attempts and forwards

## Deployment

### Docker Build

The Dockerfile uses a two-stage build:

```dockerfile
# Stage 1: Build
FROM rust:bookworm AS builder
WORKDIR /app
COPY . .
RUN cargo build --release

# Stage 2: Runtime
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates
COPY --from=builder /app/target/release/ssh-reverse-proxy /usr/local/bin/
ENTRYPOINT ["ssh-reverse-proxy"]
```

### Docker Compose

```yaml
ssh-proxy-rust:
  build:
    context: ../ssh-reverse-proxy
  environment:
    - SSH_TO_WEB_KEY=${SSH_TO_WEB_KEY}
    - CONTAINER_SSH_PORT=${CONTAINER_SSH_PORT:-13370}
    - API_BASE_URL=http://web:8000
    - RUST_LOG=ref_ssh_proxy=info,russh=warn
  volumes:
    - ./container-keys:/keys:ro
  networks:
    - web-and-ssh
    - ssh-and-host
  ports:
    - "${SSH_PORT:-2222}:2222"
  depends_on:
    - web
```

### Networks

- **web-and-ssh** - Internal network for proxy ↔ web API communication
- **ssh-and-host** - External network for client SSH connections

## Comparison: Before vs After

| Aspect | Old (Patched OpenSSH) | New (Rust Proxy) |
|--------|----------------------|------------------|
| SSH Server | Patched OpenSSH + Rust FFI | Pure russh |
| Languages | C + Rust + Python | Rust only |
| Processes per connection | 3 (sshd → wrapper.py → ssh) | 1 |
| Port forwarding | SOCKS5 proxy in container | Direct via SSH channel |
| Container changes | microsocks required | No changes needed |
| Source files | ~15 (scattered across repos) | 10 (single directory) |
| Dependencies | OpenSSH, libssh, Python | Single Rust binary |
| Build time | Complex multi-stage | Simple cargo build |

## Open Questions

1. **Connection multiplexing**: Should we multiplex multiple users to same container over one SSH connection?
2. **Container key rotation**: Implement per-container keys or keep shared key?
3. **Graceful shutdown**: How to handle in-flight sessions during proxy restart?
4. **Health checks**: How does the proxy report container SSH health?

## TODO: Shallow E2E Tests

The following E2E tests in `tests/e2e/test_rust_ssh_proxy.py` are shallow and should be improved:

### test_10_pty_and_terminal
**Current:** Uses high-level `REFSSHClient.execute()` which doesn't request a PTY with specific dimensions.
**Should:** Use paramiko's `channel.get_pty(term="xterm-256color", width=80, height=24)` and verify:
- `$TERM` is set correctly
- `stty size` returns the requested dimensions (24 rows, 80 cols)

**Blocker:** Low-level PTY requests via paramiko timeout. Investigate if this is a russh issue or test setup problem.

### test_11_window_resize
**Current:** Sends `resize_pty()` without an actual PTY and just verifies the proxy doesn't crash.
**Should:** Allocate PTY, invoke shell, resize to 120x40, and verify `stty size` reflects the new dimensions.

**Blocker:** Same PTY timeout issue as test_10.

### test_19_x11_channel_data_flow
**Current:** Only verifies X11 forwarding request is accepted and checks `$DISPLAY` env var.
**Should:** Test actual X11 channel data flow:
1. Request X11 forwarding with mock cookie
2. Run an X11 application (e.g., `xterm` or mock)
3. Accept the X11 channel opened by the container
4. Verify bidirectional X11 protocol data flows correctly

**Blocker:** paramiko doesn't expose `transport.set_x11_handler()`. May need to use a different library or mock at a lower level.

### Potential Improvements

| Test | Current Coverage | Desired Coverage |
|------|-----------------|------------------|
| PTY allocation | Command execution only | Full PTY with dimensions |
| Window resize | No-crash verification | Actual resize verification |
| X11 forwarding | Request acceptance | Full channel data flow |
| Agent forwarding | Not tested | Forward agent to container |

## Sources

- [russh GitHub](https://github.com/Eugeny/russh) - Rust SSH library
- [AsyncSSH Documentation](https://asyncssh.readthedocs.io/en/latest/) - Python alternative
- [Warpgate](https://github.com/warp-tech/warpgate) - Reference implementation using russh
