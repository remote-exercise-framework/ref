#pragma once


/*
Interface between the sshd C codebase and our rust dynamic library (libref_interface, api.rs).
NOTE: Keep these struct in sync with those in api.rs.
*/

typedef struct {
    const char *pubkey;
    const char *requested_task;
} ref_api_ssh_authenticated_request_t;

typedef struct {
    uint8_t success;
    uint8_t access_granted;
    uint64_t instance_id;
    uint8_t is_admin;
    uint8_t is_grading_assistent;

} ref_api_ssh_authenticated_response_t;

extern ref_api_ssh_authenticated_response_t ref_api_ssh_authenticated(ref_api_ssh_authenticated_request_t *auth_info);