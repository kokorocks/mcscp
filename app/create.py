from PIL import Image, ImageOps
import xml.etree.ElementTree as ET
from pathlib import Path
import os
import requests
import shutil
import uuid
import json
import zipfile
import tempfile
import re
import glob
import subprocess
import sys
import urllib.request
import traceback
server_types=["vanilla", "paper", "purpur", "fabric", "forge", "spigot", "neoforge"]
server_types2=["vanilla", "papermc", "purpur", "fabric", "forge", "spigot", "neoforge"]

url = None
globalnum = 0
BASE_DIR = "minecraft_servers"

# ----------------------------
# JSON STORAGE
# ----------------------------
def appendjson(jsonFile="data.json", newContents=None):
    global globalnum

    if not os.path.exists(jsonFile) or os.path.getsize(jsonFile) == 0:
        data = {}
    else:
        with open(jsonFile, 'r') as file:
            try:
                data = json.load(file)

                if not isinstance(data, dict):
                    data = {}

            except json.JSONDecodeError:
                data = {}
    next_id = str(len(data) + 1)
    globalnum = int(next_id)

    data[next_id] = newContents

    with open(jsonFile, 'w') as file:
        json.dump(data, file, indent=4)


# ----------------------------
# UTIL
# ----------------------------
def mkdir(path):
    os.makedirs(path, exist_ok=True)
    
def process_server_icon(icon_path, output_path):
    """
    Crops image to square (center), fixes rotation, then resizes to 64x64
    """

    if not icon_path or not os.path.exists(icon_path):
        return False

    try:
        img = Image.open(icon_path)

        # ----------------------------
        # FIX PHONE IMAGE ROTATION BUG
        # ----------------------------
        img = ImageOps.exif_transpose(img)

        img = img.convert("RGBA")

        # ----------------------------
        # CENTER CROP TO SQUARE
        # ----------------------------
        width, height = img.size
        side = min(width, height)

        left = (width - side) // 2
        top = (height - side) // 2
        right = left + side
        bottom = top + side

        img = img.crop((left, top, right, bottom))

        # ----------------------------
        # RESIZE TO 64x64
        # ----------------------------
        img = img.resize((64, 64), Image.LANCZOS)

        # ----------------------------
        # SAVE
        # ----------------------------
        img.save(output_path, "PNG")

        return True

    except Exception as e:
        print("Icon processing failed:", e)
        return False
def download(url, path):
    print(f"Downloading from: {url}")

    if not url:
        raise Exception("Download URL is None")

    r = requests.get(url, stream=True)

    if r.status_code != 200:
        raise Exception(
            f"Failed download ({r.status_code}) -> {url}"
        )

    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"Saved: {path}")


# ----------------------------
# VERSION FETCHERS
# ----------------------------
def get_vanilla_manifest():
    return requests.get(
        "https://launchermeta.mojang.com/mc/game/version_manifest.json"
    ).json()

def convert_version_for_paper(version: str) -> dict:
    """
    Converts Mojang version strings into a Paper-compatible format.
    """

    original_version = version.lower().strip()

    result = {
        "original": version,
        "paper_version": None,
        "software": "paper",
        "type": "release"
    }

    # -----------------------------------
    # Weekly snapshots like 26w14a
    # -----------------------------------
    if re.match(r"^\d+w\d+[a-z]$", original_version):
        result["software"] = "vanilla"
        result["type"] = "snapshot"
        return result

    # -----------------------------------
    # Snapshot format:
    # 26.1.2-snapshot-5
    # -----------------------------------
    snapshot_match = re.match(
        r"^(\d+\.\d+\.\d+)-snapshot-\d+$",
        original_version
    )

    if snapshot_match:
        base_version = snapshot_match.group(1)

        result["paper_version"] = base_version
        result["type"] = "snapshot"

        return result

    # -----------------------------------
    # Pre-releases:
    # 26.1.2-pre-1
    # 26.1.2 pre
    # -----------------------------------
    pre_match = re.match(
        r"^(\d+\.\d+\.\d+)[-\s]?pre[-\s]?\d*$",
        original_version
    )

    if pre_match:
        base_version = pre_match.group(1)

        result["paper_version"] = base_version
        result["type"] = "pre-release"

        return result

    # -----------------------------------
    # Release candidates:
    # 26.1.2-rc-1
    # -----------------------------------
    rc_match = re.match(
        r"^(\d+\.\d+\.\d+)-rc-\d+$",
        original_version
    )

    if rc_match:
        base_version = rc_match.group(1)

        result["paper_version"] = base_version
        result["type"] = "release-candidate"

        return result

    # -----------------------------------
    # Normal releases
    # -----------------------------------
    release_match = re.match(
        r"^\d+\.\d+\.\d+$",
        original_version
    )

    if release_match:
        result["paper_version"] = original_version
        result["type"] = "release"

        return result

    # -----------------------------------
    # Unknown format
    # -----------------------------------
    result["software"] = "vanilla"
    result["type"] = "unknown"

    return result


# -----------------------------------
# Examples
# -----------------------------------

