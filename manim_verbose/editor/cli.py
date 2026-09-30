"""
manimgl-editor: edit a scene file in the browser.

    manimgl-editor [FILE] [--port 8765] [--host 127.0.0.1] [--no-browser] [--output-dir DIR]

Starts the editor's server for FILE (video.yaml in the current folder if none is given) and
opens it in the browser. A FILE which doesn't exist yet is created from a starter document.
When no port is given and 8765 is taken, say by the editor already running for another file,
the next free port is used.

The server listens only on this computer unless told otherwise with --host. Anyone who can
reach it can read and change the scene file and make this computer render, so it says so,
loudly, when it listens anywhere else.
"""
from __future__ import annotations

import argparse
import ipaddress
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8765
PORTS_TO_TRY = 20


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.file).expanduser().resolve()
    if path.suffix.lower() not in (".yaml", ".yml", ".json"):
        print(f"manimgl-editor: {args.file}: a scene file's name ends in .yaml, .yml or .json", file=sys.stderr)
        return 2
    if path.is_dir():
        print(f"manimgl-editor: {args.file} is a folder; give the scene file inside it", file=sys.stderr)
        return 2
    if not path.parent.is_dir():
        print(f"manimgl-editor: the folder {path.parent} doesn't exist", file=sys.stderr)
        return 2
    if not path.exists():
        from manim_verbose.editor.starter import write_starter
        write_starter(path)
        print(f"Created {path} to start from")

    local = is_local_host(args.host)
    if not local:
        print(non_local_warning(args.host, path), file=sys.stderr)
    try:
        sock = bind(args.host, args.port)
    except OSError as err:
        print(f"manimgl-editor: couldn't listen on {args.host}:{args.port or DEFAULT_PORT}: {err.strerror or err}",
              file=sys.stderr)
        return 1
    port = sock.getsockname()[1]

    import uvicorn
    from manim_verbose.editor.server import LOCAL_HOSTS, create_app
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    app = create_app(path, output_dir=args.output_dir, allowed_hosts=LOCAL_HOSTS if local else None)
    url = f"http://{url_host(args.host)}:{port}/"
    print(f"Editing {path}\nThe editor is at {url}  (press Ctrl+C to stop it)", flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()
    config = uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=5)
    try:
        uvicorn.Server(config).run(sockets=[sock])
    except KeyboardInterrupt:
        # uvicorn shuts down cleanly on Ctrl+C, then raises it again for whoever called it
        pass
    print("Stopped the editor", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manimgl-editor", description="Edit a manim scene file in the browser")
    parser.add_argument("file", nargs="?", default="video.yaml",
                        help="The scene file (.yaml or .json); created if it doesn't exist. Default: video.yaml")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Port to listen on. Default: {DEFAULT_PORT}, or the next free one")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Address to listen on. Default: 127.0.0.1, which only this computer can reach")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the editor in a browser")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Folder for rendered frames, clips and exports. Default: one in your user cache")
    return parser


def is_local_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def non_local_warning(host: str, path: Path) -> str:
    rule = "!" * 78
    return (
        f"{rule}\n"
        f"  WARNING: listening on {host}, not just on this computer.\n"
        f"  Anyone who can reach this address can read and overwrite {path.name},\n"
        f"  and make this computer render for as long as they like. There is no login.\n"
        f"  Only do this on a network you trust; leave out --host to keep it private.\n"
        f"{rule}"
    )


def bind(host: str, port: int | None) -> socket.socket:
    """A listening socket on `port`, or on the first free port from DEFAULT_PORT when none is given."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    candidates = [port] if port is not None else range(DEFAULT_PORT, DEFAULT_PORT + PORTS_TO_TRY)
    error: OSError | None = None
    for candidate in candidates:
        sock = socket.socket(family, socket.SOCK_STREAM)
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host.strip("[]"), candidate))
            sock.listen(128)
            sock.set_inheritable(True)
            return sock
        except OSError as err:
            sock.close()
            error = err
    assert error is not None
    raise error


def url_host(host: str) -> str:
    if host in ("0.0.0.0", "::", ""):
        return "127.0.0.1"
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def open_when_ready(url: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    webbrowser.open(url)


if __name__ == "__main__":
    sys.exit(main())
