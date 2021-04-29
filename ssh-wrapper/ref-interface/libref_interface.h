#pragma once

#include <stdint.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netdb.h>

/*
Interface between the sshd C codebase and our rust dynamic library (libref_interface, api.rs).
NOTE: Keep these struct in sync with those in api.rs.
*/

extern void ref_get_instance_details(const char *username, const char *pubkey);
extern int ref_proxy_connect(const char *addr, const char *port);