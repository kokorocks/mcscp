"""
Update engine for MCSCP.

This module is called from app.py via two functions that app.py already
knows about:

    check_for_git_update(repo_url, local_path, branch, watch_files)
    apply_git_update(local_path, remote_sha, branch, backup_root, exclude, preserve)

Internally it no longer uses `git` at all -- it downloads the branch as a
zipball from GitHub and copies files into place itself. That means the
host doesn't need git installed and works even on locked-down hosting.

State (which commit is currently installed, and which repo/branch that
came from) is kept in a small json file, `.update_state.json`, inside the
app's own folder -- NOT in the zip, so it always survives updates.

Restart behavior
-----------------
`restart_app()` used to call `os.execl(...)`, which doesn't close
inherited file descriptors, so the old listening socket stayed bound
across the exec and the "new" process instantly failed with "Address
already in use" against itself.

That was replaced with: set a shutdown event so background threads stop
promptly, spawn a brand-new process, sleep ~1s, then os._exit(0). That
fixed the exec problem but introduced a *different* race: the new
process gets spawned (and can start its own port check / bind almost
immediately) while the OLD process is still alive and still holding the
port for that entire sleep window. A fixed sleep can't reliably
guarantee the old process is gone by the time the new one tries to
bind -- sometimes it is, sometimes it isn't.

Current fix: instead of spawning the replacement directly, spawn a tiny
detached watcher (a shell one-liner on POSIX, PowerShell on Windows)
that polls for THIS process's PID to actually disappear, and only then
launches the replacement. The current process then exits immediately
(no blind sleep needed). This guarantees the port is actually free
before anything tries to bind it again, instead of hoping a fixed delay
was long enough.

State-file race
----------------
`check_for_git_update` is conceptually read-only, but it used to
re-save the *entire* state dict it had loaded (just to persist
repo_url/branch). The background notifier calls this on its own timer
with no locking. If that overlapped with an apply that had just written
a new "sha" to disk, the notifier's save (using its older in-memory
copy) could clobber that "sha" back to the old value -- so the app would
keep reporting "update available" forever even though the installed
files were already current, while a one-off manual check (not racing
anything) would correctly report "up to date". Fixed with a lock and a
read-modify-write helper that always merges into a freshly-read copy of
the file instead of blind-overwriting it.
"""

import os
import io
import re
import shlex
import signal
import sys
import json
import time
import shutil
import zipfile
import threading
import subprocess
from pathlib import Path
import requests

STATE_FILENAME = ".update_state.json"

# Guards every read-modify-write of the on-disk state file. Without this,
# a background check (which re-saves the whole state dict just to record
# repo_url/branch) can race with an apply's write of a new "sha" and
# clobber it back to the old value -- see module docstring.
_STATE_LOCK = threading.Lock()

UPDATE = False
UPDATING = False
update_state = {"status": "idle", "last": None, "details": None}

# Signaled by restart_app() so all background loops can stop cleanly
# instead of racing the interpreter shutdown / getting killed mid-write.
SHUTDOWN_EVENT = threading.Event()

# How long restart_app() waits for background threads to notice
# SHUTDOWN_EVENT and exit before it moves on to the actual restart.
RESTART_GRACE_SECONDS = float(os.environ.get('RESTART_GRACE_SECONDS', '5'))

