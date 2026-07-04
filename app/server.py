from flask import Flask, request, jsonify, session, redirect, abort, send_file, url_for
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid
import subprocess
import threading
import os, re, traceback
import time
import json
import create
from fs import register_file_manager
import log_it
import shutil
from functools import wraps
import base64, socket
from pathlib import Path
from main_logs import init_main_logs




listeners = {}
server_log={}
player_counts = {}
idle_since = {}
listener_sockets = {}
listener_stop_flags = {}
server_started = {}
UPDATE=True
UPDATING = False#True
import updater

update_state = {"status": "idle", "last": None, "details": None}

app = Flask(__name__)

# --- auth decorator defined early so routes can use it safely
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# Ensure default config files and important folders exist so the app can run
def ensure_config_files_and_dirs():
    defaults = {
        'server-config.json': {},
        'node-config.json': {},
        'users.json': {}
    }
    for fname, default in defaults.items():
        try:
            if not os.path.exists(fname):
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(default, f, indent=4)
        except Exception:
            pass

    # ensure common directories exist and are safe to ignore in production
    for d in ('minecraft_servers', 'server-imgs', 'logs', 'nodes', 'uploads', 'temp'):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


# Call ensure at startup
ensure_config_files_and_dirs()

@app.before_request
def maintenance_mode():
    if not UPDATING:
        return

    # Allow updater endpoints
    allowed = {
        "update_status",
        "update_ws",
        "trigger_update",
        "update_state",
        "update",
        "static",
        "updating",
    }

    if request.endpoint in allowed:
        return

    # API requests
    if request.path.startswith("/api/"):
        return jsonify({
            "error": "updating",
            "message": "Server is updating."
        }), 503

    # Browser requests
    return redirect("/updating")


@app.route('/api/update/check')
@login_required
def update_status():
    """Check GitHub latest release and prepare download (does not force install)."""
    # repo can come from environment or caller
    repo = request.args.get('repo') or os.environ.get('GITHUB_REPO') or "kokorocks/mcscp"
    # token intentionally not used for unauthenticated requests per user's request
    if not repo:
        return jsonify({"error": "repo required (owner/repo)"}), 400
    try:
        info = updater.check_and_prepare_update(repo)
        return jsonify({"ok": True, "update": info})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/api/update', methods=['POST'])
@login_required
def trigger_update():
    # Only owner may trigger a full apply
    if session.get('role') != 'owner':
        abort(403)

    data = request.json or {}
    repo = data.get('repo') or os.environ.get('GITHUB_REPO') or "kokorocks/mcscp"
    pattern = data.get('pattern')
    rollout = int(data.get('rollout', 100))
    exclude = data.get('exclude', [])  # list of file/dir names or relative paths to skip

    if not repo:
        return jsonify({"error": "repo required (owner/repo)"}), 400

    def _run():
        global UPDATING
        try:
            UPDATING = True
            update_state.update({
                'status': 'running',
                'progress': 0,
                'message': 'Starting update',
            })
            info = updater.check_and_prepare_update(repo, asset_pattern=pattern, rollout_percent=rollout)
            update_state['last'] = info
            update_state['progress'] = 30
            update_state['message'] = 'Checked latest release'
            if info.get('status') == 'downloaded':
                update_state['progress'] = 60
                update_state['message'] = 'Preparing to apply update'
                try:
                    update_state['message'] = 'Applying update'
                    apply_result = updater.apply_update(info['path'], exclude=exclude)
                    update_state['details'] = apply_result
                    update_state['status'] = apply_result.get('status')
                    update_state['progress'] = 95 if apply_result.get('status') == 'applied' else 0
                    if apply_result.get('status') == 'applied':
                        update_state['message'] = 'Update applied; restarting'
                        # best-effort restart of the current process to pick up new code
                        try:
                            import sys
                            os.execv(sys.executable, [sys.executable] + sys.argv)
                        except Exception:
                            pass
                except Exception as e:
                    update_state['status'] = 'error'
                    update_state['details'] = str(e)
                    update_state['message'] = 'Failed to apply update: ' + str(e)
        except Exception as e:
            update_state['status'] = 'error'
            update_state['details'] = str(e)
            update_state['message'] = str(e)
        finally:
            UPDATING = False
            update_state['progress'] = 100 if update_state.get('status') == 'applied' else update_state.get('progress', 0)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "status": "started"}), 202

def require_owner():

    if "user" not in session:
        abort(401)

    if session.get("role") != "owner":
        abort(403)

init_main_logs(app, require_owner_func=require_owner)

# Crucial for sessions to work. In production, change this to a secure random string!
app.secret_key = "super_secret_development_key" 
# Allow credentials (cookies/sessions) across origins if needed
CORS(app, supports_credentials=True)
world_path=None
plugins_mods_path=None
nodes = {}
node_tasks = {}

