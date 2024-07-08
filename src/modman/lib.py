import hashlib
import logging
import threading
import zipfile
from urllib.parse import urlparse

import httpx
import toml
from click import Abort
from rich import print
from rich.progress import Progress, DownloadColumn, TransferSpeedColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich.prompt import IntPrompt, Confirm, Prompt
from .api import ModrinthAPI
from .models import *
from pathlib import Path
from pydantic import BaseModel


def _download_progress():
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
)


class FabricGameVersion(BaseModel):
    version: str
    stable: bool


class DownloadThread(threading.Thread):
    def __init__(
            self,
            url: str,
            target: Path,
            *,
            hashes: VersionFile.Hashes = None,
            progress: Progress = None,
    ):
        super().__init__()
        self.url = url
        self.target = target
        self.progress = progress
        self.hashes = hashes
        self.log = logging.getLogger("modman.runtime.download_thread")
        self.success = False

    def run(self):
        with httpx.Client() as client:
            task_id = None

            response = client.head(self.url)
            response.raise_for_status()
            file_name = urlparse(response.url.path.split("/")[-1])
            total = int(response.headers["Content-Length"])

            if self.progress:
                task_id = self.progress.add_task(f"{file_name}", total=total)

            for i in range(3):
                sha512sum = hashlib.new("sha512")
                with client.stream("GET", self.url) as response:
                    self.target.touch()
                    with open(self.target, "wb") as f:
                        for chunk in response.iter_bytes():
                            sha512sum.update(chunk)
                            f.write(chunk)
                            if self.progress:
                                self.progress.update(task_id, advance=len(chunk))
                if not self.hashes:
                    self.log.warning(f"Did not have a hash to check against for {self.target}. Skipping verification.")
                    break
                elif sha512sum.hexdigest() != self.hashes.sha512:
                    self.log.warning(f"Corrupted download for {self.url}, retrying ({i+1}/3)")
                    continue
                else:
                    self.log.info(f"SHA512 hash for {self.target.name} matches.")
                    break
            else:
                raise RuntimeError(f"Failed to download {self.url} after 3 attempts (hash mismatch).")


class Runtime:
    def __init__(self):
        self.log = logging.getLogger("modman.runtime")
        self.api = ModrinthAPI()

    @staticmethod
    def find_config(start: Path = None) -> Path | None:
        start = start or Path.cwd()
        for path in start.parents:
            if (path / "modman.toml").exists():
                return path / "modman.toml"

    @staticmethod
    def load_config() -> dict:
        config_file = Runtime.find_config(Path.cwd())
        if not config_file:
            raise FileNotFoundError("Could not find modman.toml in current directory or any parent directories.")
        return toml.load(config_file)

    @staticmethod
    def save_config(new: dict) -> dict:
        config_file = Runtime.find_config(Path.cwd())
        if not config_file:
            config_file = Path.cwd() / "modman.toml"
        with open(config_file, "w") as f:
            toml.dump(new, f)
        return new

    def download_fabric(self, root_dir: Path):
        with httpx.Client(base_url="https://meta.fabricmc.net/v2/versions") as client:
            available_game_versions = client.get("/game").json()  # [{"version": "1.20.4", "stable": true}]
            available_loader_versions: list[dict[str, str | bool]] = client.get("/loader").json()
            available_installer_versions = client.get("/installer").json()

        stable = True
        while True:
            minecraft_version = Prompt.ask("Which minecraft version do you want to download (e.g. 1.20.4, 24w21b)")
            if minecraft_version not in [x["version"] for x in available_game_versions]:
                print(f"[red]Minecraft version {minecraft_version} is not available.")
                continue
            for version in available_game_versions:
                if version["version"] == minecraft_version:
                    stable = version["stable"]
                    break
            break

        while True:
            default_loader = available_loader_versions[0]
            real_loaders = [x for x in available_loader_versions if x["stable"] in [True, stable]]
            loader_version = Prompt.ask(
                "Which fabric loader version do you want to download?",
                default=default_loader["version"],
                choices=[x["version"] for x in real_loaders[:10]],  # only choose from the 10 latest versions
            )



    def init(self):
        config = {
            "game": {},
            "mods": {}
        }
        print(f"Searching for a fabric server jar file in {Path.cwd()}")

        for file in Path.cwd().glob("*.jar"):
            try:
                with zipfile.ZipFile(file) as zf:
                    if "install.properties" in zf.namelist():
                        with zf.open("install.properties") as f:
                            parsed_properties = {}
                            for line in f.readlines():
                                key, value = line.decode("utf-8").strip().split("=")
                                parsed_properties[key] = value
            except zipfile.BadZipFile:
                continue
            else:
                print(f"Found fabric server jar file: {file.name}")
                config["game"]["fabric_server"] = {
                    "file": file.name,
                    "versions": {
                        "fabric-loader": parsed_properties["fabric-loader-version"],
                        "game-version": parsed_properties["game-version"],
                    }
                }
                print(
                    "Detected fabric loader version %r and minecraft version %r" % (
                        parsed_properties["fabric-loader-version"],
                        parsed_properties["game-version"]
                    )
                )
                break
        else:
            print("[red]Could not find a fabric server jar file - starting download procedure instead.")
