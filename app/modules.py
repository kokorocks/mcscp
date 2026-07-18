from __future__ import annotations
import __main__

import importlib.util
import importlib.metadata
import sys
from pathlib import Path
from graphlib import TopologicalSorter
import subprocess
import re

try:
    import yaml
except ImportError:
    raise RuntimeError("Install PyYAML: pip install pyyaml")


class ModuleManager:

    def __init__(self, modules_folder="modules"):
        self.folder = Path(modules_folder)
        self.modules = {}
        self.info = {}

    def discover(self):
        discovered = {}

        for folder in self.folder.iterdir():
            if not folder.is_dir():
                continue

            manifest = folder / "module.yml"
            if not manifest.exists():
                continue

            data = yaml.safe_load(manifest.read_text())

            if not data.get("enabled", True):
                continue

            data["_folder"] = folder
            discovered[data["id"]] = data

        return discovered

    @staticmethod
    def _get_pipdeps(info):
        """
        Accepts either 'pip-depends' or 'pipdeps' as the manifest key,
        so existing module.yml files keep working either way.
        """
        return info.get("pip-depends") or info.get("pipdeps") or []

    @staticmethod
    def _is_installed(dep: str) -> bool:
        """
        Check whether a pip package is already installed, by checking
        installed distribution metadata (pip package name), not by
        trying to import it — since pip name and import name often
        differ (e.g. beautifulsoup4 -> bs4, pyyaml -> yaml).
        """
        # Strip version specifiers / extras: "pkg==1.0", "pkg[extra]>=2"
        name = re.split(r"[<>=!~\[]", dep, maxsplit=1)[0].strip()

        if not name:
            return False

        try:
            importlib.metadata.distribution(name)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False

    def _ensure_pipdeps_installed(self, info):
        """
        Blocks until every pipdep for this module is installed.
        subprocess.check_call() is synchronous, so execution will not
        continue past this method until pip finishes (or raises).
        """
        for dep in self._get_pipdeps(info):
            if self._is_installed(dep):
                continue

            print(f"[ModuleManager] Installing missing dependency: {dep}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])

            if not self._is_installed(dep):
                raise RuntimeError(
                    f"Dependency '{dep}' still not installed after pip install."
                )

    def load_all(self):
            discovered = self.discover()

            graph = {}
            for mid, info in discovered.items():
                graph[mid] = set(info.get("depends", []))

            order = list(TopologicalSorter(graph).static_order())

            # --- Phase 1: install ALL pip deps for ALL modules first ---
            for mid in order:
                self._ensure_pipdeps_installed(discovered[mid])

            # --- Phase 2: only now, import/exec each module ---
            for mid in order:
                info = discovered[mid]

                entry = info["_folder"] / info["entry"]
                folder_str = str(info["_folder"])

                spec = importlib.util.spec_from_file_location(mid, entry)
                module = importlib.util.module_from_spec(spec)

                sys.modules[mid] = module

                # Allow the module's own folder to be searched for sibling
                # imports (e.g. `import htmledit` sitting next to main.py).
                sys.path.insert(0, folder_str)
                try:
                    spec.loader.exec_module(module)
                finally:
                    sys.path.remove(folder_str)

                module.manager = self
                module.info = info
                module.path = info["_folder"]

                self.modules[mid] = module
                self.info[mid] = info

                if hasattr(module, "on_load"):
                    module.on_load(self)

    def module(self, name):
        return self.modules[name]

    def has(self, name):
        return name in self.modules

    def call(self, module, func, *args, **kwargs):
        obj = self.modules[module]
        return getattr(obj, func)(*args, **kwargs)

    def broadcast(self, func, *args, **kwargs):
        for module in self.modules.values():
            if hasattr(module, func):
                getattr(module, func)(*args, **kwargs)

    def unload(self):
        self.broadcast("on_unload")
        self.modules.clear()
        self.info.clear()
if hasattr(__main__, "app"):
    app = __main__.app
    #print(f'modules.py found app: {app}')
else:
    print("no")
#app = __main__.app
manager = ModuleManager()
manager.load_all()