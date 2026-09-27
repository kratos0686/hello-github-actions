#!/usr/bin/env python3
"""Tiny, dependency-free web server for the Pi Zero 2W Home Assistant dashboard.

Serves the static dashboard and ``/config.json`` containing the Home Assistant
URL, access token and tile layout from the config file.

Because the token is handed to the browser, the server binds to 127.0.0.1 by
default so only the kiosk browser running on the Pi itself can read it. The
config is served as JSON (not script) and only to same-origin requests, so other
web pages open in that browser cannot load it cross-origin.
"""

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_CONFIG = BASE_DIR / "config.json"

REQUIRED_KEYS = ("ha_url", "token")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
VERBOSE = bool(os.environ.get("HA_DASH_VERBOSE"))


class ConfigError(Exception):
    pass


def load_config(path):
    """Load and validate the dashboard config, returning the client-side dict."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path} (copy config.example.json)")
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"unable to read config {path}: {e}")

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")

    missing = [k for k in REQUIRED_KEYS if not raw.get(k)]
    if missing:
        raise ConfigError(f"missing required config keys: {', '.join(missing)}")
    for key in REQUIRED_KEYS:
        if not isinstance(raw[key], str):
            raise ConfigError(f"{key} must be a string")

    ha_url = raw["ha_url"].rstrip("/")
    if not ha_url.startswith(("http://", "https://")):
        raise ConfigError("ha_url must start with http:// or https://")

    tiles = raw.get("tiles", [])
    if not isinstance(tiles, list):
        raise ConfigError("tiles must be a list")
    for i, tile in enumerate(tiles):
        if isinstance(tile, str):
            tiles[i] = tile = {"entity": tile}
        entity = tile.get("entity") if isinstance(tile, dict) else None
        if not isinstance(entity, str) or "." not in entity:
            raise ConfigError(f"tiles[{i}] needs an 'entity' like 'light.kitchen'")

    return {
        "haUrl": ha_url,
        "token": raw["token"],
        "title": raw.get("title", "Home"),
        "tiles": tiles,
        "theme": raw.get("theme", "auto"),
    }


def _host_name(host_header):
    """Hostname part of a Host header ("[::1]:8080" -> "::1")."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def make_handler(config_path, loopback_only=True):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/config.json":
                return self._send_config()
            return super().do_GET()

        def _config_request_allowed(self):
            # Browsers label cross-origin subresource requests; refuse them so a
            # page from another site can't pull the token.
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return False
            # A DNS-rebinding page would reach us under its own hostname.
            if loopback_only and _host_name(self.headers.get("Host")) not in LOOPBACK_HOSTS:
                return False
            return True

        def _send_config(self):
            if not self._config_request_allowed():
                return self.send_error(HTTPStatus.FORBIDDEN)
            # Re-read on every request so config edits apply on page reload.
            try:
                body = load_config(config_path)
            except ConfigError as e:
                body = {"error": str(e)}  # 200 so the page can render the error
            data = json.dumps(body).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

        def log_request(self, code="-", size="-"):
            # Errors always reach the journal; successful requests only when verbose.
            if VERBOSE or (isinstance(code, int) and code >= 400):
                super().log_request(code, size)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("HA_DASH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HA_DASH_PORT", "8080")))
    parser.add_argument("--config", default=os.environ.get("HA_DASH_CONFIG", str(DEFAULT_CONFIG)))
    args = parser.parse_args(argv)

    try:
        load_config(args.config)
    except ConfigError as e:
        print(f"warning: {e}", file=sys.stderr)

    loopback_only = args.host in LOOPBACK_HOSTS
    if not loopback_only:
        print(
            "warning: listening on a non-loopback address exposes your Home Assistant "
            "token to anyone who can reach this port",
            file=sys.stderr,
        )

    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.config, loopback_only))
    print(f"HA dashboard on http://{args.host}:{args.port}/", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
