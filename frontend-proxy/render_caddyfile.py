#!/usr/bin/env python3

"""Render the Caddyfile Jinja2 template from environment variables."""

import os
import sys

import jinja2

OUTPUT = "/etc/caddy/Caddyfile"


def main() -> None:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("/etc/caddy"),
        undefined=jinja2.StrictUndefined,
    )
    template = env.get_template("Caddyfile.prod.j2")

    tls_mode = os.environ.get("TLS_MODE", "off")
    if tls_mode not in ("off", "internal", "acme"):
        print(
            f"error: unknown TLS_MODE '{tls_mode}' (expected off|internal|acme)",
            file=sys.stderr,
        )
        sys.exit(1)

    domain = os.environ.get("DOMAIN", "")
    if tls_mode in ("internal", "acme") and not domain:
        print(f"error: DOMAIN must be set when TLS_MODE={tls_mode}", file=sys.stderr)
        sys.exit(1)

    context = {
        "tls_mode": tls_mode,
        "https_host_port": os.environ.get("HTTPS_HOST_PORT", "8443"),
        "domain": domain,
        "redirect_http_to_https": os.environ.get(
            "REDIRECT_HTTP_TO_HTTPS", "false"
        ).lower()
        == "true",
    }

    with open(OUTPUT, "w") as f:
        f.write(template.render(context))

    print(f"Rendered Caddyfile (tls_mode={tls_mode})")


if __name__ == "__main__":
    main()
