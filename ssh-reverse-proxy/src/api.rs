//! Web API client for authentication and provisioning.

use anyhow::{anyhow, Result};
use base64::Engine;
use hmac::{Hmac, Mac};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument};

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
        let signed = self.sign_payload(&payload);

        let url = format!("{}/api/getkeys", self.base_url);
        debug!("Fetching keys from {}", url);

        // Send signed string as JSON (Python: requests.post(..., json=signed_string))
        let response = self
            .client
            .post(&url)
            .json(&signed)
            .send()
            .await?;

        if !response.status().is_success() {
            return Err(anyhow!(
                "API request failed with status: {}",
                response.status()
            ));
        }

        let keys_response: GetKeysResponse = response.json().await?;
        debug!("Received {} keys", keys_response.keys.len());
        Ok(keys_response.keys)
    }

    /// Authenticate an SSH connection and get user permissions.
    #[instrument(skip(self, pubkey))]
    pub async fn ssh_authenticated(
        &self,
        exercise_name: &str,
        pubkey: &str,
    ) -> Result<SshAuthenticatedResponse> {
        let request = SshAuthenticatedRequest {
            name: exercise_name.to_string(),
            pubkey: pubkey.to_string(),
        };

        let url = format!("{}/api/ssh-authenticated", self.base_url);
        debug!("Authenticating user for exercise: {}", exercise_name);

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await?;

        if !response.status().is_success() {
            return Err(anyhow!(
                "SSH authentication failed with status: {}",
                response.status()
            ));
        }

        let auth_response: SshAuthenticatedResponse = response.json().await?;
        debug!(
            "Authenticated: instance_id={}, forwarding={}",
            auth_response.instance_id, auth_response.tcp_forwarding_allowed
        );
        Ok(auth_response)
    }

    /// Provision a container and get connection details.
    #[instrument(skip(self, pubkey))]
    pub async fn provision(
        &self,
        exercise_name: &str,
        pubkey: &str,
    ) -> Result<ProvisionResponse> {
        let request = ProvisionRequest {
            exercise_name: exercise_name.to_string(),
            pubkey: pubkey.to_string(),
        };
        let payload = serde_json::to_string(&request)?;
        let signed = self.sign_payload(&payload);

        let url = format!("{}/api/provision", self.base_url);
        debug!("Provisioning container for exercise: {}", exercise_name);

        // Send signed string as JSON (Python: requests.post(..., json=signed_string))
        let response = self
            .client
            .post(&url)
            .json(&signed)
            .send()
            .await?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(anyhow!(
                "Provisioning failed with status {}: {}",
                status,
                body
            ));
        }

        let provision_response: ProvisionResponse = response.json().await?;
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
}
