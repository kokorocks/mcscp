import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updater


def test_github_headers_without_token(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    headers = updater._github_headers()
    assert headers['Accept'] == 'application/vnd.github+json'
    assert headers['User-Agent'] == 'mcservermanager-updater'
    assert 'Authorization' not in headers


def test_github_headers_with_token(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'abc123')
    monkeypatch.delenv('GH_TOKEN', raising=False)
    headers = updater._github_headers()
    assert headers['Authorization'] == 'Bearer abc123'
    assert headers['User-Agent'] == 'mcservermanager-updater'
