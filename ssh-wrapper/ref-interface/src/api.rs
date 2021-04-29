use byteorder::{BigEndian, WriteBytesExt};
use itsdangerous::SignerBuilder;
use libc;
use reqwest;
use serde::{Deserialize, Serialize};
use serde_json;
use std::{
    self, mem,
    net::TcpStream,
    os::unix::prelude::{AsRawFd, IntoRawFd},
};
use std::{ffi::CStr, sync::Mutex};
use std::{io::prelude::*, time::Duration};

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

/* Keep these structs in sync with the C header counterparts */
#[repr(C)]
pub struct RefApiShhAuthenticatedRequest {
    /// The pubkey that was successfully used for authentication.
    pubkey: *const libc::c_char,
    /// The name of the requested task.
    /// E.g., basic_overflow, instance-X, ...
    requested_task: *const libc::c_char,
}

#[repr(C)]
pub struct RefApiShhAuthenticatedResponse {
    /// Whether the request was successfull or failed because of, e.g., networking
    /// errors.
    success: u8,
    /// Whether the requested instance will be served to the user.
    /// If this is false, the fields below must be considered undefined.
    access_granted: u8,
    /// The instance ID this request is associated with.
    instance_id: u64,
    /// Whether the pubkey belongs to an user that is a admin.
    is_admin: u8,
    /// Whether the pubkey belongs to an user that is a an assistant.
    is_grading_assistent: u8,
}

#[derive(Debug, Serialize)]
struct JsonRequest {
    name: String,
    pubkey: String,
}

#[derive(Debug, Deserialize, Default, Clone)]
#[repr(C)]
struct JsonResponse {
    instance_id: u64,
    is_admin: u8,
    is_grading_assistent: u8,
    tcp_forwarding_allowed: u8,
}

lazy_static! {
    static ref INSTANCE_DETAILS: Mutex<Option<JsonResponse>> = Mutex::new(None);
}

#[no_mangle]
pub extern "C" fn ref_get_instance_details(
    username: *const libc::c_char,
    auth_info: *const libc::c_char,
) {
    let pubkey = unsafe { CStr::from_ptr(auth_info) };
    let pubkey = pubkey.to_owned().into_string();
    if pubkey.is_err() {
        dbg!(pubkey.err());
        return;
    }
    let pubkey = pubkey.unwrap();

    let name = unsafe { CStr::from_ptr(username) };
    let name = name.to_owned().into_string();
    if name.is_err() {
        dbg!(name.err());
        return;
    }
    let name = name.unwrap();

    // Build JSON request
    let req = JsonRequest { name, pubkey };
    let req = serde_json::to_string(&req);
    if req.is_err() {
        dbg!(req.err());
        return;
    }

    let client = reqwest::blocking::Client::new();
    let response = client
        .post("http://web:8000/api/ssh-authenticated")
        .body(req.unwrap())
        .send();
    if response.is_err() {
        dbg!(response.err());
        return;
    }

    let response = response.unwrap();
    dbg!(&response);
    let response = response.text();
    if response.is_err() {
        dbg!(response.err());
        return;
    }
    let response = response.unwrap();

    // Parse the response into an JSON object.
    let response = serde_json::from_str::<JsonResponse>(&response);
    if response.is_err() {
        dbg!(response.err());
        return;
    }
    let response = response.unwrap();

    dbg!("Got response:");
    dbg!(&response);

    // Store the response for function called later.
    assert!(INSTANCE_DETAILS.lock().unwrap().is_none());
    *INSTANCE_DETAILS.lock().unwrap() = Some(response);
}

mod message {
    use super::*;

    #[derive(Debug, Clone, Copy, Serialize)]
    #[repr(u8)]
    pub enum MessageId {
        ProxyRequest = 0,
        Success = 50,
        Failed = 51,
    }

