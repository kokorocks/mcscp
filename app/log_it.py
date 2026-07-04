import sys
import logging
from pathlib import Path
from datetime import datetime

# -----------------------------
# Configuration
# -----------------------------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

# -----------------------------
# Tee class
# -----------------------------
class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            try:
                stream.write(text)
                stream.flush()
            except Exception:
                pass

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

# -----------------------------
# Initialize once
# -----------------------------
if not globals().get("_LOG_REDIRECT_INITIALIZED", False):
    _LOG_REDIRECT_INITIALIZED = True

    _log_handle = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

    _original_stdout = sys.stdout
    _original_stderr = sys.stderr

    sys.stdout = Tee(_original_stdout, _log_handle)
    sys.stderr = Tee(_original_stderr, _log_handle)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ],
        force=True,
    )

    print(f"[Logger] Logging to {LOG_FILE}")

# Optional helper
def get_log_file():
    return LOG_FILE