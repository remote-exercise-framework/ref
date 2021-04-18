use libc;
use std::ffi::CStr;
use itsdangerous::SignerBuilder;
use serde_json;
use serde::{Serialize, Deserialize};
use reqwest;

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

#[derive(Debug, Deserialize)]
struct JsonResponse {
    instance_id: u64,
    is_admin: u8,
    is_grading_assistent: u8,
}



#[no_mangle]
/// Entrypoint of our agent.
pub extern "C" fn ref_api_ssh_authenticated(request: *const RefApiShhAuthenticatedRequest) -> RefApiShhAuthenticatedResponse {
    let ret = RefApiShhAuthenticatedResponse {
        success: 0,
        access_granted: 0,
        instance_id: 0,
        is_admin: 0,
        is_grading_assistent: 0,
    };

    let request = unsafe { std::ptr::read(request) };
    let pubkey = unsafe { CStr::from_ptr(request.pubkey) };
    let pubkey = pubkey.to_owned().into_string();
    if pubkey.is_err() {
        dbg!(pubkey.err());
        return ret;
    }
    let pubkey = pubkey.unwrap();

    let name = unsafe { CStr::from_ptr(request.requested_task) };
    let name = name.to_owned().into_string();
    if name.is_err() {
        dbg!(name.err());
        return ret;
    }
    let name = name.unwrap();


    // Build JSON request
    let req = JsonRequest {
        name,
        pubkey,
    };
    let req = serde_json::to_string(&req);
    if req.is_err() {
        dbg!(req.err());
        return ret;
    }

    let client = reqwest::blocking::Client::new();
    let response = client.post("http://web:8000/api/ssh-authenticated").body(req.unwrap()).send();
    if response.is_err() {
        dbg!(response.err());
        return ret;
    }

    let response = response.unwrap();
    dbg!(&response);
    let response = response.text();
    if response.is_err() {
        return ret;
    }
    let response = response.unwrap();

    let response = serde_json::from_str::<JsonResponse>(&response);
    if response.is_err() {
        return ret;
    }

    dbg!("Got response:");
    dbg!(response);

    return ret;

    // RefApiShhAuthenticatedResponse {
        // success: 1,
        // access_granted: 1,
        // instance_id: 1,
        // is_admin: 1,
        // is_grading_assistent: 1
    // }
}
