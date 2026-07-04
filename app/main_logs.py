# main_logs.py
#
# Requirements:
#   pip install flask flask-sock
#
# Linux only (uses pty + bash)

import os
import pty
import fcntl
import select
import signal
import struct
import termios
import threading
import subprocess

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    request,
    send_file,
)
from flask_sock import Sock

require_owner = None

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
HTML_FILE = os.path.join(BASE_DIR, "html", "main_logs.html")

os.makedirs(LOG_DIR, exist_ok=True)

main_logs = Blueprint(
    "main_logs",
    __name__,
    url_prefix="/main-logs"
)

sock = Sock()


# ----------------------------------------------------------------------
# Register
# ----------------------------------------------------------------------

def init_main_logs(app, require_owner_func):
    global require_owner

    require_owner = require_owner_func

    app.register_blueprint(main_logs)
    sock.init_app(app)


# ----------------------------------------------------------------------
# HTML
# ----------------------------------------------------------------------

@main_logs.route("/")
def index():
    require_owner()
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


# ----------------------------------------------------------------------
# List Logs
# ----------------------------------------------------------------------

@main_logs.route("/api/logs")
def list_logs():
    require_owner()
    files = []

    for name in sorted(os.listdir(LOG_DIR)):
        path = os.path.join(LOG_DIR, name)

        if os.path.isfile(path):
            files.append({
                "name": name,
                "size": os.path.getsize(path),
                "modified": os.path.getmtime(path)
            })

    return jsonify(files)


# ----------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------

@main_logs.route("/download/<path:name>")
def download(name):
    require_owner()
    path = os.path.abspath(os.path.join(LOG_DIR, name))

    if not path.startswith(LOG_DIR):
        abort(403)

    if not os.path.isfile(path):
        abort(404)

    return send_file(path, as_attachment=True)


# ----------------------------------------------------------------------
# Read Entire Log
# ----------------------------------------------------------------------

@main_logs.route("/api/log/<path:name>")
def read_log(name):
    require_owner()
    path = os.path.abspath(os.path.join(LOG_DIR, name))

    if not path.startswith(LOG_DIR):
        abort(403)

    if not os.path.isfile(path):
        abort(404)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return Response(f.read(), mimetype="text/plain")


# ----------------------------------------------------------------------
# Live Tail
# ----------------------------------------------------------------------

@sock.route("/main-logs/ws/log/<path:name>")
def ws_log(ws, name):
    require_owner()
    path = os.path.abspath(os.path.join(LOG_DIR, name))

    if not path.startswith(LOG_DIR):
        return

    if not os.path.isfile(path):
        return

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()

            if line:
                ws.send(line)
            else:
                try:
                    if ws.receive(timeout=0):
                        pass
                except:
                    pass

                threading.Event().wait(0.15)


# ----------------------------------------------------------------------
# Bash Terminal
# ----------------------------------------------------------------------

@sock.route("/main-logs/ws/terminal")
def terminal(ws):
    require_owner()
    pid, fd = pty.fork()

    if pid == 0:
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"

        os.execvpe(
            "/bin/bash",
            ["/bin/bash", "-i"],
            env
        )

    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    running = True

    def reader():
        nonlocal running

        while running:
            try:
                r, _, _ = select.select([fd], [], [], 0.05)

                if fd in r:
                    data = os.read(fd, 4096)

                    if not data:
                        break

                    ws.send(data.decode(errors="ignore"))

            except:
                break

        running = False

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    try:
        while running:
            msg = ws.receive()

            if msg is None:
                break

            if isinstance(msg, bytes):
                os.write(fd, msg)
                continue

            if msg.startswith("__resize__:"):
                try:
                    _, rows, cols = msg.split(":")
                    rows = int(rows)
                    cols = int(cols)

                    size = struct.pack(
                        "HHHH",
                        rows,
                        cols,
                        0,
                        0
                    )

                    fcntl.ioctl(
                        fd,
                        termios.TIOCSWINSZ,
                        size
                    )

                    os.kill(pid, signal.SIGWINCH)

                except:
                    pass

                continue

            os.write(fd, msg.encode())

    finally:
        running = False

        try:
            os.close(fd)
        except:
            pass

        try:
            os.kill(pid, signal.SIGKILL)
        except:
            pass