#versions = [
#    "26.1.2",
#    "26.1.2-pre-1",
#    "26.1.2 pre",
#    "26.1.2-rc-1",
#    "26.1.2-snapshot-5",
#    "26w14a"
#]
#
#for v in versions:
#    print(convert_version_for_paper(v))

def get_vanilla_versions():
    manifest = get_vanilla_manifest()

    return [
        v["id"]
        for v in manifest["versions"]
        if v["type"] == "release"
    ]

def get_purpur_versions():
    data = requests.get(
        "https://api.purpurmc.org/v2/purpur"
    ).json()

    return data.get("versions", [])


def get_fabric_versions():
    data = requests.get(
        "https://meta.fabricmc.net/v2/versions/game"
    ).json()

    return [
        v["version"]
        for v in data
        if v.get("stable")
    ]

# ----------------------------
# NEOFORGE
# ----------------------------

'''def get_neoforge_url(version):

    data = requests.get(
        "https://maven.neoforged.net/api/maven/latest/version/releases/net/neoforged/neoforge"
    ).json()

    versions = data.get("versions", [])

    mc_version = ".".join(version.split(".")[1:])

    matches = [
        v for v in versions
        if v.startswith(mc_version + ".")
    ]

    if not matches:
        raise Exception(
            f"No NeoForge build found for MC {version}"
        )

    matching = matches[-1]  # newest build

    return (
        f"https://maven.neoforged.net/releases/"
        f"net/neoforged/neoforge/{matching}/"
        f"neoforge-{matching}-installer.jar"
    )'''

def install_neoforge(server_dir, version):

    installer_url = get_neoforge_url(version)

    installer_path = os.path.join(
        server_dir,
        "neoforge-installer.jar"
    )

    # Download installer
    response = requests.get(
        installer_url,
        stream=True
    )

    response.raise_for_status()

    with open(installer_path, "wb") as f:
        for chunk in response.iter_content(8192):
            f.write(chunk)

    print("Running NeoForge installer...")

    # Run installer
    subprocess.run(
        [
            "java",
            "-jar",
            installer_path,
            "--installServer"
        ],
        cwd=server_dir,
        check=True
    )

    # Find generated NeoForge jar
    neoforge_jars = glob.glob(
        os.path.join(server_dir, "neoforge-*.jar")
    )

    if not neoforge_jars:
        raise Exception(
            "Could not find NeoForge server jar"
        )

    # Copy to server.jar
    shutil.copy2(
        neoforge_jars[0],
        os.path.join(server_dir, "server.jar")
    )

    print("NeoForge installed.")
'''def get_neoforge_url(version):
    versions = get_neoforge_versions()

    prefix = mc_to_neoforge_prefix(version)

    matches = [
        v for v in versions
        if v.startswith(prefix + ".")
    ]

    if not matches:
        raise Exception(
            f"No NeoForge build found for MC {version}"
        )

    matching = matches[-1]

    return (
        f"https://maven.neoforged.net/releases/"
        f"net/neoforged/neoforge/{matching}/"
        f"neoforge-{matching}-installer.jar"
    )'''
def get_forge_versions():
    data = requests.get(
        "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
    ).json()

    versions = set()

    for key in data["promos"].keys():
        version = key.split("-")[0]
        versions.add(version)

    return sorted(list(versions), reverse=True)

'''def get_neoforge_url(version):
    versions = get_neoforge_versions()

    prefix = mc_to_neoforge_prefix(version)

    matches = [
        v for v in versions
        if v.startswith(prefix + ".")
    ]

    if not matches:
        raise Exception(
            f"No NeoForge build found for MC {version}"
        )

    matching = matches[-1]

    return (
        f"https://maven.neoforged.net/releases/"
        f"net/neoforged/neoforge/{matching}/"
        f"neoforge-{matching}-installer.jar"
    )'''
    
def get_neoforge_builds():
    xml_text = requests.get(
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
    ).text

    root = ET.fromstring(xml_text)

    builds = []

    for version in root.findall(".//version"):
        builds.append(version.text)

    return builds
    
    
def get_neoforge_versions():
    xml_text = requests.get(
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
    ).text

    root = ET.fromstring(xml_text)

    mc_versions = set()

    for version in root.findall(".//version"):
        v = version.text.split("-")[0]

        parts = v.split(".")

        # NeoForge release versions look like:
        # 21.6.12
        # 21.7.103
        # 20.6.95
        if (
            len(parts) >= 3
            and parts[0].isdigit()
            and parts[1].isdigit()
        ):
            mc_versions.add(f"1.{parts[0]}.{parts[1]}")

    return sorted(
        mc_versions,
        key=lambda x: tuple(map(int, x.split("."))),
        reverse=True
    )

def mc_to_neoforge_prefix(mc_version):
    parts = mc_version.split(".")
    print('CONVERTED VRESION', f"{parts[1]}.{parts[2]}")
    return f"{parts[1]}.{parts[2]}"
def get_neoforge_url(version):
    builds = get_neoforge_builds()

    prefix = mc_to_neoforge_prefix(version)

    matches = [
        b for b in builds
        if b.startswith(prefix + ".")
    ]

    print("PREFIX:", prefix)
    print("MATCHES:", matches[-5:])

    if not matches:
        raise Exception(
            f"No NeoForge build found for MC {version}"
        )

    matching = matches[-1]

    return (
        f"https://maven.neoforged.net/releases/"
        f"net/neoforged/neoforge/{matching}/"
        f"neoforge-{matching}-installer.jar"
    )
