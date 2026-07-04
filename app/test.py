import json
import socket
import threading
import time

CONFIG_FILE = "server-config.json"

servers = {}          # loaded config
listeners = {}        # active listener threads
running = set()       # started servers (sid tracking)


# ----------------------------
# YOUR EXISTING FUNCTION
# ----------------------------
def start_server(sid):
    """
    You already have this.
    This function should start the MC server using SID.
    """
    print(f"[START] Server {sid} starting...")


# ----------------------------
# LOAD CONFIG
# ----------------------------
def load_servers():
    global servers
    with open(CONFIG_FILE, "r") as f:
        servers = json.load(f)

    print(f"[LOAD] Loaded {len(servers)} servers")


# ----------------------------
# AUTO-START TRIGGER LISTENER
# ----------------------------
def listen_on_port(sid, port):
    """
    Waits for ANY TCP connection on the port.
    First connection triggers server start.
    """

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(1)

    print(f"[LISTEN] SID {sid} on port {port}")

    while True:
        conn, addr = s.accept()

        print(f"[TRIGGER] Connection on SID {sid} from {addr}")

        if sid not in running:
            running.add(sid)
            start_server(sid)

        conn.close()


# ----------------------------
# START LISTENERS ON BOOT
# ----------------------------
def start_auto_start_listeners():
    for sid, data in servers.items():

        auto_start = data.get("auto-start-on-join", False)
        port = data.get("port")

        if not auto_start:
            continue

        t = threading.Thread(
            target=listen_on_port,
            args=(sid, port),
            daemon=True
        )
        t.start()

        listeners[sid] = t

    print(f"[BOOT] Active auto-start listeners: {len(listeners)}")


# ----------------------------
# INIT FUNCTION (CALL THIS ON STARTUP)
# ----------------------------
def init_server_system():
    load_servers()
    start_auto_start_listeners()


# ----------------------------
# RUN
# ----------------------------
if __name__ == "__main__":
    init_server_system()

    while True:
        time.sleep(1)