from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _wait_and_open_browser(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((HOST, PORT)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.2)


def _uvicorn_kwargs() -> dict:
    # In PyInstaller --noconsole mode, stdout/stderr can be None. Uvicorn's
    # default logging formatter expects a TTY-like stream and can crash when
    # calling isatty() on None.
    return {
        "host": HOST,
        "port": PORT,
        "reload": False,
        "log_level": "info",
        "log_config": None,
    }


def main() -> None:
    root = _project_root()
    os.chdir(root)

    url = f"http://{HOST}:{PORT}"
    threading.Thread(target=_wait_and_open_browser, args=(url,), daemon=True).start()

    uvicorn.run("app.main:app", **_uvicorn_kwargs())


if __name__ == "__main__":
    main()