#print(get_neoforge_versions())

# ----------------------------
# CONSISTENT VERSION HANDLER
# ----------------------------
def get_versions(choice):

    choice = str(choice)

    if choice == "1":
        return get_vanilla_versions()

    elif choice == "2":
        return get_paper_versions()

    elif choice == "3":
        return get_purpur_versions()

    elif choice == "4":
        return get_fabric_versions()

    elif choice == "5":
        return get_forge_versions()

    elif choice == "6":
        return get_vanilla_versions()  # Spigot uses vanilla versions

    elif choice == "7":
        print(get_neoforge_versions())
        return get_neoforge_versions()

    return []




# ----------------------------
# DOWNLOAD URL FETCHERS
# ----------------------------
def get_vanilla_url(version):
    manifest = get_vanilla_manifest()

    for v in manifest["versions"]:

        if v["id"] == version:

            data = requests.get(v["url"]).json()

            return data["downloads"]["server"]["url"]

    return None


def get_paper_versions():
    try:
        # Using the official PaperMC API
        data = requests.get(
            "https://fill.papermc.io/v3/projects/paper/versions"
        ).json()
        #print(data)
        return data.get("versions", [])
    except Exception as e:
        print(f"Error fetching Paper versions: {e}")
        return []


def get_paper_url(version):

    #converted = convert_version_for_paper(version)

    # snapshots/pre-releases should use vanilla
    #if converted["software"] != "paper":
    #    raise Exception(
    #        f"{version} is not supported by PaperMC"
    #    )

    #version = converted["paper_version"]

    print("VERSION:", version)

    builds_url = (
        f"https://fill.papermc.io/v3/projects/"
        f"paper/versions/{version}/builds"
    )

    print("BUILD URL:", builds_url)

    data = requests.get(builds_url).json()

    # v3 API returns list directly
    if not isinstance(data, list):
        raise Exception(
            f"Unexpected Paper API response: {data}"
        )

    if not data:
        raise Exception(
            f"No Paper builds found for {version}"
        )

    latest_build = max(data, key=lambda b: b["id"])

    downloads = latest_build.get("downloads", {})

    server_default = downloads.get("server:default")

    if not server_default:
        raise Exception(
            "Missing server:default download"
        )

    url = server_default.get("url")

    if not url:
        raise Exception(
            "Missing download URL"
        )

    return url

def get_purpur_url(version):

    data = requests.get(
        f"https://api.purpurmc.org/v2/purpur/{version}"
    ).json()

    builds = data.get("builds")

    if not builds:
        raise Exception(
            f"No Purpur builds found for version {version}"
        )

    build = builds["latest"]

    return (
        f"https://api.purpurmc.org/v2/purpur/"
        f"{version}/{build}/download"
    )

# ----------------------------
# FABRIC
# ----------------------------

# ----------------------------
# FABRIC
# ----------------------------

def get_fabric_url(version):
    """
    Dynamically fetches the latest stable Fabric Loader and Installer versions
    to build a functional server JAR download URL.
    """
    # Safe fallbacks if the API is completely unreachable
    loader_version = "0.15.11"
    installer_version = "1.0.1"
    
    try:
        # Fetch the latest stable loader
        loader_res = requests.get("https://meta.fabricmc.net/v2/versions/loader")
        if loader_res.status_code == 200:
            loaders = loader_res.json()
            stable_loaders = [l["version"] for l in loaders if l.get("stable")]
            if stable_loaders:
                loader_version = stable_loaders[0]
                
        # Fetch the latest stable installer
        installer_res = requests.get("https://meta.fabricmc.net/v2/versions/installer")
        if installer_res.status_code == 200:
            installers = installer_res.json()
            stable_installers = [i["version"] for i in installers if i.get("stable")]
            if stable_installers:
                installer_version = stable_installers[0]
    except Exception as e:
        print(f"Warning: Failed to fetch dynamic Fabric versions, using fallbacks. Error: {e}")

    return (
        f"https://meta.fabricmc.net/v2/versions/loader/"
        f"{version}/{loader_version}/{installer_version}/server/jar"
    )


def install_fabric(server_dir, version):
    global url
    """
    Safely handles the Fabric server installation without scoping issues.
    """
    # Defensive initialization to completely prevent UnboundLocalError
    url = None 
    
    try:
        url = get_fabric_url(version)
        server_jar = os.path.join(server_dir, "server.jar")

        print(f"Downloading Fabric server jar from: {url}")
        response = requests.get(url, stream=True)
        response.raise_for_status()

        with open(server_jar, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)

        print("Fabric installed successfully.")
        
    except Exception as e:
        url_str = url if url else "Unknown URL"
        raise Exception(f"Failed to install Fabric from {url_str}. Error: {e}")