# Start an optional hourly scheduler (controlled via env AUTO_UPDATE=true)
def _start_update_scheduler():
    auto = os.environ.get('AUTO_UPDATE', 'true').lower() == 'true'
    if not auto:
        return

    repo = os.environ.get('GITHUB_REPO') or "kokorocks/mcscp"
    if not repo:
        # nothing to do without a target repo
        return

    pattern = os.environ.get('UPDATE_ASSET_PATTERN')
    exclude_env = os.environ.get('UPDATE_EXCLUDE', 'server-config.json,users.json,node-config.json,minecraft_servers,server-imgs,logs,nodes')
    exclude = [p.strip() for p in exclude_env.split(',') if p.strip()]
    try:
        interval = int(os.environ.get('UPDATE_INTERVAL', '3600'))
    except Exception:
        interval = 3600

    def loop():
        while True:
            try:
                global UPDATING
                if UPDATING:
                    time.sleep(10)
                    continue
                update_state.update({'status': 'checking', 'progress': 5, 'message': 'Checking for updates'})
                info = updater.check_and_prepare_update(repo, asset_pattern=pattern)
                update_state['last'] = info
                update_state['progress'] = 30
                update_state['message'] = 'Latest release checked'
                if info.get('status') == 'downloaded':
                    # apply with a clear UPDATING flag during apply and ensure it is reset
                    try:
                        UPDATING = True
                        update_state.update({'status': 'applying', 'progress': 60, 'message': 'Applying update'})
                        res = updater.apply_update(info['path'], exclude=exclude)
                        update_state['details'] = res
                        update_state['status'] = res.get('status')
                        update_state['progress'] = 95 if res.get('status') == 'applied' else update_state.get('progress', 60)
                        if res.get('status') == 'applied':
                            update_state['message'] = 'Update applied; restarting'
                            try:
                                import sys
                                os.execv(sys.executable, [sys.executable] + sys.argv)
                            except Exception:
                                pass
                    finally:
                        UPDATING = False
            except Exception as e:
                update_state['status'] = 'error'
                update_state['details'] = str(e)
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()

# attempt to start scheduler now
_start_update_scheduler()

def image_to_blob(image_path, file_type="png"):
    # 1. Read the image file as raw binary data (BLOB)
    try:
        with open(image_path, "rb") as image_file:
            blob_data = image_file.read()

        # 2. Encode the binary BLOB to Base64 bytes
        base64_bytes = base64.b64encode(blob_data)

        # 3. Decode bytes into a UTF-8 string to remove the b'' prefix
        base64_string = base64_bytes.decode("utf-8")

        # 4. Construct the inline HTML image Data URI tag
        html_img_tag = f'<img src="data:image/{file_type};base64,{base64_string}" alt="Embedded Image" />'

        return html_img_tag
    
    except Exception as e:

        return "error:"+str(e)


# Example Usage
# If your file is a JPEG, use file_type="jpeg"
#html_output = image_to_html_tag("my_photo.png", file_type="png")
#print(html_output)

# -------------------------
# DATABASE REGISTRIES
# -------------------------
SERVERS={}
def referesh_list():
    global SERVERS
    # create default if missing, then load safely
    if not os.path.exists('server-config.json'):
        with open('server-config.json', 'w', encoding='utf-8') as f:
            json.dump({}, f)
    try:
        with open('server-config.json', 'r', encoding='utf-8') as file:
            SERVERS = json.load(file)
    except Exception:
        SERVERS = {}

USERS_FILE = 'users.json'
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({}, f)

def load_users():
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

processes = {}
logs = {}
os.makedirs("logs", exist_ok=True)
server_types=["vanilla", "paper", "purpur", "fabric", "forge", "spigot", "neoforge"]
server_types2=["vanilla", "papermc", "purpur", "fabric", "forge","spigot" ,"neoforge"]

# -------------------------
# HIERARCHY / PERMISSIONS
# -------------------------
def has_permission(email, sid):
    users = load_users()
    user = users.get(email)
    if not user:
        return False
    # Admins bypass restrictions. Users must have the server ID in their allowed list.
    #if user.get('role') == 'admin' or user.get('role') == 'owner':
    #    return True
    #return int(sid) in user.get('allowed_servers', [])
    return True

# -------------------------
# ACCOUNT API
# -------------------------
@app.route("/create-accounts", methods=["POST"])
def create_account():
    data = request.json
    email = data.get("email")
    username = data.get("username")
    password = data.get("password")

    users = load_users()
    if username in users:
        return jsonify({"error": "Email already registered"}), 400

    # Hierarchy: The first account created becomes an 'admin', the rest are 'user' by default
    role = "owner" if not users else "user"
    if(username in load_users()):
        return jsonify({"message": "Account Already exists, try again"}), 201
    
    users[username] = {
        "email": email,
        "password": generate_password_hash(password),
        "role": role,
        "accepted":len(users) < 1,
        "allowed_servers": [] # Add server IDs here (e.g., [1, 3]) for standard users
    }
    
    save_users(users)
    return jsonify({"message": "Account created successfully, you must wait for your acceptance"}), 201

