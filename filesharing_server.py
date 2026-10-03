#!/usr/bin/env python3
"""
    python filesharing_server.py [PORT] [--bind ADDRESS] [--dir FOLDER] [--max-mb N]
"""

import argparse
import functools
import hmac
import html
import http.server
import os
import re
import secrets
import socket
import string
import struct
import subprocess
import sys
import urllib.parse

CHUNK_SIZE = 64 * 1024

PAGE = string.Template("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Upload</title>
    <style nonce="$nonce">
        body { font-family: sans-serif; margin: 30px; background: #f5f5f5; color: #333; }
        .box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); max-width: 500px; margin-bottom: 20px; }
        input[type=file] { margin-bottom: 10px; display: block; }
        button { background: #0088cc; color: white; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; }
        button:hover { background: #006699; }
        .size { color: #888; }
    </style>
</head>
<body>
    <div class="box">
        <h3>Upload a file</h3>
        <form id="upload-form">
            <input id="file" type="file" multiple required>
            <button type="submit">Upload</button>
        </form>
        <p id="upload-status">Maximum file size: $max_mb MB</p>
    </div>
    <h3>Available files in the folder:</h3>
    <hr>
    <ul>
$file_list
    </ul>
    <script nonce="$nonce">
        const TOKEN = new URLSearchParams(location.search).get("token") || "";
        const MAX_BYTES = $max_bytes;
        const statusEl = document.getElementById("upload-status");

        document.getElementById("upload-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            for (const file of document.getElementById("file").files) {
                if (file.size > MAX_BYTES) {
                    statusEl.textContent = file.name + ": file is too large";
                    return;
                }
                statusEl.textContent = "Uploading " + file.name + " ...";
                try {
                    const response = await fetch("/upload/" + encodeURIComponent(file.name), {
                        method: "PUT",
                        headers: { "X-Upload-Token": TOKEN },
                        body: file,
                    });
                    if (!response.ok) {
                        statusEl.textContent = file.name + ": " + (await response.text());
                        return;
                    }
                } catch {
                    statusEl.textContent = file.name + ": network error";
                    return;
                }
            }
            statusEl.textContent = "WE DID IT!";
            location.reload();
        });
    </script>
</body>
</html>
""")


def clean_name(raw):
    name = os.path.basename(raw.replace("\\", "/"))
    if (
        not name
        or name.startswith(".")
        or len(name.encode("utf-8")) > 255
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        return None
    return name


def human_size(size):
    size = float(size)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def run_command(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def wifi_ip_linux():
    import fcntl

    base = "/sys/class/net"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    for name in names:
        if not (
            os.path.isdir(os.path.join(base, name, "wireless"))
            or os.path.isdir(os.path.join(base, name, "phy80211"))
        ):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
        return socket.inet_ntoa(packed[20:24])
    return None


def wifi_ip_macos():
    ports = run_command("networksetup", "-listallhardwareports")
    for device in re.findall(r"Hardware Port: (?:Wi-Fi|AirPort)\s*\nDevice: (\S+)", ports):
        ip = run_command("ipconfig", "getifaddr", device)
        if ip:
            return ip
    return None


def wifi_ip_windows():
    script = (
        "Get-NetAdapter -Physical "
        "| Where-Object { $_.Status -eq 'Up' -and $_.PhysicalMediaType -like '*802.11*' } "
        "| Get-NetIPAddress -AddressFamily IPv4 "
        "| Select-Object -ExpandProperty IPAddress"
    )
    lines = run_command("powershell", "-NoProfile", "-Command", script).splitlines()
    return lines[0].strip() if lines else None


def lan_ip():
    finders = {"linux": wifi_ip_linux, "darwin": wifi_ip_macos, "win32": wifi_ip_windows}
    finder = finders.get(sys.platform)
    ip = finder() if finder else None
    if ip:
        return ip
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


class UploadHandler(http.server.SimpleHTTPRequestHandler):
    timeout = 30
    server_version = "UploadServer"
    sys_version = ""
    _attachment = None

    def _authorized(self, allow_query):
        supplied = self.headers.get("X-Upload-Token", "")
        if not supplied and allow_query:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            supplied = query.get("token", [""])[0]
        return hmac.compare_digest(supplied.encode(), self.server.token.encode())

    def _reply(self, code, text):
        body = text.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if self._attachment:
            quoted = urllib.parse.quote(self._attachment)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        line = re.sub(r"token=[^&\s]+", "token=***", self.requestline)
        self.log_message('"%s" %s %s', line, code, size)

    def do_GET(self):
        if not self._authorized(allow_query=True):
            return self._reply(403, "Forbidden: missing or invalid token")

        url_path = urllib.parse.urlsplit(self.path).path
        if url_path == "/":
            return self._send_index()

        raw = urllib.parse.unquote(url_path[1:])
        name = clean_name(raw)
        full = os.path.join(self.directory, name) if name else None
        if name != raw or not os.path.isfile(full) or os.path.islink(full):
            return self._reply(404, "Not found")

        self._attachment = name
        super().do_GET()

    def do_HEAD(self):
        self._reply(405, "Method not allowed")

    def _send_index(self):
        token = urllib.parse.quote(self.server.token)
        with os.scandir(self.directory) as it:
            entries = sorted(it, key=lambda e: e.name.lower())

        items = []
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                continue
            try:
                link = urllib.parse.quote(entry.name, errors="strict")
            except UnicodeEncodeError:
                continue
            size = human_size(entry.stat(follow_symlinks=False).st_size)
            items.append(
                f'        <li><a href="/{link}?token={token}">{html.escape(entry.name)}</a> '
                f'<span class="size">({size})</span></li>'
            )
        if not items:
            items.append("        <li>No files yet.</li>")

        nonce = secrets.token_urlsafe(16)
        max_bytes = self.server.max_bytes
        page = PAGE.substitute(
            nonce=nonce,
            max_bytes=max_bytes,
            max_mb=max_bytes // (1024 * 1024),
            file_list="\n".join(items),
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(page)

    def do_PUT(self):
        if not self._authorized(allow_query=False):
            return self._reply(403, "Forbidden: missing or invalid token")

        url_path = urllib.parse.urlsplit(self.path).path
        if not url_path.startswith("/upload/"):
            return self._reply(404, "Not found")

        name = clean_name(urllib.parse.unquote(url_path[len("/upload/"):]))
        if name is None:
            return self._reply(400, "Invalid file name")

        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            return self._reply(411, "Content-Length header required")
        length = int(length)
        if length > self.server.max_bytes:
            return self._reply(413, "File too large")

        try:
            self._save(os.path.join(self.directory, name), length)
        except FileExistsError:
            return self._reply(409, "A file with this name already exists")
        except Exception as exc:
            self.log_error("upload of %r failed: %r", name, exc)
            return self._reply(500, "Upload failed")

        self.log_message("upload saved: %s (%d bytes)", name, length)
        self._reply(201, f"Upload successful: {name}")

    def _save(self, target, length):
        f = open(target, "xb")
        try:
            with f:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ConnectionError("client closed the connection early")
                    f.write(chunk)
                    remaining -= len(chunk)
        except BaseException:
            try:
                os.unlink(target)
            except OSError:
                pass
            raise


def main():
    parser = argparse.ArgumentParser(description="Lean, token-protected upload server")
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument("--bind",
                        help="address to listen on (default: IP address of the Wi-Fi adapter; use 0.0.0.0 for all interfaces)")
    parser.add_argument("--dir", default="uploads", help="upload folder (default: ./uploads)")
    parser.add_argument("--max-mb", type=int, default=5000, help="maximum upload size in MB (default: 5000)")
    args = parser.parse_args()

    bind = args.bind if args.bind is not None else lan_ip()
    upload_dir = os.path.abspath(args.dir)
    os.makedirs(upload_dir, mode=0o700, exist_ok=True)

    token = secrets.token_urlsafe(6)
    handler = functools.partial(UploadHandler, directory=upload_dir)
    server = http.server.ThreadingHTTPServer((bind, args.port), handler)
    server.token = token
    server.max_bytes = args.max_mb * 1024 * 1024

    host = lan_ip() if bind in ("", "0.0.0.0") else bind
    print(f"Open this URL: http://{host}:{args.port}/?token={token}")
    print(f"Lean upload server listening on {bind}:{args.port}, storing files in {upload_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