def get_forge_url(version):
    """Fetches the correct Forge installer URL for a given Minecraft version."""
    
    data = requests.get(
        "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
    ).json()

    promos = data["promos"]

    # Check for 'latest' first, then fallback to 'recommended'
    latest_key = f"{version}-latest"
    recommended_key = f"{version}-recommended"

    if latest_key in promos:
        forge_version = promos[latest_key]
    elif recommended_key in promos:
        forge_version = promos[recommended_key]
    else:
        raise Exception(f"No Forge build found for MC {version}")

    return (
        f"https://maven.minecraftforge.net/net/minecraftforge/"
        f"forge/{version}-{forge_version}/"
        f"forge-{version}-{forge_version}-installer.jar"
    )


def install_forge(server_dir, version):
    global url
    """Downloads and installs the Forge server into the specified directory."""
    
    installer_url = get_forge_url(version)
    installer_path = os.path.join(server_dir, "forge-installer.jar")

    # 1. Download installer
    print(f"Downloading Forge installer for {version}...")
    response = requests.get(installer_url, stream=True)
    response.raise_for_status()

    with open(installer_path, "wb") as f:
        for chunk in response.iter_content(8192):
            f.write(chunk)

    print("Running Forge installer (this may take a minute or two)...")

    # 2. Run installer
    # Note: 'java' must be in your system PATH and be the correct version for the MC release
    subprocess.run(
        [
            "java",
            "-jar",
            "forge-installer.jar",
            "--installServer"
        ],
        cwd=server_dir,
        check=True
    )

    # 3. Handle generated files based on Forge version
    # Exclude the installer jar from our search
    legacy_jars = glob.glob(os.path.join(server_dir, "forge-*.jar"))
    legacy_jars = [j for j in legacy_jars if "installer" not in j]

    run_sh = os.path.join(server_dir, "run.sh")
    run_bat = os.path.join(server_dir, "run.bat")

    if legacy_jars:
        # Legacy Forge (1.16.5 and older): Single JAR workflow
        shutil.copy2(legacy_jars[0], os.path.join(server_dir, "server.jar"))
        print("Legacy Forge installed. 'server.jar' successfully created.")
        
    elif os.path.exists(run_sh) or os.path.exists(run_bat):
        # Modern Forge (1.17+): Script workflow
        print("\n--- MODERN FORGE DETECTED ---")
        print("Note: Modern Forge does NOT use a single 'server.jar'.")
        print("To start this server, your execution logic must trigger 'run.sh' (Linux/Mac) or 'run.bat' (Windows).")
        print("-----------------------------\n")
        
    else:
        raise Exception("Could not find Forge server jar or run scripts after installation.")

    # 4. Clean up installer payload
    if os.path.exists(installer_path):
        os.remove(installer_path)

    print(f"Forge {version} installation complete.")

# ----------------------------
# SPIGOT
# ----------------------------

def get_spigot_url(version):

    return (
        "https://download.getbukkit.org/spigot/"
        f"spigot-{version}.jar"
    )


def install_spigot(server_dir, version):

    url = get_spigot_url(version)

    server_jar = os.path.join(
        server_dir,
        "server.jar"
    )

    response = requests.get(
        url,
        stream=True
    )

    response.raise_for_status()

    with open(server_jar, "wb") as f:
        for chunk in response.iter_content(8192):
            f.write(chunk)

    print("Spigot installed.")

# ----------------------------
# CONFIG FILES
# ----------------------------
def setup_server_properties(folder, port, desc, max_players=20, map_name=None, config=None):
    print(config)

    props_path = os.path.join(folder, "server.properties")
    props = {}
    if config:
        with open(props_path, "w", encoding='utf-8') as f:
            f.write(config)
        return
    if os.path.exists(props_path):

        with open(
            props_path,
            'r',
            encoding='utf-8',
            errors='ignore'
        ) as f:

            for line in f:

                if '=' in line and not line.strip().startswith('#'):

                    k, v = line.strip().split('=', 1)
                    props[k.strip()] = v.strip()

    props['server-port'] = str(port)
    props['max-players'] = str(max_players)
    props['motd'] = desc
    props['online-mode'] = 'true'
    props['enable-command-block'] = 'true'
    props['view-distance'] = '10'
    if map_name: props['level-name'] = map_name

    with open(props_path, "w", encoding='utf-8') as f:

        for key, val in props.items():
            f.write(f"{key}={val}\n")

def normalize_server_type(server_type):

    if server_type is None:
        return None

    if str(server_type).isdigit():
        return str(server_type)

    lookup = {
        "vanilla": "1",
        "paper": "2",
        "purpur": "3",
        "fabric": "4",
        "forge": "5",
        "spigot": "6",
        "neoforge": "7"
    }

    result = lookup.get(
        str(server_type).lower()
    )

    if result is None:
        raise Exception(
            f"Unknown server type: {server_type}"
        )

    return result

def create_eula(folder):

    with open(
        os.path.join(folder, "eula.txt"),
        "w"
    ) as f:

        f.write("eula=true\n")
        
