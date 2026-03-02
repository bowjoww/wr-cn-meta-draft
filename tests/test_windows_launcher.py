from __future__ import annotations

import windows_launcher


def test_main_runs_uvicorn_with_safe_log_config(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(windows_launcher, "_project_root", lambda: windows_launcher.Path("."))
    monkeypatch.setattr(windows_launcher.os, "chdir", lambda *_args, **_kwargs: None)

    class _ThreadStub:
        def __init__(self, target, args, daemon):
            captured["thread_target"] = target
            captured["thread_args"] = args
            captured["thread_daemon"] = daemon

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(windows_launcher.threading, "Thread", _ThreadStub)

    def _fake_run(*args, **kwargs):
        captured["uvicorn_args"] = args
        captured["uvicorn_kwargs"] = kwargs

    monkeypatch.setattr(windows_launcher.uvicorn, "run", _fake_run)

    windows_launcher.main()

    assert captured["thread_started"] is True
    assert captured["uvicorn_args"] == ("app.main:app",)
    assert captured["uvicorn_kwargs"]["log_config"] is None
    assert captured["uvicorn_kwargs"]["host"] == "127.0.0.1"
    assert captured["uvicorn_kwargs"]["port"] == 8000
