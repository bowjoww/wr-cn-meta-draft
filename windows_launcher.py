from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _wait_and_open_browser(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", 8000)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.2)


def main() -> None:
    root = _project_root()
    os.chdir(root)

    url = "http://127.0.0.1:8000"
    threading.Thread(target=_wait_and_open_browser, args=(url,), daemon=True).start()

    # In PyInstaller --noconsole mode, stdout/stderr can be None. Uvicorn's
    # default logging formatter expects a TTY-like stream and can crash when
    # calling isatty() on None.
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
        log_config=None,
    )


if __name__ == "__main__":
    main()