@login_required
@app.route('/get-server-data/<sid>')
def get_server_data(sid):
    #print(SERVERS)
    if not SERVERS.get(sid):#str(sid) not in SERVERS:
        return jsonify({"error": "Server not found"}), 404

    plugin_path = f"minecraft_servers/{sid}/plugins"
    mods_path = f"minecraft_servers/{sid}/mods"

    if os.path.isdir(plugin_path):
        path = plugin_path
    elif os.path.isdir(mods_path):
        path = mods_path
    else:
        path = None
    print(path)
    plugins = []

    if path:
        for entry in os.scandir(path):
            enabled=False
            if not (entry.is_file() and (entry.name.endswith(".jar") or entry.name.endswith(".jar.disabled"))):
                continue
            if entry.name.endswith(".jar.disabled"):
                filename = entry.name[:-13]  # remove .jar.disabled
                enabled=False
            else: 
                filename = entry.name[:-4]  # remove .jar
                enabled=True
                
            match = re.match(
                r"^(.*?)-(\d+(?:\.\d+)*(?:[-a-zA-Z0-9.]*)?)$",
                filename
            )

            if match:
                name = match.group(1)
                version = match.group(2)
            else:
                name = filename
                version = None
                
            print(name, version, 'yes')

            plugins.append({
                "name": name,
                "version": version,
                "file": entry.name,
                "enabled": enabled,
            })

    return jsonify({
        "data": SERVERS[sid],
        "plugins": plugins
    })
    
@app.route('/get-plugin-config/<sid>/<plugin_name>') 
def get_plugins_config(sid, plugin_name): 
    primary_file = f"minecraft_servers/{sid}/plugins/{plugin_name}/config.yml" 
    fallback_file = f"minecraft_servers/{sid}/plugins/{plugin_name}/config.json" # Choose the file based on existence
    if os.path.exists(primary_file):
        file_to_use = primary_file
    elif os.path.exists(fallback_file):
        file_to_use = fallback_file
    else:
        return {"error": "Config not found"}, 404

    f_type = 'yaml' if file_to_use.endswith('.yml') else 'json'
    with open(file_to_use, 'r', encoding='utf-8') as f:
        content = f.read()

    return {"type": f_type, "content": content}
    
'''@login_required
@app.route('/get-plugin-config/<sid>/<plugin_name>')
def get_plugins_config(sid, plugin_name):
    yml_file = f"minecraft_server/{sid}/{plugin_name}/config.yml"
    json_file = f"app/minecraft_server/{sid}/{plugin_name}/config.json"

    print(os.path.exists(yml_file))
    if os.path.exists(yml_file):
        return {
            "type": "yaml",
            "content": open(yml_file).read()
        }

    if os.path.exists(json_file):
        return {
            "type": "json",
            "content": open(json_file).read()
        }
    #print("CONFIG: ", yml_file)

    return {"error": "Config not found"}, 404'''

def disable_enable_plugins(sid):

    data = request.get_json()
    plugins_path = data.get("path")

    print(plugins_path)

    if sid not in SERVERS:
        return jsonify({"error": "Server not found"}), 404

    plugin_path = f"minecraft_servers/{sid}/plugins/"
    mods_path = f"minecraft_servers/{sid}/mods/"

    if os.path.isdir(plugin_path):
        path = plugin_path
    elif os.path.isdir(mods_path):
        path = mods_path
    else:
        return jsonify({
            "error": f'No plugin found with name "{plugins_path}"'
        }), 404

    file_path = Path(os.path.join(path, plugins_path))
    
    if not file_path.exists():
        return jsonify({
            "error": f'No plugin found with name "{plugins_path}"'
        }), 404

    print(file_path)

    if file_path.suffix == ".disabled":
        new_file_path = file_path.with_suffix("")
    else:
        new_file_path = Path(str(file_path) + ".disabled")

    file_path.rename(new_file_path)

    return jsonify({
        "success": True,
        "path": str(new_file_path)
    }), 200
@login_required
@app.route('/set-plugin-config/<sid>/<plugin_name>', methods=['POST'])
def set_plugins_config(sid, plugin_name):
    primary_file = f"minecraft_server/{sid}/{plugin_name}/config.yml"
    fallback_file = f"minecraft_server/{sid}/{plugin_name}/config.json"

    # Choose the file based on existence
    file_to_use = primary_file if os.path.exists(primary_file) else fallback_file

    with open(file_to_use, 'w') as f:
        f.write(request.json.get('config'))
        
    return jsonify('it worked')

@app.route("/user")
def user():
    return jsonify({"role":session.get("role"), "username": session.get("user")})

@app.route('/create-server', methods=['GET'])
def create_server():
    if "user" not in session:
        return redirect("/login")  # send back to login page
    return open('html/create.htm').read()