def delete_plugin_and_data(
    sid,
    filename
):

    server_folder = os.path.join(
        BASE_DIR,
        str(sid)
    )

    plugin_name = (
        Path(filename)
        .stem
        .replace(".disabled","")
    )

    for root in [
        os.path.join(
            server_folder,
            "plugins"
        ),
        os.path.join(
            server_folder,
            "mods"
        )
    ]:

        if not os.path.isdir(root):
            continue

        full_file = os.path.join(
            root,
            filename
        )

        if os.path.isfile(full_file):
            os.remove(full_file)

        for item in os.listdir(root):

            full = os.path.join(
                root,
                item
            )

            if (
                os.path.isdir(full)
                and item.lower().startswith(
                    plugin_name.lower()
                )
            ):
                shutil.rmtree(
                    full,
                    ignore_errors=True
                )
        
def apply_plugin_states(sid, plugin_states):

    roots = [
        f"minecraft_servers/{sid}/plugins",
        f"minecraft_servers/{sid}/mods"
    ]

    for plugin in plugin_states:

        filename = plugin["path"]
        print(filename)
        enabled = plugin["enabled"]

        for root in roots:

            enabled_file = os.path.join(
                root,
                filename.replace(
                    ".disabled",
                    ""
                )
            )

            disabled_file = (
                enabled_file +
                ".disabled"
            )

            # Should be enabled
            if enabled:

                if os.path.exists(
                    disabled_file
                ):
                    os.rename(
                        disabled_file,
                        enabled_file
                    )

            # Should be disabled
            else:

                if os.path.exists(
                    enabled_file
                ):
                    os.rename(
                        enabled_file,
                        disabled_file
                    )
                    
def install_server_software(folder, choice, version):
    try:
        global url
        choice = str(choice)
        jar_path = os.path.join(folder, "server.jar")

        if os.path.exists(jar_path):
            os.remove(jar_path)

        # FIX: Initialize url as None at the top of the function scope.
        # If any logging code at the bottom references 'url', it will safely read 'None'
        # instead of crashing the program when Fabric/Forge runs.
        url = None 

        if choice == "1":
            url = get_vanilla_url(version)
            print('URL FOR DOWNLOAD: ', url)
            download(url, jar_path)

        elif choice == "2":
            url = get_paper_url(version)
            print('URL FOR DOWNLOAD: ', url)
            download(url, jar_path)

        elif choice == "3":
            url = get_purpur_url(version)
            print('URL FOR DOWNLOAD: ', url)
            download(url, jar_path)

        elif choice == "4":
            install_fabric(folder, version)

        elif choice == "5":
            install_forge(folder, version)

        elif choice == "6":
            install_spigot(folder, version)

        elif choice == "7":
            install_neoforge(folder, version)

        else:
            raise Exception("Invalid server type")

        #traceback.print_exc()

        # If you have something like this at the bottom of your function, it is now safe:
        if url:
            print(f"Direct download tracking completed for URL: {url}")
            
    except Exception as e:
        print(e)

# ------------------------------------------------
# SLEEPING SERVER STARTER
# ------------------------------------------------

def setup_auto_start(
    server_dir,
    ram="2G",
    port=25565
):
    """
    Installs MC Sleeping Server Starter into a server folder.
    """

    if sys.platform.startswith("win"):
        binary_name = "mcsleepingserverstarter-windows-amd64.exe"

    elif sys.platform.startswith("linux"):
        binary_name = "mcsleepingserverstarter-linux-amd64"

    else:
        return None

    binary_path = os.path.join(
        server_dir,
        binary_name
    )

    # Download wrapper if missing
    if not os.path.exists(binary_path):

        print(
            "Downloading Sleeping Server Starter..."
        )

        release_url = (
            "https://github.com/a-h/MC-Sleeping-Server-Starter/releases/latest/download/"
            + binary_name
        )

        urllib.request.urlretrieve(
            release_url,
            binary_path
        )

        if not sys.platform.startswith("win"):
            os.chmod(binary_path, 0o755)

    # ------------------------------------------------
    # Startup script
    # ------------------------------------------------

    if sys.platform.startswith("win"):

        start_script = os.path.join(
            server_dir,
            "start.bat"
        )

        with open(
            start_script,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                f'java -Xms{ram} -Xmx{ram} -jar server.jar nogui\n'
            )

    else:

        start_script = os.path.join(
            server_dir,
            "start.sh"
        )

        with open(
            start_script,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                f'#!/bin/bash\njava -Xms{ram} -Xmx{ram} -jar server.jar nogui\n'
            )

        os.chmod(start_script, 0o755)

    # ------------------------------------------------
    # Config
    # ------------------------------------------------

    config = {
        "settings": {
            "serverStartCommand":
                "start.bat"
                if sys.platform.startswith("win")
                else "./start.sh",

            "serverStopCommand": "stop",

            "serverPort": port,

            "countdownBeforeStop": 600,

            "maxConnectionAttempts": 20,

            "messages": {
                "serverStarting":
                    "Server is starting, reconnect in a moment.",
                "serverMaintenance":
                    "Server is under maintenance."
            }
        }
    }

    with open(
        os.path.join(server_dir, "config.json"),
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            config,
            f,
            indent=4
        )

    return binary_path


def launch_sleeping_wrapper(
    server_dir
):
    """
    Starts the sleeping wrapper.
    """

    files = os.listdir(server_dir)

    binary = None

    for f in files:

        if "mcsleepingserverstarter" in f.lower():
            binary = os.path.join(
                server_dir,
                f
            )
            break

    if not binary:
        raise Exception(
            "Sleeping starter not installed"
        )

    return subprocess.Popen(
        [binary],
        cwd=server_dir
    )