    /// The header common to all messages send and received.
    #[derive(Copy, Debug, Serialize, Clone)]
    #[repr(C, packed)]
    pub struct MessageHeader {
        pub msg_type: MessageId,
        pub len: u32,
    }

    #[derive(Debug, Serialize, Clone)]
    pub struct ProxyRequest {
        msg_type: String,
        instance_id: u64,
        dst_ip: String,
        dst_port: String,
    }

    impl ProxyRequest {
        pub fn new(instance_id: u64, dst_ip: String, dst_port: String) -> ProxyRequest {
            ProxyRequest {
                msg_type: "PROXY_REQUEST".to_owned(),
                instance_id,
                dst_ip,
                dst_port,
            }
        }
    }
}

/// Request a proxy connection the the given address and port.
/// On success, a socket fd that is connected to the destination is returned.
/// On error, -1 is returned.
#[no_mangle]
pub extern "C" fn ref_proxy_connect(
    addr: *const libc::c_char,
    port: *const libc::c_char,
) -> libc::c_int {
    let ret = _ref_proxy_connect(addr, port);
    if ret.is_err() {
        dbg!(ret.err());
        return -1;
    }
    ret.unwrap()
}
#[derive(Debug)]
enum RefError {
    IoError(std::io::Error),
    GenericError(String),
}

impl From<&str> for RefError {
    fn from(s: &str) -> Self {
        RefError::GenericError(s.to_owned())
    }
}

impl From<std::io::Error> for RefError {
    fn from(e: std::io::Error) -> Self {
        RefError::IoError(e)
    }
}

fn _ref_proxy_connect(
    addr: *const libc::c_char,
    port: *const libc::c_char,
) -> Result<libc::c_int, RefError> {
    let resp = INSTANCE_DETAILS.lock().unwrap().clone();
    dbg!(&resp);
    let resp = resp.ok_or("INSTANCE_DETAILS should not be empty!")?;

    let addr = unsafe { CStr::from_ptr(addr) };
    let addr = addr.to_owned().into_string().unwrap();
    let port = unsafe { CStr::from_ptr(port) };
    let port = port.to_owned().into_string().unwrap();

    // Create the body.
    let body = message::ProxyRequest::new(resp.instance_id, addr, port);
    let json_body = serde_json::to_string(&body).unwrap();
    let body_bytes = json_body.as_bytes();

    // Buffer used to construct the message we are about to send.
    let mut msg = Vec::new();

    /*
    msg_id: u8,
    len: u32, # The length of the trailing body.
    <JSON Body>
    */
    msg.write_u8(message::MessageId::ProxyRequest as u8)
        .unwrap();
    msg.write_u32::<BigEndian>(body_bytes.len() as u32).unwrap();
    msg.write_all(body_bytes).unwrap();

    // Connect to the proxy server.
    let mut con = TcpStream::connect("ssh-proxy:8001")?;

    // Setup timesouts
    con.set_write_timeout(Some(DEFAULT_TIMEOUT))?;
    con.set_read_timeout(Some(DEFAULT_TIMEOUT))?;

    // Send the request.
    con.write_all(&msg)?;

    // Wait for a success / error response.
    let mut buffer = vec![0u8; mem::size_of::<message::MessageHeader>()];
    con.read_exact(buffer.as_mut_slice())?;

    let header = unsafe { &*(buffer.as_ptr() as *const message::MessageHeader) };
    match header.msg_type as u8 {
        v if v == message::MessageId::Success as u8 => {
            eprintln!("Proxied connection successfully established!")
            // fallthrough
        }
        v if v == message::MessageId::Failed as u8 => {
            return Err(RefError::GenericError(
                "Failed to establish proxied connection!".to_owned(),
            ));
        }
        v => {
            return Err(RefError::GenericError(format!(
                "Received unknown message with id {id}",
                id = v
            )));
        }
    }

    // Transfer the ownership to sshd.
    Ok(con.into_raw_fd())
}