@app.route('/edit', methods=['GET'])
def edit_server():
    if "user" not in session:
        return redirect("/login")  # send back to login page
    if(not session['user'] == SERVERS[str(request.args.get('sid'))]["created-by"] and session['user'] not in SERVERS[str(request.args.get('sid'))]["has-access"] and not session['role'] == "owner" and not session['role'] == "admin"):
        #if(not session['user'] == SERVERS[str(request.args.get('sid'))]["created-by"] and not session['role'] == "owner"):
        print("COMPLETELY FAILED BECAUSE U R NOT THE CREATOR")
        return abort(403)
    return open('html/edit.htm').read()

@app.route('/account-settings', methods=['GET'])
def account_settings():
    if "user" not in session:
        return redirect("/login")  # send back to login page
    #if(not session['user'] == SERVERS[str(request.args.get('sid'))]["created-by"] and not session['role'] == "owner"):
    #    print("COMPLETELY FAILED BECAUSE U R NOT THE CREATOR")
    #    return abort(403)
    return open('html/settings.htm').read()


UPLOAD_FOLDER = "uploads"
SERVERS_FOLDER = "servers"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SERVERS_FOLDER, exist_ok=True)

MAX_RAM = 8
MAX_PLAYERS = 100

@login_required
@app.route("/register-node", methods=["POST"])
def register_node():
    node_id = str(uuid.uuid4())

    nodes[node_id] = {
        "info": request.json,
        "online": True
    }

    node_tasks[node_id] = []

    return jsonify({"node_id": node_id})

@login_required
@app.route("/node-tasks/<node_id>")
def get_tasks(node_id):
    return jsonify(node_tasks.get(node_id, []))
 
