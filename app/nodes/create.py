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

server_types=["vanilla", "paper", "purpur", "fabric", "forge", "spigot", "neoforge"]

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

    converted = convert_version_for_paper(version)

    # snapshots/pre-releases should use vanilla
    if converted["software"] != "paper":
        raise Exception(
            f"{version} is not supported by PaperMC"
        )

    version = converted["paper_version"]

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

def get_fabric_url(version):

    loader_version = "0.15.11"
    installer_version = "1.0.1"

    return (
        f"https://meta.fabricmc.net/v2/versions/loader/"
        f"{version}/{loader_version}/{installer_version}/server/jar"
    )


def install_fabric(server_dir, version):

    url = get_fabric_url(version)

    server_jar = os.path.join(server_dir, "server.jar")

    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(server_jar, "wb") as f:
        for chunk in response.iter_content(8192):
            f.write(chunk)

    print("Fabric installed.")


# ----------------------------
# FORGE
# ----------------------------

def get_forge_url(version):

    data = requests.get(
        "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
    ).json()

    promos = data["promos"]

    key = f"{version}-latest"

    if key not in promos:
        raise Exception(
            f"No Forge build found for {version}"
        )

    forge_version = promos[key]

    return (
        f"https://maven.minecraftforge.net/net/minecraftforge/"
        f"forge/{version}-{forge_version}/"
        f"forge-{version}-{forge_version}-installer.jar"
    )


def install_forge(server_dir, version):

    installer_url = get_forge_url(version)

    installer_path = os.path.join(
        server_dir,
        "forge-installer.jar"
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

    print("Running Forge installer...")

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

    # Find generated forge jar
    forge_jars = glob.glob(
        os.path.join(server_dir, "forge-*-shim.jar")
    )

    if not forge_jars:
        forge_jars = glob.glob(
            os.path.join(server_dir, "forge-*.jar")
        )

    if not forge_jars:
        raise Exception(
            "Could not find Forge server jar"
        )

    # Copy to server.jar
    shutil.copy2(
        forge_jars[0],
        os.path.join(server_dir, "server.jar")
    )

    print("Forge installed.")

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


def create_eula(folder):

    with open(
        os.path.join(folder, "eula.txt"),
        "w"
    ) as f:

        f.write("eula=true\n")


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
    twenty47=False
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

        if backend in ["fabric", "forge", "neoforge"]:
            target_name = "mods"
        else:
            target_name = "plugins"

        target_dir = os.path.join(folder, target_name)

        os.makedirs(target_dir, exist_ok=True)

        for item in os.listdir(plugins_mods_path):

            src = os.path.join(plugins_mods_path, item)
            dst = os.path.join(target_dir, item)

            if os.path.isdir(src):
                shutil.copytree(
                    src,
                    dst,
                    dirs_exist_ok=True
                )
            else:
                shutil.copy2(src, dst)

        print(f"Imported {target_name} from {plugins_mods_path}")
        
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

    print("FINAL DOWNLOAD URL:", url)

    download(url, jar_path)

    # ----------------------------
    # CONFIG FILES
    # ----------------------------
    assigned_port = 25564 + globalnum
    
    if map_path:
        map_name=Path(map_path).name
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

    # ----------------------------
    # ICON
    # ----------------------------

    # ----------------------------
    # ICON
    # ----------------------------
    if not icon_path or not os.path.exists(icon_path):
        icon_path="server-imgs/default.png"

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
        "type": choice,
        "max-players": max_players,
        "status": "Offline",
        "desc": desc,
        "created-by":user,
        "twenty47": twenty47,
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