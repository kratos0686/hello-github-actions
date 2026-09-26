import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


def write_config(data):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return f.name


class LoadConfigTests(unittest.TestCase):
    def test_valid_config(self):
        path = write_config({
            "ha_url": "http://ha.local:8123/",
            "token": "abc",
            "tiles": ["light.kitchen", {"entity": "sensor.temp", "name": "Temp"}],
        })
        cfg = server.load_config(path)
        self.assertEqual(cfg["haUrl"], "http://ha.local:8123")
        self.assertEqual(cfg["title"], "Home")
        self.assertEqual(cfg["tiles"][0], {"entity": "light.kitchen"})
        self.assertEqual(cfg["tiles"][1]["name"], "Temp")

    def test_missing_token(self):
        path = write_config({"ha_url": "http://ha.local:8123"})
        with self.assertRaisesRegex(server.ConfigError, "token"):
            server.load_config(path)

    def test_bad_url_scheme(self):
        path = write_config({"ha_url": "ha.local:8123", "token": "x"})
        with self.assertRaisesRegex(server.ConfigError, "http"):
            server.load_config(path)

    def test_bad_tile(self):
        path = write_config({"ha_url": "http://h", "token": "x", "tiles": [{"name": "no entity"}]})
        with self.assertRaisesRegex(server.ConfigError, r"tiles\[0\]"):
            server.load_config(path)

    def test_wrong_types(self):
        cases = [
            (["not", "an", "object"], "JSON object"),
            ({"ha_url": 8123, "token": "x"}, "ha_url must be a string"),
            ({"ha_url": "http://h", "token": ["x"]}, "token must be a string"),
            ({"ha_url": "http://h", "token": "x", "tiles": [{"entity": 42}]}, r"tiles\[0\]"),
            ({"ha_url": "http://h", "token": "x", "tiles": [7]}, r"tiles\[0\]"),
        ]
        for data, message in cases:
            with self.subTest(data=data):
                with self.assertRaisesRegex(server.ConfigError, message):
                    server.load_config(write_config(data))

    def test_missing_file(self):
        with self.assertRaisesRegex(server.ConfigError, "not found"):
            server.load_config("/nonexistent/config.json")

    def test_example_config_is_valid(self):
        cfg = server.load_config(Path(server.BASE_DIR) / "config.example.json")
        self.assertTrue(cfg["tiles"])


class HandlerTests(unittest.TestCase):
    def serve(self, config_path):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(config_path))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_config_js_and_static(self):
        base = self.serve(write_config({"ha_url": "http://h:8123", "token": "tok"}))
        with urllib.request.urlopen(base + "/config.js") as r:
            body = r.read().decode()
            self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertTrue(body.startswith("window.HA_CONFIG = "))
        self.assertIn('"token": "tok"', body)
        with urllib.request.urlopen(base + "/") as r:
            self.assertIn(b"app.js", r.read())

    def test_config_error_is_reported_to_page(self):
        base = self.serve("/nonexistent/config.json")
        with urllib.request.urlopen(base + "/config.js") as r:
            self.assertIn("HA_CONFIG_ERROR", r.read().decode())


if __name__ == "__main__":
    unittest.main()
