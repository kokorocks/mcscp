import os
import requests
import tempfile
import shutil
import hashlib
import zipfile
import tarfile
import time
import logging
from pathlib import Path

logger = logging.getLogger("updater")
logging.basicConfig(level=logging.INFO)


def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_archive(archive_path, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
    elif archive_path.endswith(('.tar.gz', '.tgz', '.tar')):
        with tarfile.open(archive_path, 'r:*') as t:
            t.extractall(dest_dir)
    else:
        # If it's not a recognized archive, just copy it
        shutil.copy(archive_path, dest_dir / Path(archive_path).name)


def check_latest_release(repo, token=None):
    """Return latest release dict from GitHub API for `owner/repo`."""
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    r = requests.get(api, headers=headers, timeout=20)
    # handle 404 (no releases) gracefully
    if r.status_code == 404:
        logger.info(f"No releases found for {repo} (404)")
        return None
    r.raise_for_status()
    return r.json()


def download_asset(url, dest_path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return dest_path


def find_asset_for_release(release, pattern=None):
    assets = release.get('assets', [])
    if not assets:
        return None
    if pattern:
        for a in assets:
            if pattern in a.get('name', ''):
                return a
    # prefer zip or tar.gz
    for a in assets:
        n = a.get('name', '')
        if n.endswith('.zip') or n.endswith('.tar.gz') or n.endswith('.tgz'):
            return a
    return assets[0]


def verify_with_checksum(asset, release, download_path, token=None):
    # Try to find a checksum asset (name + .sha256 or checksums.txt)
    assets = release.get('assets', [])
    checksum_text = None
    for a in assets:
        if a.get('name', '').endswith('.sha256') or 'checksums' in a.get('name',''):
            tmp = tempfile.mktemp()
            download_asset(a.get('browser_download_url'), tmp, token=token)
            with open(tmp, 'r', encoding='utf-8', errors='ignore') as f:
                checksum_text = f.read()
            try:
                os.remove(tmp)
            except Exception:
                pass
            break

    if checksum_text:
        # crude parsing: look for filename or just hex
        h = _sha256_of_file(download_path)
        if h in checksum_text:
            return True, h
        return False, h
    # no checksum available
    return None, _sha256_of_file(download_path)


def check_and_prepare_update(repo, asset_pattern=None, token=None, rollout_percent=100):
    """Check GitHub latest release and download + extract into `updates/<tag>`.

    This function does NOT forcibly replace in-use files. It prepares an extracted
    update in `updates/<tag>/` and returns an object describing what to do next.
    """
    release = check_latest_release(repo, token=token)
    if not release:
        return {"status": "no_release", "repo": repo}
    tag = release.get('tag_name') or release.get('name')
    if not tag:
        tag = str(int(time.time()))

    asset = find_asset_for_release(release, pattern=asset_pattern)
    if not asset:
        raise RuntimeError('No suitable asset found in release')

    updates_dir = Path('updates')
    dest_dir = updates_dir / tag
    if dest_dir.exists():
        return {"status": "already_downloaded", "tag": tag, "path": str(dest_dir)}

    tmpfile = tempfile.mktemp(suffix='-'+asset.get('name','download'))
    download_asset(asset.get('browser_download_url'), tmpfile, token=token)
    verify_result, sha = verify_with_checksum(asset, release, tmpfile, token=token)

    _extract_archive(tmpfile, dest_dir)
    try:
        os.remove(tmpfile)
    except Exception:
        pass

    return {
        "status": "downloaded",
        "tag": tag,
        "path": str(dest_dir),
        "sha256": sha,
        "checksum_verified": verify_result
    }


def apply_update(prepared_path, install_root=None, backup_root='backups', exclude=None):
    """Attempt an atomic-ish swap: backup current install, move new files into place.

    install_root defaults to repository root (parent of this file's parent).
    Returns dict with status and backup path on success, or error details on failure.
    """
    install_root = Path(install_root) if install_root else Path(__file__).resolve().parents[1]
    prepared_path = Path(prepared_path)
    if not prepared_path.exists():
        raise RuntimeError('Prepared update path does not exist')

    timestamp = time.strftime('%Y%m%d-%H%M%S')
    backup_dir = Path(backup_root) / f'backup-{timestamp}'
    backup_dir.mkdir(parents=True, exist_ok=True)
    # normalize exclude list of relative paths/names
    exclude = exclude or []
    exclude_set = set(exclude)
    def is_excluded(path: Path):
        # path relative to install_root
        try:
            rel = path.relative_to(install_root)
        except Exception:
            return False
        parts = (str(rel).replace('\\','/')).split('/')
        # check if any prefix or filename in exclude_set matches
        for i in range(1, len(parts)+1):
            if '/'.join(parts[:i]) in exclude_set:
                return True
        if parts[0] in exclude_set:
            return True
        return False

    try:
        # copy current install to backup
        for item in install_root.iterdir():
            # skip backups and updates folders
            if item.name in (backup_root, 'updates'):
                continue
            if is_excluded(item):
                continue
            dest = backup_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        # copy prepared files into install root (overwriting)
        for item in prepared_path.iterdir():
            dest = install_root / item.name
            if is_excluded(dest):
                # skip overwriting excluded paths
                continue
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        return {"status": "applied", "backup": str(backup_dir)}
    except Exception as e:
        logger.exception('Failed to apply update')
        return {"status": "error", "error": str(e)}
