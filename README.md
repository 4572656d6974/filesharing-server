# Lean File-Sharing Server

A single-file, dependency-free Python script for sharing files with someone on the same network, using nothing more than a link in their browser.

Start the script, send the printed link to the other person, done. They can download your files and upload theirs. They don't need an app, an account, or any software.

The script is small on purpose: only the Python standard library, one token-protected page, and a set of defensive defaults. It is meant for the everyday case of "my parent / colleague / friend needs to send me a file" on a **trusted network**. It is not a general-purpose file hosting service.

> **Use miniserve instead.** [miniserve](https://github.com/svenstaro/miniserve) is the better tool for almost every use case: it supports HTTPS, passwords, subfolders and folder downloads, needs no Python, and is mature and actively maintained. This script is an inferior alternative that only makes sense in a few narrow cases. See [Alternatives: miniserve](#alternatives-miniserve).

## Features

- **No third-party dependencies.** One `.py` file, Python standard library only. Nothing to `pip install` (but Python itself must be installed, see [Requirements](#requirements)).
- **Easy for non-technical users.** They open a link, pick files, click *Upload*. Downloads are one click.
- **Token-protected.** A random token is generated on every start and is required to list, download, or upload files.
- **Safe defaults.** By default the server listens only on your Wi-Fi adapter's address, not on every network interface.
- **Cross-platform Wi-Fi detection** for Linux, macOS and Windows, with a generic fallback.
- **Multiple files at once**, with a configurable size limit per file.
- **Never overwrites.** Uploading a name that already exists is rejected.

## Requirements

- **Python 3.7 or newer must be installed.** "No dependencies" means no third-party packages, not "nothing to install". This is a real drawback compared with miniserve, which is a single binary that runs without any runtime. (miniserve's own README names the same requirement as a drawback of Python's built-in web server.)
- A modern web browser on the other person's device

## Quick start

```bash
python filesharing_server.py
```

The script prints something like:

```
Open this URL: http://192.168.1.23:8000/?token=Ab3dEf_h
Lean upload server listening on 192.168.1.23:8000, storing files in /home/you/uploads
```

Send the **complete** URL, including `?token=...`, to the other person. They must be connected to the same network (for example, the same Wi-Fi). Press `Ctrl+C` to stop the server. The token is only valid until then; every new start creates a new one.

### What the other person does

1. Open the link in a browser (a phone works fine).
2. To **upload**: click *Choose files*, select one or more files, click *Upload*.
3. To **download**: click a file name in the list.

## Options

| Option | Default | Description |
|---|---|---|
| `PORT` (positional) | `8000` | Port to listen on |
| `--bind ADDRESS` | IP of the Wi-Fi adapter | Address to listen on. `0.0.0.0` listens on all interfaces |
| `--dir FOLDER` | `./uploads` | Folder that is shared and receives uploads. Created if missing |
| `--max-mb N` | `5000` | Maximum size of a single upload in MB |

Examples:

```bash
python filesharing_server.py 9000                       # different port
python filesharing_server.py --dir ~/Share --max-mb 500 # own folder, 500 MB limit
python filesharing_server.py --bind 192.168.1.23        # listen on one specific address
python filesharing_server.py --bind 0.0.0.0             # all interfaces (less restrictive)
```

To offer files for download, put them in the shared folder and reload the page. Only regular files directly in that folder are listed; subfolders, hidden files and symlinks are not.

### Uploading from the command line

The upload endpoint is a plain HTTP `PUT`, so technical users can also use `curl`:

```bash
curl -T report.pdf -H "X-Upload-Token: YOUR_TOKEN" http://192.168.1.23:8000/upload/report.pdf
```

## Security design

- **Token.** A random 8-character URL-safe token (48 bits) is created at startup. It is compared in constant time. Uploads send it in a request header rather than in the URL.
- **Token hygiene.** The token is masked in the server log, and pages are served with `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.
- **File names.** Names are reduced to a plain base name. Path separators, hidden files (leading `.`), control characters and over-long names are rejected, so there is no path traversal and no subfolders.
- **Symlinks** are neither listed nor served.
- **Uploads.** The size limit is checked before the body is read, and exactly the announced number of bytes is read. Incomplete or failed uploads are deleted. Existing files are never overwritten (HTTP 409).
- **Downloads** are always sent as attachments with `X-Content-Type-Options: nosniff` and a `sandbox` Content-Security-Policy, so an uploaded HTML or SVG file is saved instead of being run in the browser.
- **The page itself** uses a strict Content-Security-Policy with a per-request nonce, loads no external resources, and uses no cookies.
- **Upload folder** is created with permissions `0700` (owner only, on systems that support it).

## Limitations (please read)

- **Plain HTTP, no encryption.** The token and the files travel unencrypted. Anyone who can observe traffic on your network can read them. Use this **only on networks you trust**, such as your home network, and **not** on public or shared Wi-Fi.
- **Do not expose it to the internet.** Do not port-forward it and do not run it on a public server.
- **One shared token, no user accounts.** Anyone who has the link can download and upload. Share the link only with the intended person and stop the server when you are done.
- **No delete or rename function**, and no folders.
- **No rate limiting, connection limit or disk quota.** The server is meant for short, attended sessions.
- **File types are not filtered.** Uploaded files can be executables; treat received files like any other download.
- **Windows file name edge cases** (reserved device names such as `NUL`, NTFS alternate data streams such as `name:stream`) are not specially handled.
- This script has not been independently audited. "Reasonably secure" means "sensible defaults for a trusted home or office network", not "safe on hostile networks".

## Alternatives: miniserve

[**miniserve**](https://github.com/svenstaro/miniserve) (MIT licensed, written in Rust) solves the same problem and does it better in almost every respect: more features, HTTPS, real authentication, no Python required, and a long track record. This script is the inferior alternative. If you are unsure which one to pick, pick miniserve.

| | This script | miniserve |
|---|---|---|
| Installation | Needs Python 3.7+ | Single binary, no Python needed; also available via Homebrew, Scoop, pacman, cargo, Docker |
| Authentication | Random token per session, always on | Optional username/password (plain or hashed), or a random URL path (`--random-route`) |
| Default exposure | Listens on the Wi-Fi adapter only; token required | Listens on all interfaces by default; no authentication unless enabled |
| HTTPS | No (plain HTTP) | Yes (TLS with your own certificate and key) |
| Uploads | On by default; existing files never overwritten; size limit | Opt-in (`-u`); duplicate handling configurable; optional deletion and directory creation |
| Subfolders | No | Yes |
| Folder download | No | As tar, tar.gz or zip |
| Extras | None | QR code, search, themes, WebDAV, README rendering, shell completions |
| Size and review | One short Python file | Large, widely used, actively developed codebase |

**The few remaining reasons to use this script:** you already have Python but don't want to download a binary; you want a short file you can read and change yourself; or you like that the defaults are restrictive (token always required, Wi-Fi address only) without needing any flags.

The miniserve facts above come from its [README](https://github.com/svenstaro/miniserve) and manual page. Check there for current details.

## Troubleshooting

- **The other device cannot connect.** Check that both devices are on the same network. Many routers isolate guest Wi-Fi clients from each other. On Windows, allow Python through the firewall for *private* networks when prompted.
- **The printed address is wrong** (VPN, several adapters). Pass the correct address explicitly with `--bind`.
- **`403 Forbidden: missing or invalid token`.** The link is incomplete or from an earlier run. Send the newly printed link.
- **`A file with this name already exists`.** Rename the file or remove the existing one from the shared folder.
- **Port already in use.** Choose another port, for example `python filesharing_server.py 8080`.

## Transparency: AI assistance

- **The script:** a locally run **DeepSeek-R1 (8B)** model was used as an assistant while developing it.
- **This README:** generated with **Claude Sonnet 5.5** (Anthropic). The comparison with miniserve is based on miniserve's public documentation at the time of writing.

The script is a single readable file, so reviewing it before you run it is quick, and you should do so as with any code you download.

## License

Released under the [MIT License](LICENSE).

## Disclaimer

This software is provided "as is", without warranty of any kind. Use it at your own risk.
