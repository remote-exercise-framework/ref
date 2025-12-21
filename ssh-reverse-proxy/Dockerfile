# Build stage - use bookworm for GLIBC compatibility with runtime
FROM rust:bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    clang \
    && rm -rf /var/lib/apt/lists/*

# Copy source
COPY Cargo.toml Cargo.lock* ./
COPY src ./src

# Build release binary
RUN cargo build --release

# Runtime stage
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy binary
COPY --from=builder /build/target/release/ssh-reverse-proxy /usr/local/bin/

# Create directories for keys
RUN mkdir -p /keys

# Default configuration via environment
ENV SSH_LISTEN_ADDR=0.0.0.0:2222
ENV API_BASE_URL=http://web:8000
ENV CONTAINER_SSH_PORT=13370
ENV RUST_LOG=ssh_reverse_proxy=info,russh=warn

# Expose SSH port
EXPOSE 2222

# Run as root to be able to read mounted keys with restricted permissions
# TODO: Improve by copying keys during container startup and changing ownership
CMD ["/usr/local/bin/ssh-reverse-proxy"]
