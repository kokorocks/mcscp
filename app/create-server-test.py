from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
import uuid

app = Flask(__name__)

UPLOAD_FOLDER = "./uploads"
SERVERS_FOLDER = "servers"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SERVERS_FOLDER, exist_ok=True)

MAX_RAM = 32
MAX_PLAYERS = 500


@app.route("/create_server", methods=["POST"])
def create_server():

    try:

        # -----------------------
        # READ FORM DATA
        # -----------------------
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "an MCSCP").strip()

        server_type = request.form.get("type", "PaperMC")
        version = request.form.get("version", "latest")

        ram = int(request.form.get("ram", 2))
        max_players = int(request.form.get("max_players", 20))

        online_mode = request.form.get("online_mode") == "true"
        pvp = request.form.get("pvp") == "true"
        command_blocks = request.form.get("command_blocks") == "true"
        auto_start = request.form.get("auto_start") == "true"

        # -----------------------
        # VALIDATION
        # -----------------------
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

        if icon:

            filename = secure_filename(icon.filename)

            icon.save(
                os.path.join(
                    server_path,
                    filename
                )
            )

        if world_zip:

            filename = secure_filename(
                world_zip.filename
            )

            world_zip.save(
                os.path.join(
                    server_path,
                    filename
                )
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

        # -----------------------
        # SAVE CONFIG
        # -----------------------
        config = {
            "id": server_id,
            "name": name,
            "description": description,
            "type": server_type,
            "version": version,
            "ram": ram,
            "max_players": max_players,
            "online_mode": online_mode,
            "pvp": pvp,
            "command_blocks": command_blocks,
            "auto_start": auto_start
        }

        print("Created server:")
        print(config)

        return jsonify({
            "success": True,
            "server": config
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


if __name__ == "__main__":
    app.run(debug=True)