def edit_server(
    sid,
    name=None,
    ram=None,
    desc=None,
    max_players=None,
    version=None,
    server_type=None,
    icon_path=None,
    map_path=None,
    plugins_mods_path=None,
    server_properties=None,
    twenty47=None,
    plugin_states=None,
    deleted_plugins=None,
    auto_start_on_join=False,
):

    sid = str(sid)
    print(plugin_states)
    with open("server-config.json", "r") as f:
        data = json.load(f)

    if sid not in data:
        raise Exception("Server not found")

    server = data[sid]

    folder = os.path.join(
        BASE_DIR,
        sid
    )
    def normalize_type(t):
        if t is None:
            return None
        t = str(t).lower()
        if t.isdigit():
            return t
        return str(server_types2.index(t) + 1)
        
    def type_id_to_name(tid):
        return server_types[int(tid) - 1]

    def type_name_to_id(name):
        name = str(name).lower()
        return str(server_types.index(name) + 1)
    if not os.path.exists(folder):
        raise Exception(
            f"Server folder not found: {folder}"
        )
    version_changed = \
    (
        version is not None
        and version != server["version"]
    )
    

    if server_type is not None:
        server_type = normalize_type(server_type)

    type_changed = (
        server_type is not None
        and server_type != server["type"]
    )
    
    #print(server_types2.index(server_type.lower())+1,server["type"])
    #print(, server['type'], type_changed, "MAKE THIS VERSION WORK LIKE WHY IS IT NOOOWWWSAzFE")
    
    #if server_type is not None:
    #    server_type = str(server_type)
    # ----------------------------
    # BASIC SETTINGS
    # ----------------------------

    if name is not None:
        server["name"] = name

    if ram is not None:
        server["ram"] = ram

    if desc is not None:
        server["desc"] = desc

    if max_players is not None:
        server["max-players"] = max_players

    if twenty47 is not None:
        server["twenty47"] = twenty47

    # ----------------------------
    # SERVER.PROPERTIES
    # ----------------------------

    if (
        desc is not None
        or max_players is not None
        or server_properties is not None
    ):

        setup_server_properties(
            folder,
            server["port"],
            server.get("desc", ""),
            max_players=server.get(
                "max-players",
                20
            ),
            config=server_properties
        )

    # ----------------------------
    # ICON
    # ----------------------------

    if icon_path and os.path.exists(icon_path):

        server_icon = os.path.join(
            folder,
            "server-icon.png"
        )

        preview_icon = (
            f"server-imgs/{sid}.png"
        )

        success = process_server_icon(
            icon_path,
            server_icon
        )

        if success:
            shutil.copy2(
                server_icon,
                preview_icon
            )

    # ----------------------------
    # CHANGE VERSION
    # ----------------------------

    if (
        version is not None
        and version != server["version"]
    ):
    
        valid_versions = get_versions(
            server["type"]
        )
    
        if (
            version not in valid_versions
            and server["type"] != "2"
        ):
            raise Exception(
                f"Version {version} is not supported"
            )
    
        if version_changed:
            install_server_software(folder, server["type"], version)
            server["version"] = version
    
        server["version"] = version
    
    # ----------------------------
    # CHANGE SERVER TYPE
    # ----------------------------

    if (
        server_type is not None
        and str(server_type)
        != str(server["type"])
    ):

        server_type = str(server_type)

        valid_versions = get_versions(
            server_type
        )

        current_version = server["version"]

        if (
            current_version
            not in valid_versions
            and server_type != "2"
        ):
            raise Exception(
                f"{current_version} is not "
                f"supported by "
                f"{type_id_to_name(server['type'])}"
            )

    if type_changed:
        backup_dir = os.path.join(folder, "_migration_backup")
        os.makedirs(backup_dir, exist_ok=True)
    
        for item in ["plugins", "mods", "config"]:
            src = os.path.join(folder, item)
            if os.path.exists(src):
                dst = os.path.join(backup_dir, item)
                shutil.copytree(src, dst, dirs_exist_ok=True)
    
        install_server_software(folder, server_type, server["version"])
        server["type"] = server_type

    # ----------------------------
    # IMPORT MODS / PLUGINS
    # ----------------------------
    if plugin_states:
        apply_plugin_states(
            sid,
            plugin_states
        )
    if deleted_plugins:

        for plugin in deleted_plugins:
        
            delete_plugin_and_data(
                sid,
                plugin
            )
    if (
        plugins_mods_path
        and os.path.exists(
            plugins_mods_path
        )
    ):

        backend = server_types[
            int(server["type"]) - 1
        ].lower()

        target_name = (
            "mods"
            if backend in [
                "fabric",
                "forge",
                "neoforge"
            ]
            else "plugins"
        )

        target_dir = os.path.join(
            folder,
            target_name
        )

        os.makedirs(
            target_dir,
            exist_ok=True
        )

        contents = os.listdir(
            plugins_mods_path
        )

        if (
            len(contents) == 1
            and os.path.isdir(
                os.path.join(
                    plugins_mods_path,
                    contents[0]
                )
            )
            and contents[0].lower()
            == target_name
        ):

            plugins_mods_path = os.path.join(
                plugins_mods_path,
                contents[0]
            )

        for item in os.listdir(
            plugins_mods_path
        ):

            src = os.path.join(
                plugins_mods_path,
                item
            )

            dst = os.path.join(
                target_dir,
                item
            )

            if os.path.isdir(src):

                shutil.copytree(
                    src,
                    dst,
                    dirs_exist_ok=True
                )

            else:

                shutil.copy2(
                    src,
                    dst
                )

    # ----------------------------
    # REPLACE WORLD
    # ----------------------------

    if (
        map_path
        and os.path.exists(map_path)
    ):

        for world in [
            "world",
            "world_nether",
            "world_the_end"
        ]:

            path = os.path.join(
                folder,
                world
            )

            if os.path.exists(path):

                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)

        if os.path.isdir(map_path):

            shutil.copytree(
                map_path,
                folder,
                dirs_exist_ok=True
            )

        elif map_path.lower().endswith(
            ".zip"
        ):

            with zipfile.ZipFile(
                map_path,
                "r"
            ) as zip_ref:

                zip_ref.extractall(
                    folder
                )

    # ----------------------------
    # SAVE CONFIG
    # ----------------------------

    with open(
        "server-config.json",
        "w"
    ) as f:

        json.dump(
            data,
            f,
            indent=4
        )

    return True
