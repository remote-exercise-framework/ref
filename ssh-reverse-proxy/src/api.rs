//! Web API client for authentication and provisioning.

use anyhow::{anyhow, Result};
use base64::Engine;
use hmac::{Hmac, Mac};
use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};
use tracing::{debug, info, error, instrument};

/// Error kind for API calls that drive the SSH auth path.
///
/// The SSH proxy uses this to decide whether a backend failure should be
/// surfaced to the student as an auth rejection (they did something wrong)
/// or as an operational error (the backend broke and it's not their fault).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApiErrorKind {
    /// HTTP 4xx — the request itself is invalid. Most commonly a key that is
    /// not registered for this exercise, or the exercise name is unknown.
    /// These are treated as genuine auth rejections.
    ClientError,
    /// HTTP 5xx, transport failure, or response decoding failure. The student
    /// cannot resolve these themselves; the proxy accepts auth and delivers
    /// an operational-error message over the channel so they know to
    /// contact staff.
    ServerError,
}

#[derive(Debug, thiserror::Error)]
#[error("{kind:?}: {detail}")]
pub struct ApiError {
    pub kind: ApiErrorKind,
    /// Human-readable detail for logging. Includes the HTTP status and raw
    /// body when available so staff can correlate with web logs.
    pub detail: String,
}

impl ApiError {
    /// Classify an HTTP failure by status code: 4xx → `ClientError`,
    /// else → `ServerError`. Use this for endpoints where a 4xx genuinely
    /// reflects caller input (e.g. a pubkey the backend doesn't recognize).
    fn from_status_unsigned(status: StatusCode, body: &str) -> Self {
        let kind = if status.is_client_error() {
            ApiErrorKind::ClientError
        } else {
            ApiErrorKind::ServerError
        };
        Self {
            kind,
            detail: format!("HTTP {}: {}", status, body),
        }
    }

    /// Any non-2xx is treated as `ServerError`. Use this for HMAC-signed
    /// endpoints (e.g. `/api/provision`), where a 4xx typically means the
    /// signature check on the web side failed — an operational problem
    /// (stale `SSH_TO_WEB_KEY`, clock skew, etc.), not something the
    /// student can resolve.
    fn from_status_signed(status: StatusCode, body: &str) -> Self {
        Self {
            kind: ApiErrorKind::ServerError,
            detail: format!("HTTP {}: {}", status, body),
        }
    }

    fn transport(err: reqwest::Error) -> Self {
        Self {
            kind: ApiErrorKind::ServerError,
            detail: format!("transport error: {}", err),
        }
    }

    fn decode(err: impl std::fmt::Display) -> Self {
        Self {
            kind: ApiErrorKind::ServerError,
            detail: format!("response decode error: {}", err),
        }
    }
}

/// API client for communicating with the REF web server.
#[derive(Clone)]
pub struct ApiClient {
    client: Client,
    base_url: String,
    signing_key: Vec<u8>,
}

/// Response from /api/getkeys
#[derive(Debug, Deserialize)]
pub struct GetKeysResponse {
    pub keys: Vec<String>,
}

/// Response from /api/ssh-authenticated
#[derive(Debug, Deserialize)]
pub struct SshAuthenticatedResponse {
    pub instance_id: i64,
    pub is_admin: i32,
    pub is_grading_assistent: i32,
    pub tcp_forwarding_allowed: i32,
}

/// Response from /api/provision
#[derive(Debug, Deserialize)]
pub struct ProvisionResponse {
    pub ip: String,
    #[serde(default)]
    pub cmd: Option<Vec<String>>,
    #[serde(default)]
    pub welcome_message: Option<String>,
    #[serde(default)]
    pub as_root: bool,
}

/// Request body for /api/getkeys
#[derive(Serialize)]
struct GetKeysRequest {
    username: String,
}

/// Request body for /api/ssh-authenticated
#[derive(Serialize)]
struct SshAuthenticatedRequest {
    name: String,
    pubkey: String,
}

/// Request body for /api/provision
#[derive(Serialize)]
struct ProvisionRequest {
    exercise_name: String,
    pubkey: String,
}

impl ApiClient {
    /// Create a new API client.
    pub fn new(base_url: String, signing_key: Vec<u8>) -> Self {
        Self {
            client: Client::new(),
            base_url,
            signing_key,
        }
    }