@login_required
@app.route("/create", methods=["POST"])
def create_s():

    try:
        icon_path=None
        plugins_mods_path=None
        MOD_BACKENDS = {
            "fabric",
            "forge",
            "neoforge"
        }
        # -----------------------
        # READ FORM DATA
        # -----------------------
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "an MCSCP server").strip()

        server_type = request.form.get("type", "PaperMC")
        version = request.form.get("version", "latest")

        ram = int(request.form.get("ram", 2))
        max_players = int(request.form.get("max_players", 20))

        online_mode = request.form.get("online_mode") == "true"
        pvp = request.form.get("pvp") == "true"
        command_blocks = request.form.get("command_blocks") == "true"
        auto_start = request.form.get("auto_start") == "true"
        twenty47 = request.form.get("twenty47") == "true"
        server_properties=request.form.get('server_properties')

        # -----------------------
        # VALIDATION
        # -----------------------
        
        if(twenty47 and session['role'] == "owner" or  session['role'] == "admin"):
            twenty47 = True
        else: 
            twenty47 = False

        if not name:
            return jsonify({
                "error": "Server name required"
            }), 400

        if ram < 1 or ram > MAX_RAM:
            return jsonify({
                "error": f"RAM must be between 1 and {MAX_RAM} GB"
            }), 400

        if max_players < 1 or max_players > MAX_PLAYERS:
            return jsonify({
                "error": f"Max players must be between 1 and {MAX_PLAYERS}"
            }), 400

        # -----------------------
        # CREATE SERVER FOLDER
        # -----------------------
        server_id = str(uuid.uuid4())

        server_path = os.path.join(
            SERVERS_FOLDER,
            server_id
        )

        os.makedirs(server_path, exist_ok=True)

        # -----------------------
        # SAVE FILES
        # -----------------------
        icon = request.files.get("icon")
        world_zip = request.files.get("world_zip")
        server_zip = request.files.get("server_zip")
        plugins_mods = request.files.getlist('plugins_mods')

        if icon:

            filename = secure_filename(icon.filename)

            icon.save(
                os.path.join(
                    server_path,
                    filename
                )
            )
            icon_path=os.path.join(
                                    server_path,
                                    filename
                                  )

        if world_zip:
            global world_path

            filename = secure_filename(
                world_zip.filename
            )

            world_path=os.path.join(
                    server_path,
                    filename
                )
            
            world_zip.save(
                world_path
            )

        if server_zip:

            filename = secure_filename(
                server_zip.filename
            )

            server_zip.save(
                os.path.join(
                    server_path,
                    filename
                )
            )
            
        if plugins_mods:

            folder_name = (
                "mods"
                if server_type.lower() in MOD_BACKENDS
                else "plugins"
            )

            plugins_mods_path = os.path.join(
                server_path,
                folder_name
            )

            os.makedirs(plugins_mods_path, exist_ok=True)

            for file in plugins_mods:
            
                if not file.filename:
                    continue
                
                # Preserve folder structure if uploaded as a directory
                rel_path = file.filename.replace("\\", "/")

                save_path = os.path.join(
                    plugins_mods_path,
                    rel_path
                )

                os.makedirs(
                    os.path.dirname(save_path),
                    exist_ok=True
                )

                file.save(save_path)

        # -----------------------
        # SAVE CONFIG
        # -----------------------
        config = {
            "id": server_id,
            "name": name,
            "desc": description,
            "type": server_type,
            "version": version,
            "ram": f"{ram}G",
            "maxPlayers": max_players,
            "online_mode": online_mode,
            "pvp": pvp,
            "command_blocks": command_blocks,
            "auto_start": auto_start
        }

        print("Created server:")
        #print(config)
        print("WORLD PATH", world_path)
        print(session)
        create.create_server(user=session['user'] ,choice=server_types2.index(server_type.lower())+1, name=name, version=version, ram=f"{ram}G", max_players=max_players, desc=description, icon_path=icon_path, map_path=world_path,plugins_mods_path=plugins_mods_path ,server_properties=server_properties, twenty47=twenty47)
        referesh_list()
        return jsonify({
            "success": True,
            "server": config
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

@login_required
@app.route(
    "/edit-server/<sid>",
    methods=["POST"]
)
def edit_s(sid):

    try:

        if sid not in SERVERS:
            return jsonify({
                "error": "Server not found"
            }), 404
        if(not session['user'] == SERVERS[str(sid)]["created-by"] and session['user'] not in SERVERS[str(sid)]["has-access"] and not session['role'] == "owner" and not session['role'] == "admin"):
            print("COMPLETELY FAILED BECAUSE U R NOT THE CREATOR")
            return abort(403)

        temp_dir = os.path.join(
            "temp",
            sid
        )

        os.makedirs(
            temp_dir,
            exist_ok=True
        )

        icon_path = None
        map_path = None
        plugins_mods_path = None

        # --------------------
        # ICON
        # --------------------

        icon = request.files.get("icon")

        if icon and icon.filename:

            icon_path = os.path.join(
                temp_dir,
                secure_filename(
                    icon.filename
                )
            )

            icon.save(icon_path)

        # --------------------
        # WORLD
        # --------------------

        world = request.files.get(
            "world_zip"
        )

        if world and world.filename:

            map_path = os.path.join(
                temp_dir,
                secure_filename(
                    world.filename
                )
            )

            world.save(map_path)

        # --------------------
        # PLUGINS / MODS
        # --------------------

        uploaded_files = (
            request.files.getlist(
                "plugins_mods"
            )
        )

        if uploaded_files:

            plugins_mods_path = os.path.join(
                temp_dir,
                "plugins_mods"
            )

            os.makedirs(
                plugins_mods_path,
                exist_ok=True
            )

            for file in uploaded_files:

                if not file.filename:
                    continue

                target = os.path.join(
                    plugins_mods_path,
                    file.filename
                )

                os.makedirs(
                    os.path.dirname(target),
                    exist_ok=True
                )

                file.save(target)
                
        deleted_plugins = json.loads(
            request.form.get(
                "deleted_plugins",
                "[]"
            )
        )
        plugin_states = json.loads(
            request.form.get(
                "plugin_states",
                "[]"
            )
        )
        plugin_configs = json.loads(
            request.form.get(
                "plugin_configs",
                "{}"
            )
        )
        # --------------------
        # EDIT SERVER
        # --------------------
        #if deleted_plugins:
#
        #    for plugin in deleted_plugins:
        #    
        #        delete_plugin_and_data(
        #            folder,
        #            plugin
        #        )
        create.edit_server(
            sid=sid,

            name=request.form.get(
                "name"
            ) or None,

            desc=request.form.get(
                "desc"
            ) or None,

            ram=(
                request.form.get("ram")
                + "G"
                if request.form.get("ram")
                else None
            ),

            max_players=(
                int(
                    request.form.get(
                        "maxPlayers"
                    )
                )
                if request.form.get(
                    "maxPlayers"
                )
                else None
            ),

            version=request.form.get(
                "version"
            ) or None,

            server_type=request.form.get(
                "type"
            ) or None,

            icon_path=icon_path,

            map_path=map_path,

            plugins_mods_path=
                plugins_mods_path,

            server_properties=
                request.form.get(
                    "server_properties"
                ) or None,

            twenty47=(
                request.form.get(
                    "twenty47"
                ) == "true"
                
            ),
            deleted_plugins=deleted_plugins,
            plugin_states=plugin_states)
        '''deleted_plugins = json.loads(
        request.form.get(
            "deleted_plugins",
            "[]"
        )
    )'''
    
        

        return jsonify({
            "success": True
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "error": str(e)
        }), 500

@login_required
@app.route('/logs/<sid>')
def log(sid):
    if(not str(sid) in processes): print(SERVERS[sid].get('status'),"OFFLINE", sid); return ""
    print(SERVERS[sid].get('status'),'. server ', sid, 'online')
    if (os.path.isfile(f"minecraft_servers/{sid}/logs/latest.log")):
        with open(f"minecraft_servers/{sid}/logs/latest.log", "r") as file:
            log_val = file.read()
    else:
        log_val="server is starting"
    #log
    return log_val#"".join(set(log_val) - set(server_log[sid]))#server_log[sid]

# This is the ONLY rule you define
def get_root(server_id):
    return f"minecraft_servers/{server_id}"

def permission_check(server_id):
    return True  # replace with auth later if needed

# Register ONCE
register_file_manager(
    app,
    get_root=get_root,
    permission_check=permission_check,
    url_prefix="/files"
)

@login_required
@app.route("/send/<sid>", methods=["POST"])
def send_command(sid):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    #if not has_permission(session["user"], int(sid)):
    #    return jsonify({"error": "No permission"}), 403
    if(not session['user'] == SERVERS[str(sid)]["created-by"] and session['user'] not in SERVERS[str(sid)]["has-access"] and not session['role'] == "owner" and not session['role'] == "admin"): #has-access
        print("COMPLETELY FAILED BECAUSE U R NOT THE CREATOR")
        return abort(403)
    if sid not in processes:
        return jsonify({"error": "Server offline"}), 400

    command = request.json.get("command", "").strip()

    if not command:
        return jsonify({"error": "Empty command"}), 400

    try:
        proc = processes[sid]

        proc.stdin.write(command + "\n")
        proc.stdin.flush()

        return jsonify({
            "success": True,
            "command": command
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

@app.route("/sign-in", methods=["POST"])
def sign_in():
    data = request.json

    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    print(username, password)

    users = load_users()

    user = users.get(username)
    
    print(user)

    # User not found
    #print(user)
    #print(user['accepted'])
    if not user or not user['accepted']:
        return jsonify({"error": "Invalid credentials or your account has not been accepted"}), 401

    # Password check
    if check_password_hash(user["password"], password):
        session["user"] = username
        session["role"] = user["role"]
        print(session)

        return jsonify({
            "message": "Logged in",
            "role": user["role"]
        }), 200

    return jsonify({"error": "Invalid credentials"}), 401

def send_to_node(node_id, command):
    node_tasks[node_id].append(command)

@login_required
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200


@app.route('/delete', methods=['POST'])
def delete():
    
    sid = int(request.json["id"])
    
    if(not session['user'] == SERVERS[str(sid)]["created-by"] and session['user'] not in SERVERS[str(sid)]["has-access"] and not session['role'] == "owner" and not session['role'] == "admin"):
        print("COMPLETELY FAILED BECAUSE U R NOT THE CREATOR")
        return abort(403)
    
    if(not SERVERS[str(sid)]['node'] == 'main'):
        node_id = SERVERS[str(sid)]["node_id"]

        send_to_node(node_id, {
            "type": "delete",
            "sid": sid
        })
    
    try:
        os.remove('server-imgs/'+str(sid)+'.png')
    except Exception as e:
        print(e)
    try:
        shutil.rmtree("minecraft_servers/"+str(sid))
    except Exception as e:
        print(e)

    # 2. Pop key "4" out of the dictionary (returns None if it doesn't exist)
    SERVERS[str(sid)]={"deleted":True}

    # 3. Save the updated layout back to the file
    with open('server-config.json', 'w') as file:
        json.dump(SERVERS, file, indent=4)
        

    #print("Server 4 successfully removed!")
    
    
    
@app.route('/kill', methods=['POST'])
def kill_process():
    referesh_list()
    #print('GIVEN JSON FOR /KILL', request.json["id"])
    sid = int(request.json["id"])
    #print("SERVER", SERVERS[str(sid)])
    if "user" not in session:
        return abort(401)
    
    if(not session['user'] == SERVERS[str(sid)]["created-by"] and session['user'] not in SERVERS[str(sid)]["has-access"] and not session['role'] == "owner" and not session['role'] == "admin"):
        print("COMPLETELY FAILED BECAUSE U R NOT THE CREATOR")
        return abort(403)
    print('KILLING ', sid, 'PROCESS')
    success=kill(sid)
    if success:
        return jsonify({"ok": True})
    else:
        return jsonify({"bad": False})


    # -------------------------
    # SERVER CONTROL LOGIC
    # -------------------------
def start_server(sid):
    def stop_listener(sid):
        sid = str(sid)

        if sid in listener_stop_flags:
            listener_stop_flags[sid].set()

        if sid in listener_sockets:
            try:
                listener_sockets[sid].close()
            except:
                pass

            del listener_sockets[sid]
            
    
    stop_listener(sid)

    if str(sid) in processes:
        return
    
    if str(sid) in processes: return
    s = SERVERS[str(sid)]
    logs[str(sid)] = []
    
    #java -Xmx4G -Xms4G -jar minecraft_server.26.1.2.jar nogui
    cmd = ["java", f"-Xms{s['ram']}", f"-Xmx{s['ram']}", "-jar", "server.jar", "nogui"]
    
    node_id=s['node']
    print("NODE ID IS THIS VALUE RIGHT HERE SO YA I GOT NOTHIN ELSE TO SAY", node_id)
    
    if(not node_id == "main"):
        send_to_node(node_id, {
            "type": "start",
            "sid": sid,
            "ram": SERVERS[str(sid)]["ram"]
        })

        # store assignment
        SERVERS[str(sid)]["node_id"] = node_id

        return jsonify({"ok": True, "node": node_id})
    
    proc = subprocess.Popen(
        cmd,
        cwd=f"minecraft_servers/{sid}",
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    processes[str(sid)] = proc
    print('SERVER ', sid, 'NOW PROCESS', proc)
    server_started[str(sid)] = False
    server_log[sid]=''
    def reader():
        player_counts[str(sid)] = 0
        idle_since[str(sid)] = time.time()

        join_pattern = re.compile(r": ([^ ]+) joined the game")
        leave_pattern = re.compile(r": ([^ ]+) left the game")

        for line in proc.stdout:
            line = line.strip()

            logs[str(sid)].append(line)

            if len(logs[str(sid)]) > 200:
                logs[str(sid)].pop(0)

            if join_pattern.search(line):
                player_counts[str(sid)] += 1

                print(
                    f"[{sid}] Player joined "
                    f"({player_counts[str(sid)]} online)"
                )

            elif leave_pattern.search(line):

                player_counts[str(sid)] = max(
                    0,
                    player_counts[str(sid)] - 1
                )

                print(
                    f"[{sid}] Player left "
                    f"({player_counts[str(sid)]} online)"
                )

                if player_counts[str(sid)] == 0:
                    idle_since[str(sid)] = time.time()
                
            for line in proc.stdout:
                line = line.rstrip()

                logs[str(sid)].append(line)

                if (
                    "Done (" in line
                    and '! For help, type "help"' in line
                ):
                    server_started[str(sid)] = True
    
    reader()

    threading.Thread(target=reader, daemon=True).start()

def listen_for_join(sid, port):
    stop_flag = threading.Event()
    listener_stop_flags[sid] = stop_flag

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.listen(5)
    sock.settimeout(1)

    listener_sockets[sid] = sock

    print(f"[AUTOSTART] Listening on {port}")

    while not stop_flag.is_set():
        try:
            conn, addr = sock.accept()

            print(f"[AUTOSTART] Connection from {addr}")

            if str(sid) not in processes:
                start_server(sid)

            conn.close()

        except socket.timeout:
            continue

    sock.close()
    

        
def start_autostart_listeners():

    referesh_list()

    for sid, server in SERVERS.items():

        if not server.get(
            "auto-start-on-join",
            False
        ):
            continue

        port = int(server["port"])

        t = threading.Thread(
            target=listen_for_join,
            args=(sid, port),
            daemon=True
        )

        t.start()

        listeners[sid] = t

def stop_server(sid):
    s=SERVERS[str(sid)]
    if(not s['node']=='main'):
        node_id = SERVERS[str(sid)]["node_id"]
    
        send_to_node(node_id, {
            "type": "kill",
            "sid": sid
        })
    
        return jsonify({"ok": True})
    sid = str(sid)
    if sid not in processes: return
    proc = processes[sid]
    try:
        proc.stdin.write("save-all\n")
        proc.stdin.flush()
        time.sleep(2)                                                                                                                                                                    #hi
        proc.stdin.write("stop\n")
        proc.stdin.flush()
        proc.wait(timeout=30)
    except Exception as e:
        proc.terminate()
    finally:
        server_started.pop(str(sid), None)
        del processes[sid]

        server = SERVERS[sid]

        if server.get("auto-start-on-join"):
            port = int(server["port"])

            t = threading.Thread(
                target=listen_for_join,
                args=(sid, port),
                daemon=True
            )
            t.start()

            listeners[sid] = t

def kill(sid):
    s=SERVERS[str(sid)]
    if(not s['node'] == 'main'):
        node_id = SERVERS[str(sid)]["node_id"]

        send_to_node(node_id, {
            "type": "kill",
            "sid": sid
        })

        return jsonify({"ok": True})
    sid = str(sid)
    if sid not in processes: return
    proc = processes[sid]
    try:
        proc.kill()
    except Exception as e:
        proc.terminate()
    finally:
        server_started.pop(str(sid), None)
        del processes[sid]

def currentlyonline(sid):
    return player_counts.get(str(sid), 0)

def idle_server_monitor():

    while True:

        time.sleep(60)

        referesh_list()

        for sid, server in SERVERS.items():

            sid = str(sid)

            if sid not in processes:
                continue

            if server.get("twenty47"):
                continue

            players = player_counts.get(sid, 0)

            if players > 0:
                continue

            sleep_minutes = int(
                server.get("sleep-time", 10)
            )

            idle_time = (
                time.time()
                - idle_since.get(
                    sid,
                    time.time()
                )
            )

            if idle_time >= sleep_minutes * 60:

                print(
                    f"[AUTO-SLEEP] "
                    f"Stopping {sid}"
                )

                stop_server(sid)

# -------------------------
# PROTECTED API ENDPOINTS
# -------------------------
@app.route('/login')
def account():
    if "user" in session:
        return redirect("/")  # send back to login page
    
    return open('html/account.htm').read()

@app.route('/')
def index():
    if "user" not in session:
        return redirect("/login")  # send back to login page
    referesh_list()
    return open('html/index.htm').read()

@app.route('/owners')
def owner_area():
    require_owner()
    return open('html/owner.htm').read()

@app.route('/nodes')
def node_s():
    require_owner()
    return open('html/nodes.htm').read()

@login_required
@app.route("/server-icon/<sid>")
def server_icon(sid):

    path = f"server-imgs/{sid}.png"

    if not os.path.exists(path):
        return send_file("default.png", mimetype="image/png")
    
    if "user" not in session:abort(401)

    return send_file(path, mimetype="image/png")

@login_required
@app.route("/servers")
def servers():
    data = []
    for sid, s in SERVERS.items():
        if str(sid) not in processes:
            status = "Offline"
        elif server_started.get(str(sid), False):
            status = "Online"
        else:
            status = "Starting"
        #print(image_to_blob('minecraft_servers/'+sid+"/server-icon.png"))
        if(not s.get("deleted")):
            data.append({
                "id": sid,
                "name": s["name"],
                "version":s["version"],
                "maxPlayers":str(s["max-players"]),
                "players": currentlyonline(sid),
                "type": server_types[int(s["type"])-1],
                "status": status, #"started" if 'Done (' in data and '! For help, type "help"' in data else "Starting" if str(sid) in processes else "Offline",
                "ram": s["ram"],
                "port": s["port"],
                "desc": s["desc"],
                "creator": s["created-by"],
                #"img": image_to_blob('minecraft_servers/'+sid+"/server-icon.png")
            })
        else:
            data.append({
                "deleted": True
            })
        #print(data)
    return jsonify({"servers":data, "update": UPDATE})

@app.route("/update")
def update():
    global UPDATING
    require_owner()
    UPDATING = True
    return redirect('/updating')
    

@app.route('/updating')
def updating():
    if(UPDATING):
        return open('html/updating.htm').read()
    else:
        return redirect(url_for('index'))


@app.route('/api/update/state')
def update_state_api():
    # public read-only state for the updating page
    s = update_state.copy()
    # redact large details
    if 'details' in s and isinstance(s['details'], dict):
        d = s['details'].copy()
        # keep only status and backup
        s['details'] = {k: d.get(k) for k in ('status','backup') if k in d}
    return jsonify(s)

@app.route("/verify-users")
def verify_users():

    require_owner()

    users = load_users()

    data = []

    for username, u in users.items():

        data.append({
            "username": username,
            "email": u.get("email"),
            "role": u.get("role", "user"),
            "accepted": u.get("accepted", False),
            "allowed_servers": u.get("allowed_servers", [])
        })

    return jsonify(data)

@app.route("/accept-user", methods=["POST"])
def accept_user():

    require_owner()

    data = request.json

    username = data.get("username")

    users = load_users()

    if username not in users:
        return jsonify({
            "error": "User not found"
        }), 404

    users[username]["accepted"] = True

    save_users(users)

    return jsonify({
        "message": f"{username} accepted"
    })
    
@app.route("/deny-user", methods=["POST"])
def deny_user():

    require_owner()

    data = request.json

    username = data.get("username")

    users = load_users()

    if username not in users:
        return jsonify({
            "error": "User not found"
        }), 404

    del users[username]

    save_users(users)

    return jsonify({
        "message": f"{username} deleted"
    })    
    
@app.route("/set-role", methods=["POST"])
def set_role():

    require_owner()

    data = request.json

    username = data.get("username")
    role = data.get("role")

    allowed_roles = [
        "user",
        "admin",
        "owner"
    ]

    if role not in allowed_roles:
        return jsonify({
            "error": "Invalid role"
        }), 400

    users = load_users()

    if username not in users:
        return jsonify({
            "error": "User not found"
        }), 404

    users[username]["role"] = role

    save_users(users)

    return jsonify({
        "message": f"{username} is now {role}"
    })


@app.route("/start", methods=["POST"])
def start():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    
    sid = int(request.json["id"])
    if not has_permission(session["user"], sid):
        return jsonify({"error": "Hierarchy restricted: You do not have permission for this server."}), 403

    start_server(sid)
    return jsonify({"ok": True})

@app.route("/stop", methods=["POST"])
def stop():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    
    sid = int(request.json["id"])
    if not has_permission(session["user"], sid):
        return jsonify({"error": "Hierarchy restricted: You do not have permission for this server."}), 403

    stop_server(sid)
    return jsonify({"ok": True})

def autostart():
    #data = []
    referesh_list()
    for sid, s in SERVERS.items():
        if(s.get('twenty47')):
            print("STARTING 24/7 SERVER: ", sid)
            start_server(sid)

#with app.app_context():
#    autostart()

if __name__ == "__main__":
    threading.Thread(target=autostart, daemon=True).start()

    threading.Thread(
        target=idle_server_monitor,
        daemon=True
    ).start()

    start_autostart_listeners()
    
    debug=False #True
    app.run(host="0.0.0.0", port=5000, debug=debug)