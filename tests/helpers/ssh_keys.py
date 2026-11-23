"""
Generating SSH keypairs for tests.

Needed because REF treats a public key as unique to one account: a second
registration offering an already-registered key is refused with "Already
registered, please use your password to restore the key." So a test that
exercises the bring-your-own-key path has to mint a key nobody has used,
rather than reusing one from an earlier step.

Uses `cryptography` directly — it is already present as a paramiko
dependency, and its OpenSSH encoding produces exactly the
"ssh-ed25519 AAAA..." form the registration endpoint parses.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


@dataclass(frozen=True)
class SSHKeyPair:
    """An OpenSSH-formatted keypair."""

    public: str
    private: str

    @property
    def algorithm(self) -> str:
        """The key type prefix, e.g. "ssh-ed25519"."""
        return self.public.split()[0]


def generate_ed25519_keypair(comment: str = "ref-test") -> SSHKeyPair:
    """
    Mint a fresh Ed25519 keypair.

    Ed25519 rather than RSA because generation is instant; an RSA key of a
    size worth testing with costs noticeable time per call.
    """
    key = ed25519.Ed25519PrivateKey.generate()

    public = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )

    private = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    return SSHKeyPair(public=f"{public} {comment}", private=private)