    /// Create a new API client from environment configuration.
    pub fn from_env(base_url: String, signing_key_env: &str) -> Result<Self> {
        let signing_key = std::env::var(signing_key_env)
            .map_err(|_| anyhow!("Missing environment variable: {}", signing_key_env))?
            .into_bytes();
        Ok(Self::new(base_url, signing_key))
    }

    /// Sign a payload using itsdangerous Serializer format.
    ///
    /// itsdangerous Serializer uses:
    /// 1. Key derivation (django-concat): SHA1(salt + "signer" + secret_key)
    ///    where salt = "itsdangerous"
    /// 2. Signing: HMAC-SHA1(derived_key, payload)
    /// 3. Format: "payload.base64_signature"
    fn sign_payload(&self, payload: &str) -> String {
        use sha1::{Digest, Sha1};
        type HmacSha1 = Hmac<sha1::Sha1>;

        // Step 1: Derive key using django-concat: SHA1(salt + "signer" + secret_key)
        let mut hasher = Sha1::new();
        hasher.update(b"itsdangerous");  // salt
        hasher.update(b"signer");
        hasher.update(&self.signing_key);
        let derived_key = hasher.finalize();

        // Step 2: Sign payload with derived key using HMAC-SHA1
        let mut mac = HmacSha1::new_from_slice(&derived_key)
            .expect("HMAC can take key of any size");
        mac.update(payload.as_bytes());
        let signature = mac.finalize().into_bytes();

        // Step 3: Base64 URL-safe encode (no padding)
        let encoded_sig = base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode(signature);

        // Step 4: Return payload.signature
        format!("{}.{}", payload, encoded_sig)
    }

    /// Fetch all valid public keys from the API.
    #[instrument(skip(self))]
    pub async fn get_keys(&self) -> Result<Vec<String>> {
        let request = GetKeysRequest {
            username: "NotUsed".to_string(),
        };
        let payload = serde_json::to_string(&request)?;
        info!("[API] get_keys payload: {}", payload);
        let signed = self.sign_payload(&payload);
        info!("[API] get_keys signed (first 100 chars): {}...", &signed[..std::cmp::min(100, signed.len())]);

        let url = format!("{}/api/getkeys", self.base_url);
        info!("[API] Fetching keys from {}", url);

        // Send signed string as JSON (Python: requests.post(..., json=signed_string))
        let response = self
            .client
            .post(&url)
            .json(&signed)
            .send()
            .await?;

        let status = response.status();
        info!("[API] get_keys response status: {}", status);

        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            error!("[API] get_keys failed: status={}, body={}", status, body);
            return Err(anyhow!(
                "API request failed with status: {}",
                status
            ));
        }

        let body_text = response.text().await?;
        info!("[API] get_keys response body (first 500 chars): {}...", &body_text[..std::cmp::min(500, body_text.len())]);

