"""
Update engine for MCSCP.

This module is called from app.py via two functions that app.py already
knows about:

    check_for_git_update(repo_url, local_path, branch, watch_files)
    apply_git_update(local_path, remote_sha, branch, backup_root, exclude, preserve)

Internally it no longer uses `git` at all -- it downloads the branch as a
zipball from GitHub (like the second script you pasted) and copies files
into place itself. That means the host doesn't need git installed and
works even on locked-down hosting.

State (which commit is currently installed, and which repo/branch that
came from) is kept in a small json file, `.update_state.json`, inside the
app's own folder -- NOT in the zip, so it always survives updates.
"""

import os
import io
import json
import time
import shutil
import zipfile
import requests

STATE_FILENAME = ".update_state.json"


# -------------------------
# helpers
# -------------------------
def _parse_owner_repo(repo_url_or_slug):
    """Accepts 'owner/repo', a full https url, or a git@ url -> (owner, repo)."""
    s = (repo_url_or_slug or "").strip()
    if s.endswith(".git"):
        s = s[:-4]
    if s.startswith("git@"):
        # git@github.com:owner/repo
        s = s.split(":", 1)[-1]
    elif s.startswith("http://") or s.startswith("https://"):
        s = s.split("github.com/", 1)[-1]
    parts = s.strip("/").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise ValueError(f"Could not parse owner/repo from '{repo_url_or_slug}'")


def _load_state(local_path):
    state_file = os.path.join(local_path, STATE_FILENAME)
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(local_path, state):
    state_file = os.path.join(local_path, STATE_FILENAME)
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_latest_commit_sha(owner, repo, branch):
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    resp = requests.get(url, headers=_github_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()["sha"]


def _get_changed_files(owner, repo, base_sha, head_sha):
    """List of filenames changed between base_sha and head_sha, or None if unknown."""
    if not base_sha:
        return None
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    resp = requests.get(url, headers=_github_headers(), timeout=15)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return [f["filename"] for f in data.get("files", [])]


def _matches_rule(relative_path, rule):
    rule = rule.replace("\\", "/").strip()
    if not rule:
        return False
    path = relative_path.replace("\\", "/")
    if rule.endswith("/"):
        return path == rule.rstrip("/") or path.startswith(rule)
    return path == rule or path.endswith(f"/{rule}")


def _should_skip(relative_path, preserve, exclude):
    """True if this path must NOT be touched (live data) or was explicitly excluded."""
    for rule in (preserve or []):
        if _matches_rule(relative_path, rule):
            return True
    for rule in (exclude or []):
        if _matches_rule(relative_path, rule):
            return True
    return False


# -------------------------
# public API (same names/signatures app.py already calls)
# -------------------------
def check_for_git_update(repo_url, local_path, branch="main", watch_files=None):
    """
    Look up the latest commit on GitHub for `branch` and compare it against
    what's currently installed. Read-only -- never downloads or modifies
    anything. Returns a dict describing the result.
    """
    watch_files = watch_files or []
    owner, repo = _parse_owner_repo(repo_url)

    state = _load_state(local_path)
    local_sha = state.get("sha")

    remote_sha = _get_latest_commit_sha(owner, repo, branch)

    # Remember which repo/branch we're tracking so apply_git_update can be
    # called later with no arguments and still know what to fetch.
    state["repo_url"] = repo_url
    state["branch"] = branch
    _save_state(local_path, state)

    if not local_sha:
        return {
            "status": "cloned",
            "remote_sha": remote_sha,
            "local_sha": None,
            "important_change": False,
            "matched_watch_files": [],
        }

    if local_sha == remote_sha:
        return {
            "status": "up_to_date",
            "remote_sha": remote_sha,
            "local_sha": local_sha,
            "important_change": False,
            "matched_watch_files": [],
        }

    changed = _get_changed_files(owner, repo, local_sha, remote_sha)
    matched = []
    if changed:
        for wf in watch_files:
            wf_norm = wf.replace("\\", "/").rstrip("/")
            for cf in changed:
                if cf == wf_norm or cf.startswith(wf_norm + "/"):
                    matched.append(cf)

    return {
        "status": "update_available",
        "remote_sha": remote_sha,
        "local_sha": local_sha,
        "important_change": bool(matched),
        "matched_watch_files": matched,
        "changed_files": changed,
    }


def apply_git_update(local_path, remote_sha=None, branch="main", backup_root="backups",
                      exclude=None, preserve=None, repo_url=None):
    """
    Downloads the branch's zipball from GitHub and installs every file
    that isn't in `preserve` (live data, always left alone) or `exclude`
    (one-off skip list for this run). Anything about to be overwritten is
    backed up first. Returns a dict describing the result.
    """
    state = _load_state(local_path)

    if repo_url is None:
        repo_url = state.get("repo_url")
    if not repo_url:
        raise ValueError(
            "apply_git_update: no repo_url on record -- call check_for_git_update first, "
            "or pass repo_url explicitly."
        )

    if branch is None:
        branch = state.get("branch", "main")

    owner, repo = _parse_owner_repo(repo_url)

    if not remote_sha:
        remote_sha = _get_latest_commit_sha(owner, repo, branch)

    zip_url = f"https://github.com/{owner}/{repo}/zipball/{branch}"
    resp = requests.get(zip_url, stream=True, timeout=60)
    if resp.status_code != 200:
        return {"status": "error", "message": f"Failed to download archive (HTTP {resp.status_code})"}

    zip_data = io.BytesIO(resp.content)

    installed = []
    skipped = []
    backup_dir = os.path.join(local_path, backup_root, f"{remote_sha[:12]}-{int(time.time())}") if backup_root else None

    with zipfile.ZipFile(zip_data) as zf:
        names = zf.namelist()
        if not names:
            return {"status": "error", "message": "Downloaded archive was empty"}
        root_dir_in_zip = names[0].split("/")[0]

        for info in zf.infolist():
            if info.filename == f"{root_dir_in_zip}/" or not info.filename.strip():
                continue

            relative_path = info.filename[len(root_dir_in_zip) + 1:]
            if not relative_path:
                continue

            if _should_skip(relative_path, preserve, exclude):
                skipped.append(relative_path)
                continue

            target_path = os.path.join(local_path, relative_path)

            if info.is_dir():
                os.makedirs(target_path, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            if backup_dir and os.path.exists(target_path):
                backup_target = os.path.join(backup_dir, relative_path)
                os.makedirs(os.path.dirname(backup_target), exist_ok=True)
                try:
                    shutil.copy2(target_path, backup_target)
                except Exception:
                    pass

            with zf.open(info) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            installed.append(relative_path)

    state["sha"] = remote_sha
    state["repo_url"] = repo_url
    state["branch"] = branch
    state["last_updated"] = time.time()
    _save_state(local_path, state)

    return {
        "status": "applied",
        "remote_sha": remote_sha,
        "installed_count": len(installed),
        "skipped_count": len(skipped),
        "backup": backup_dir,
    }