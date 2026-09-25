#!/usr/bin/env python3
"""Tiny, dependency-free web server for the Pi Zero 2W Home Assistant dashboard.

Serves the static dashboard and a generated ``/config.js`` containing the
Home Assistant URL, access token and tile layout from ``config.json``.

Because the token is handed to the browser, the server binds to 127.0.0.1 by
default so only the kiosk browser running on the Pi itself can read it.
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

    missing = [k for k in REQUIRED_KEYS if not raw.get(k)]
    if missing:
        raise ConfigError(f"missing required config keys: {', '.join(missing)}")

    ha_url = raw["ha_url"].rstrip("/")
    if not ha_url.startswith(("http://", "https://")):
        raise ConfigError("ha_url must start with http:// or https://")

    tiles = raw.get("tiles", [])
    if not isinstance(tiles, list):
        raise ConfigError("tiles must be a list")
    for i, tile in enumerate(tiles):
        if isinstance(tile, str):
            tiles[i] = tile = {"entity": tile}
        if not isinstance(tile, dict) or "." not in str(tile.get("entity", "")):
            raise ConfigError(f"tiles[{i}] needs an 'entity' like 'light.kitchen'")

    return {
        "haUrl": ha_url,
        "token": raw["token"],
        "title": raw.get("title", "Home"),
        "tiles": tiles,
        "theme": raw.get("theme", "auto"),
    }


def make_handler(config_path):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/config.js":
                return self._send_config()
            return super().do_GET()

        def _send_config(self):
            # Re-read on every request so config edits apply on page reload.
            try:
                body = "window.HA_CONFIG = " + json.dumps(load_config(config_path)) + ";\n"
                status = HTTPStatus.OK
            except ConfigError as e:
                body = "window.HA_CONFIG_ERROR = " + json.dumps(str(e)) + ";\n"
                status = HTTPStatus.OK  # let the page render the error
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

        def log_message(self, fmt, *args):
            if os.environ.get("HA_DASH_VERBOSE"):
                super().log_message(fmt, *args)

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

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "warning: listening on a non-loopback address exposes your Home Assistant "
            "token to anyone who can reach this port",
            file=sys.stderr,
        )

    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.config))
    print(f"HA dashboard on http://{args.host}:{args.port}/", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