        let keys_response: GetKeysResponse = serde_json::from_str(&body_text)?;
        info!("[API] Received {} keys", keys_response.keys.len());
        for (i, key) in keys_response.keys.iter().enumerate() {
            info!("[API] Key {}: {} chars, first 60: {}...", i, key.len(), &key[..std::cmp::min(60, key.len())]);
        }
        Ok(keys_response.keys)
    }

    /// Authenticate an SSH connection and get user permissions.
    ///
    /// Returns a typed `ApiError` so the SSH layer can distinguish genuine
    /// auth failures (4xx — reject the SSH auth) from operational failures
    /// (5xx/transport/decode — accept auth and show an error message).
    #[instrument(skip(self, pubkey))]
    pub async fn ssh_authenticated(
        &self,
        exercise_name: &str,
        pubkey: &str,
    ) -> std::result::Result<SshAuthenticatedResponse, ApiError> {
        let request = SshAuthenticatedRequest {
            name: exercise_name.to_string(),
            pubkey: pubkey.to_string(),
        };

        let url = format!("{}/api/ssh-authenticated", self.base_url);
        info!("[API] ssh_authenticated: exercise={}, pubkey={}...", exercise_name, &pubkey[..std::cmp::min(40, pubkey.len())]);
        debug!("Authenticating user for exercise: {}", exercise_name);

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(ApiError::transport)?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            let body_escaped = body.replace('\n', "\\n").replace('\r', "\\r");
            error!("[API] ssh_authenticated FAILED: status={}, body={}", status, body_escaped);
            return Err(ApiError::from_status_unsigned(status, &body_escaped));
        }

        let body_text = response.text().await.map_err(ApiError::transport)?;
        info!("[API] ssh_authenticated response: {}", body_text);

        let auth_response: SshAuthenticatedResponse =
            serde_json::from_str(&body_text).map_err(ApiError::decode)?;
        debug!(
            "Authenticated: instance_id={}, forwarding={}",
            auth_response.instance_id, auth_response.tcp_forwarding_allowed
        );
        Ok(auth_response)
    }

    /// Provision a container and get connection details.
    ///
    /// Returns a typed `ApiError` for the same reasons as `ssh_authenticated`.
    #[instrument(skip(self, pubkey))]
    pub async fn provision(
        &self,
        exercise_name: &str,
        pubkey: &str,
    ) -> std::result::Result<ProvisionResponse, ApiError> {
        let request = ProvisionRequest {
            exercise_name: exercise_name.to_string(),
            pubkey: pubkey.to_string(),
        };
        let payload = serde_json::to_string(&request).map_err(ApiError::decode)?;
        let signed = self.sign_payload(&payload);

        let url = format!("{}/api/provision", self.base_url);
        debug!("Provisioning container for exercise: {}", exercise_name);

        let response = self
            .client
            .post(&url)
            .json(&signed)
            .send()
            .await
            .map_err(ApiError::transport)?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            let body_escaped = body.replace('\n', "\\n").replace('\r', "\\r");
            error!("[API] provision FAILED: status={}, body={}", status, body_escaped);
            return Err(ApiError::from_status_signed(status, &body_escaped));
        }

        let body_text = response.text().await.map_err(ApiError::transport)?;
        let provision_response: ProvisionResponse =
            serde_json::from_str(&body_text).map_err(ApiError::decode)?;
        debug!("Provisioned container at IP: {}", provision_response.ip);
        Ok(provision_response)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sign_payload() {
        let client = ApiClient::new(
            "http://test".to_string(),
            b"test_secret".to_vec(),
        );
        let signed = client.sign_payload(r#"{"test": true}"#);
        assert!(signed.contains('.'));
        let parts: Vec<&str> = signed.split('.').collect();
        assert_eq!(parts.len(), 2);
        assert_eq!(parts[0], r#"{"test": true}"#);
        // The signature should be a valid base64 URL-safe string
        assert!(!parts[1].is_empty());
    }

    #[test]
    fn test_sign_payload_deterministic() {
        // itsdangerous signing is deterministic - same input produces same output
        let client = ApiClient::new(
            "http://test".to_string(),
            b"test_secret".to_vec(),
        );
        let signed1 = client.sign_payload(r#"{"username": "test"}"#);
        let signed2 = client.sign_payload(r#"{"username": "test"}"#);
        assert_eq!(signed1, signed2);
    }

    #[test]
    fn unsigned_4xx_is_client_error() {
        let err = ApiError::from_status_unsigned(StatusCode::FORBIDDEN, "nope");
        assert_eq!(err.kind, ApiErrorKind::ClientError);
    }

    #[test]
    fn unsigned_5xx_is_server_error() {
        let err = ApiError::from_status_unsigned(StatusCode::INTERNAL_SERVER_ERROR, "boom");
        assert_eq!(err.kind, ApiErrorKind::ServerError);
    }

    #[test]
    fn signed_4xx_is_server_error() {
        // HMAC validation failures from signed endpoints surface as 4xx but
        // are operational problems (e.g. key rotation / drift), not the
        // student's fault.
        let err = ApiError::from_status_signed(StatusCode::BAD_REQUEST, "bad signature");
        assert_eq!(err.kind, ApiErrorKind::ServerError);
    }

    #[test]
    fn signed_5xx_is_server_error() {
        let err = ApiError::from_status_signed(StatusCode::INTERNAL_SERVER_ERROR, "boom");
        assert_eq!(err.kind, ApiErrorKind::ServerError);
    }

    #[test]
    fn decode_error_is_server_error() {
        let err = ApiError::decode("parse fail");
        assert_eq!(err.kind, ApiErrorKind::ServerError);
    }
}