# ----------------------------
# MAIN SERVER CREATOR
# ----------------------------
def create_server(
    choice,
    name,
    version,
    ram,
    max_players,
    user=None,
    desc="A super duper fun MC server",
    icon_path=None,
    map_path=None,
    import_zip_path=None,
    plugins_mods_path=None,
    server_properties=None,
    twenty47=False,
    auto_start_on_join=False,
):

    global globalnum

    
    jsonFile='server-config.json'
    if not os.path.exists(jsonFile) or os.path.getsize(jsonFile) == 0:
        data = {}
    else:
        with open(jsonFile, 'r') as file:
            try:
                data = json.load(file)

                if not isinstance(data, dict):
                    data = {}
            except json.JSONDecodeError:
                data = {}
    
    next_id = str(len(data) + 1)
    globalnum = int(next_id)


    print("CHOICE:", choice)

    choice = str(choice)

    valid_versions = get_versions(choice)

    if version not in valid_versions and not choice == '2':
        raise Exception(
            f"Version '{version}' is not supported "
            f"for server type {server_types[int(choice)-1]}"
        )

    folder = os.path.join(
        BASE_DIR,
        str(globalnum)
    )

    mkdir(folder)

    print(f"Creating server in: {folder}")

    # ----------------------------
    # IMPORT ZIP
    # ----------------------------
    # ----------------------------
    # IMPORT ZIP
    # ----------------------------
    # ----------------------------
    # PLUGINS / MODS
    # ----------------------------
    if plugins_mods_path:

        backend = server_types[int(choice)-1].lower()

        target_name = (
            "mods"
            if backend in ["fabric", "forge", "neoforge"]
            else "plugins"
        )

        target_dir = os.path.join(folder, target_name)

        os.makedirs(target_dir, exist_ok=True)

        print("IMPORTING:", plugins_mods_path)
        print("CONTENTS:", os.listdir(plugins_mods_path))

        # Handle uploads that contain an extra plugins/ or mods/ folder
        contents = os.listdir(plugins_mods_path)

        if (
            len(contents) == 1
            and os.path.isdir(
                os.path.join(
                    plugins_mods_path,
                    contents[0]
                )
            )
            and contents[0].lower() == target_name
        ):
            plugins_mods_path = os.path.join(
                plugins_mods_path,
                contents[0]
            )

            print(
                f"Detected nested {target_name} folder, flattening import."
            )

        for item in os.listdir(plugins_mods_path):

            src = os.path.join(
                plugins_mods_path,
                item
            )

            dst = os.path.join(
                target_dir,
                item
            )

            if os.path.isdir(src):

                shutil.copytree(
                    src,
                    dst,
                    dirs_exist_ok=True
                )

            else:

                shutil.copy2(
                    src,
                    dst
                )

        print(
            f"Imported {target_name} from {plugins_mods_path}"
        )
    if import_zip_path:
    
        if (
            os.path.exists(import_zip_path)
            and import_zip_path.lower().endswith('.zip')
        ):
    
            print(f"Extracting: {import_zip_path}")
    
            with tempfile.TemporaryDirectory() as temp_dir:
            
                with zipfile.ZipFile(
                    import_zip_path,
                    'r'
                ) as zip_ref:
    
                    zip_ref.extractall(temp_dir)
    
                src_dir = temp_dir
    
                contents = os.listdir(src_dir)
    
                # handle nested folder zips
                if (
                    len(contents) == 1
                    and os.path.isdir(
                        os.path.join(src_dir, contents[0])
                    )
                ):
    
                    src_dir = os.path.join(
                        src_dir,
                        contents[0]
                    )
    
                # ----------------------------
                # SAFE IMPORTS ONLY
                # ----------------------------
                allowed_folders = [
                    "world",
                    "world_nether",
                    "world_the_end",
                    "plugins",
                    "mods",
                    "config"
                ]
    
                allowed_files = [
                    "server.properties",
                    "ops.json",
                    "whitelist.json",
                    "banned-ips.json",
                    "banned-players.json"
                ]
    
                for item in os.listdir(src_dir):
                
                    src_item = os.path.join(src_dir, item)
                    dst_item = os.path.join(folder, item)
    
                    # skip dangerous files
                    dangerous = [
                        "server.jar",
                        "eula.txt",
                        "run.bat",
                        "run.sh",
                        "user_jvm_args.txt"
                    ]
    
                    if item in dangerous:
                        print(f"Skipping dangerous file: {item}")
                        continue
                    
                    # copy allowed folders
                    if (
                        os.path.isdir(src_item)
                        and item in allowed_folders
                    ):
    
                        shutil.copytree(
                            src_item,
                            dst_item,
                            dirs_exist_ok=True
                        )
    
                        print(f"Imported folder: {item}")
    
                    # copy allowed files
                    elif (
                        os.path.isfile(src_item)
                        and item in allowed_files
                    ):
    
                        shutil.copy2(src_item, dst_item)
    
                        print(f"Imported file: {item}")
    
    # ----------------------------
    # DOWNLOAD SERVER SOFTWARE
    # ----------------------------
    jar_path = os.path.join(folder, "server.jar")

    # ----------------------------
    # DOWNLOAD SERVER SOFTWARE
    # ----------------------------
    jar_path = os.path.join(folder, "server.jar")
    url = None
    if choice == "1":

        url = get_vanilla_url(version)

        print("FINAL DOWNLOAD URL:", url)

        download(url, jar_path)

    elif choice == "2":

        url = get_paper_url(version)

        print("FINAL DOWNLOAD URL:", url)

        download(url, jar_path)

    elif choice == "3":

        url = get_purpur_url(version)

        print("FINAL DOWNLOAD URL:", url)

        download(url, jar_path)

    elif choice == "4":

        print("Installing Fabric...")

        install_fabric(folder, version)

    elif choice == "5":

        print("Installing Forge...")

        install_forge(folder, version)

    elif choice == "6":

        print("Installing Spigot...")

        install_spigot(folder, version)
    
    elif choice == "7":

        print("Installing NeoForge...")

        install_neoforge(folder, version)

    else:
        raise Exception("Invalid server type")

    #print("FINAL DOWNLOAD URL:", url)