# Git-based updater configuration
GIT_REPO_URL = os.environ.get('GIT_REPO_URL') or os.environ.get('GITHUB_REPO') or "kokorocks/mcscp"
GIT_BRANCH = os.environ.get('GIT_BRANCH', 'main')
# Install into the repository root so extracted files land where the app actually runs.
LOCAL_REPO_PATH = Path(__file__).resolve().parents[1]
UPDATE_WATCH_FILES = [f.strip() for f in os.environ.get('UPDATE_WATCH_FILES', 'version.txt').split(',') if f.strip()]
UPDATE_PRESERVE = [p.strip() for p in os.environ.get(
    'UPDATE_PRESERVE',
    'server-config.json,users.json,node-config.json,minecraft_servers,server-imgs,logs,nodes,uploads,temp,.update_state.json,backups'
).split(',') if p.strip()]
UPDATE_CHECK_INTERVAL = int(os.environ.get('UPDATE_CHECK_INTERVAL', '300'))


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
    local_path = Path(local_path).resolve()
    state_file = os.path.join(local_path, STATE_FILENAME)
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    legacy_state_file = os.path.join(local_path, "app", STATE_FILENAME)
    if os.path.exists(legacy_state_file):
        try:
            with open(legacy_state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(local_path, state):
    local_path = Path(local_path).resolve()
    state_file = os.path.join(local_path, STATE_FILENAME)
    try:
        os.makedirs(local_path, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _update_persisted_state(local_path, **updates):
    """
    Atomically merge `updates` into the on-disk state file.

    Always re-reads the file right before writing, under `_STATE_LOCK`,
    so a check running concurrently with an apply (or two checks
    racing each other) can never clobber a field -- like "sha" -- that
    the other one just wrote. This replaces the old pattern of loading
    the whole state dict once and blindly re-saving that same snapshot
    later, which could silently revert a just-applied commit sha back
    to the previous one. See module docstring.
    """
    with _STATE_LOCK:
        state = _load_state(local_path)
        state.update(updates)
        _save_state(local_path, state)
        return state


def _github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcservermanager-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
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


def _to_git_url(repo):
    """Accept either a full git URL or a GitHub 'owner/repo' shorthand."""
    if repo.startswith(('http://', 'https://', 'git@')):
        return repo
    return f"https://github.com/{repo}.git"


def _get_restart_ports():
    ports = []
    try:
        port = int(os.environ.get('PORT', '5000'))
    except Exception:
        port = 5000
    ports.append(port)
    if port == 5000:
        ports.append(5001)
    return ports


def _find_pids_listening_on_port(port):
    pids = set()
    try:
        if sys.platform.startswith("win"):
            output = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                parts = re.split(r"\s+", line.strip())
                if len(parts) < 5 or parts[0].upper() != "TCP":
                    continue
                local = parts[1]
                state = parts[3]
                pid = parts[-1]
                if state != "LISTENING":
                    continue
                if not re.search(fr"[:\.]{port}$", local):
                    continue
                try:
                    pids.add(int(pid))
                except ValueError:
                    continue
        else:
            try:
                output = subprocess.check_output([
                    "lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"
                ], text=True, stderr=subprocess.DEVNULL)
                for line in output.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    try:
                        pids.add(int(parts[1]))
                    except ValueError:
                        continue
            except (FileNotFoundError, subprocess.CalledProcessError):
                try:
                    output = subprocess.check_output(["ss", "-ltnp"], text=True, stderr=subprocess.DEVNULL)
                    for line in output.splitlines():
                        if "LISTEN" not in line:
                            continue
                        if f":{port}" not in line:
                            continue
                        match = re.search(r"pid=(\d+),", line)
                        if match:
                            pids.add(int(match.group(1)))
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
    except Exception:
        pass
    return pids


def _kill_process(pid):
    if pid == os.getpid():
        return False
    try:
        if sys.platform.startswith("win"):
            subprocess.check_call([
                "taskkill", "/F", "/PID", str(pid)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _force_close_port_processes(port):
    """
    Kill any *other* stray process holding `port` -- e.g. an orphan left
    over from a previous bad restart. Deliberately never touches our own
    PID: this process's own listening socket is released by exiting (see
    restart_app / _spawn_restart_watcher), not by killing ourselves here.
    """
    pids = _find_pids_listening_on_port(port)
    killed = []
    for pid in pids:
        if pid == os.getpid():
            continue
        if _kill_process(pid):
            killed.append(pid)
    return killed


def _shutdown_conflicting_port_users():
    for port in _get_restart_ports():
        killed = _force_close_port_processes(port)
        if killed:
            print(f"[UPDATER] Force-closed process(es) on port {port}: {', '.join(map(str, killed))}")


def _spawn_restart_watcher(old_pid, args):
    """
    Launch a tiny detached watcher that waits for `old_pid` (this
    process) to actually exit -- and therefore actually release its
    listening socket(s) -- before starting the replacement process.

    This is the piece that was missing before: spawning the replacement
    immediately and then sleeping a fixed amount before exiting cannot
    guarantee the old process is gone by the time the new one tries to
    bind the port. Polling for the PID to disappear guarantees the
    ordering instead of hoping a delay was long enough.
    """
    if sys.platform.startswith("win"):
        arg_list = ", ".join(f"'{a}'" for a in args[1:])
        cmd = (
            f"while (Get-Process -Id {old_pid} -ErrorAction SilentlyContinue) "
            f"{{ Start-Sleep -Milliseconds 200 }}; "
            f"Start-Process -FilePath '{args[0]}' -ArgumentList {arg_list}"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd],
            close_fds=True,
        )
    else:
        quoted_args = " ".join(shlex.quote(a) for a in args)
        cmd = (
            f"while kill -0 {old_pid} 2>/dev/null; do sleep 0.2; done; "
            f"exec {quoted_args}"
        )
        subprocess.Popen(
            ["/bin/sh", "-c", cmd],
            cwd=os.getcwd(),
            close_fds=True,
            start_new_session=True,
        )


def _set_update_state(**kwargs):
    update_state.update(kwargs)


def restart_app():
    """
    Cleanly restart the process.

    Sets SHUTDOWN_EVENT so any well-behaved background loop stops on its
    own, waits briefly for that, force-closes any *other* stray process
    still squatting on the restart port(s), then hands off to a detached
    watcher that waits for THIS process to actually die before starting
    the replacement -- and finally exits immediately.

    We do NOT spawn the replacement directly and then sleep-then-exit:
    that left a window where both the old and new process were alive
    and fighting over the same port. We also do NOT use os.execl():
    exec() doesn't close inherited file descriptors, so the listening
    socket would stay bound across the exec and the "new" process would
    immediately fail to bind against itself.
    """
    print("Restarting application...")

    # Tell every SHUTDOWN_EVENT-aware background loop to stop.
    SHUTDOWN_EVENT.set()

    # Flush stdout/stderr to ensure logs aren't lost.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    # Give background threads a short window to actually exit instead of
    # a fixed blind sleep -- still bounded by RESTART_GRACE_SECONDS.
    deadline = time.time() + RESTART_GRACE_SECONDS
    for t in threading.enumerate():
        if t is threading.current_thread():
            continue
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        t.join(timeout=remaining)

    # Clean up any *other* stray process left over from a previous bad
    # restart. Never touches our own PID -- our own port is released by
    # this process actually exiting below, not by killing ourselves here.
    _shutdown_conflicting_port_users()

    old_pid = os.getpid()
    args = [sys.executable] + sys.argv

    try:
        _spawn_restart_watcher(old_pid, args)
    except Exception as exc:
        print(f"Failed to spawn restart watcher: {exc}")
        try:
            subprocess.Popen(args, cwd=os.getcwd(), close_fds=True, start_new_session=True)
        except Exception:
            os.execl(sys.executable, sys.executable, *sys.argv)
            return

    # Exit immediately. The watcher is polling for exactly this PID to
    # disappear before it launches the replacement, so there's no need
    # (and no benefit) to sleep here first -- doing so would just widen
    # the window during which nothing is serving the port for no reason.
    os._exit(0)


def run_update_flow(repo=None, branch=None, extra_exclude=None, restart_callback=None,
                    initial_message='Checking for updates', mark_updating=True):
    """Run the full check/apply lifecycle and keep update_state in sync."""
    global UPDATE, UPDATING

    repo = repo or GIT_REPO_URL
    branch = branch or GIT_BRANCH
    extra_exclude = extra_exclude or []

    _set_update_state(status='running', progress=0, message=initial_message)
    info = check_for_git_update(
        _to_git_url(repo),
        LOCAL_REPO_PATH,
        branch=branch,
        watch_files=UPDATE_WATCH_FILES,
    )
    update_state['last'] = info
    update_state['progress'] = 30
    update_state['message'] = 'Checked latest commit'

    if info['status'] == 'up_to_date':
        _set_update_state(status='up_to_date', message='Already up to date', progress=100)
        UPDATE = False
        return info

    if info.get('important_change'):
        update_state['message'] = f"Important files changed: {info.get('matched_watch_files')}"

    update_state['progress'] = 60
    update_state['message'] = 'Installing files' if info['status'] == 'cloned' else 'Applying update'

    if mark_updating:
        UPDATING = True
    try:
        apply_result = apply_git_update(
            LOCAL_REPO_PATH,
            remote_sha=info.get('remote_sha'),
            branch=branch,
            backup_root='backups',
            exclude=extra_exclude,
            preserve=UPDATE_PRESERVE,
        )
        update_state['details'] = apply_result
        update_state['status'] = apply_result.get('status')
        update_state['progress'] = 95 if apply_result.get('status') == 'applied' else update_state.get('progress', 60)
        if apply_result.get('status') == 'applied':
            update_state['message'] = 'Update applied; restarting'
            UPDATE = False
            if restart_callback is not None:
                try:
                    restart_callback()
                except Exception:
                    pass
        return apply_result
    finally:
        if mark_updating:
            UPDATING = False


def start_update_job(repo=None, branch=None, extra_exclude=None, restart_callback=None):
    """Kick off a background update apply job and return a JSON-compatible response."""
    def _runner():
        try:
            run_update_flow(
                repo=repo,
                branch=branch,
                extra_exclude=extra_exclude,
                restart_callback=restart_callback,
                initial_message='Checking for updates',
            )
        except Exception as exc:
            update_state['status'] = 'error'
            update_state['details'] = str(exc)
            update_state['message'] = str(exc)

    threading.Thread(target=_runner, daemon=True).start()
    return {"ok": True, "status": "started"}, 202


def start_manual_update(repo=None, branch=None, extra_exclude=None, restart_callback=None):
    """Start a manual update for the web UI and return the redirect target."""
    repo = repo or GIT_REPO_URL
    if not repo:
        _set_update_state(status='error', message='No repository configured for update', progress=0)
        return '/updating'

    if UPDATING:
        _set_update_state(status='running', message='Update already in progress', progress=update_state.get('progress', 0))
        return '/updating'

    _set_update_state(status='checking', message='Manual update started', progress=5)

    def _runner():
        try:
            run_update_flow(
                repo=repo,
                branch=branch,
                extra_exclude=extra_exclude,
                restart_callback=restart_callback,
                initial_message='Manual update started',
            )
        except Exception as exc:
            update_state.update({'status': 'error', 'message': str(exc), 'details': str(exc), 'progress': 0})

    threading.Thread(target=_runner, daemon=True).start()
    return '/updating'


def start_update_notifier():
    """Background check-only notifier that updates UPDATE based on remote state."""
    def loop():
        global UPDATE
        while not SHUTDOWN_EVENT.is_set():
            try:
                if UPDATING:
                    SHUTDOWN_EVENT.wait(10)
                    continue
                info = check_for_git_update(
                    _to_git_url(GIT_REPO_URL),
                    LOCAL_REPO_PATH,
                    branch=GIT_BRANCH,
                    watch_files=UPDATE_WATCH_FILES,
                )
                update_state['last'] = info
                UPDATE = (info.get('status') in ('update_available', 'cloned'))
            except Exception as exc:
                update_state['check_error'] = str(exc)
            # wait() returns early (and loop re-checks the condition)
            # as soon as SHUTDOWN_EVENT is set, instead of sleeping the
            # full interval regardless.
            SHUTDOWN_EVENT.wait(UPDATE_CHECK_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


def start_update_scheduler():
    """Optionally apply updates automatically when AUTO_UPDATE is enabled."""
    auto = os.environ.get('AUTO_UPDATE', 'false').lower() == 'true'
    if not auto:
        return

    repo = GIT_REPO_URL
    branch = GIT_BRANCH
    if not repo:
        return

    exclude_env = os.environ.get('UPDATE_EXCLUDE', '')
    extra_exclude = [p.strip() for p in exclude_env.split(',') if p.strip()]
    try:
        interval = int(os.environ.get('UPDATE_INTERVAL', '3600'))
    except Exception:
        interval = 3600

    def loop():
        while not SHUTDOWN_EVENT.is_set():
            try:
                global UPDATE, UPDATING
                if UPDATING:
                    SHUTDOWN_EVENT.wait(10)
                    continue

                _set_update_state(status='checking', progress=5, message='Checking for updates')
                info = check_for_git_update(
                    _to_git_url(repo),
                    LOCAL_REPO_PATH,
                    branch=branch,
                    watch_files=UPDATE_WATCH_FILES,
                )
                update_state['last'] = info
                update_state['progress'] = 30
                update_state['message'] = 'Checked latest commit'

                if info['status'] == 'up_to_date':
                    _set_update_state(status='up_to_date', message='Already up to date', progress=100)
                    UPDATE = False
                    SHUTDOWN_EVENT.wait(interval)
                    continue

                UPDATE = True
                if info.get('important_change'):
                    update_state['message'] = f"Important files changed: {info.get('matched_watch_files')}"

                try:
                    UPDATING = True
                    msg = 'Installing files' if info['status'] == 'cloned' else 'Applying update'
                    _set_update_state(status='applying', progress=60, message=msg)
                    res = apply_git_update(
                        LOCAL_REPO_PATH,
                        remote_sha=info.get('remote_sha'),
                        branch=branch,
                        backup_root='backups',
                        exclude=extra_exclude,
                        preserve=UPDATE_PRESERVE,
                    )
                    update_state['details'] = res
                    update_state['status'] = res.get('status')
                    update_state['progress'] = 95 if res.get('status') == 'applied' else update_state.get('progress', 60)
                    if res.get('status') == 'applied':
                        update_state['message'] = 'Update applied; restarting'
                        UPDATE = False
                        try:
                            restart_app()
                        except Exception:
                            pass
                finally:
                    UPDATING = False
            except Exception as exc:
                update_state['status'] = 'error'
                update_state['details'] = str(exc)
            SHUTDOWN_EVENT.wait(interval)

    threading.Thread(target=loop, daemon=True).start()


# -------------------------
# public API (same names/signatures app.py already calls)
# -------------------------
def check_for_git_update(repo_url, local_path, branch="main", watch_files=None):
    """
    Look up the latest commit on GitHub for `branch` and compare it against
    what's currently installed. Read-only -- never downloads or modifies
    anything (other than recording which repo/branch it checked, merged
    in via `_update_persisted_state` so it can't clobber a concurrently
    written "sha"). Returns a dict describing the result.
    """
    watch_files = watch_files or []
    owner, repo = _parse_owner_repo(repo_url)

    with _STATE_LOCK:
        state = _load_state(local_path)
    local_sha = state.get("sha")

    remote_sha = _get_latest_commit_sha(owner, repo, branch)

    # Remember which repo/branch we're tracking so apply_git_update can be
    # called later with no arguments and still know what to fetch. Merged
    # in rather than re-saving the whole dict we loaded above, so this
    # can't race with (and revert) a concurrent apply's "sha" write.
    _update_persisted_state(local_path, repo_url=repo_url, branch=branch)

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
            "sha_match": True,
            "state_file": os.path.join(local_path, STATE_FILENAME),
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
        "sha_match": False,
        "state_file": os.path.join(local_path, STATE_FILENAME),
    }


def apply_git_update(local_path, remote_sha=None, branch="main", backup_root="backups",
                      exclude=None, preserve=None, repo_url=None):
    """
    Downloads the branch's zipball from GitHub and installs every file
    that isn't in `preserve` (live data, always left alone) or `exclude`
    (one-off skip list for this run). Anything about to be overwritten is
    backed up first. Returns a dict describing the result.
    """
    with _STATE_LOCK:
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

    # Merge the new sha/repo_url/branch into a freshly-read copy of the
    # state file (see _update_persisted_state) rather than saving the
    # `state` dict we loaded at the top of this function, which could be
    # stale by now if a check ran concurrently.
    _update_persisted_state(
        local_path,
        sha=remote_sha,
        repo_url=repo_url,
        branch=branch,
        last_updated=time.time(),
    )

    return {
        "status": "applied",
        "remote_sha": remote_sha,
        "installed_count": len(installed),
        "skipped_count": len(skipped),
        "backup": backup_dir,
    }