#
    #download(url, jar_path)
    
    if ("url" in locals() and url != None):
        print("FINAL DOWNLOAD URL:", url)
        download(url, jar_path)

    # ----------------------------
    # CONFIG FILES
    # ----------------------------
    assigned_port = 25564 + globalnum
    
    if map_path:
        map_name=Path(map_path).stem
    else:
        map_name=None

    setup_server_properties(
        folder,
        assigned_port,
        desc,
        max_players=max_players,
        map_name=map_name,
        config=server_properties
    )

    create_eula(folder)
    #if auto_start_on_join:
#
    #    setup_auto_start(
    #        folder,
    #        ram=ram,
    #        port=assigned_port
    #    )

    # ----------------------------
    # ICON
    # ----------------------------
    if not icon_path or not os.path.exists(icon_path):
        icon_path="default.png"

    server_icon_path = os.path.join(folder, "server-icon.png")
    preview_icon_path = f"server-imgs/{globalnum}.png"
    success = process_server_icon(icon_path, server_icon_path)
    if success:
        # also save preview copy
        shutil.copy(server_icon_path, preview_icon_path)
        print("Server icon processed successfully")
    else:
        print("No valid icon provided or failed processing")

    # ----------------------------
    # CUSTOM WORLD
    # ----------------------------
    if map_path and os.path.exists(map_path):

        world_target_dir = os.path.join(folder)

        if os.path.isdir(map_path):

            shutil.copytree(
                map_path,
                world_target_dir,
                dirs_exist_ok=True
            )

        elif map_path.lower().endswith(".zip"):

            with zipfile.ZipFile(map_path, 'r') as zip_ref:
                zip_ref.extractall(world_target_dir)
                
        os.remove(map_path)

# Create a Path object from your file path string
        file_path = Path(map_path)

# Use .parent to get the containing folder
        folder_path = file_path.parent

# Output: /home/user/documents

        os.rmdir(folder_path)
        
    server_uuid = str(uuid.uuid4())

    appendjson("server-config.json", {
        "uuid": server_uuid,
        "name": name,
        "port": 25564 + globalnum,
        "ram": ram,
        "version": version,
        "type": str(choice),
        "max-players": max_players,
        "status": "Offline",
        "desc": desc,
        "created-by":user,
        "node": "main",
        "twenty47": twenty47,
        "auto-start-on-join": auto_start_on_join,
    })

    print("\n=== DONE ===")
    print(f"Server deployed at: {folder}")
    print(f"Port: {assigned_port}")


# ----------------------------
# TEST
# ----------------------------
if __name__ == "__main__":

    print(get_versions("2"))

    create_server(
        choice="2",
        name="Paper Test",
        version="1.20.4",
        ram="4G",
        max_players=20,
        desc="A PaperMC test server"
    )