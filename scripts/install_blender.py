"""Install a checksum-verified portable Blender runtime without sudo (Linux x64)."""

import hashlib
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "4.5.3"
BASE_URL = "https://download.blender.org/release/Blender4.5/"
ARCHIVE = f"blender-{VERSION}-linux-x64.tar.xz"


def main() -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("This installer supports Linux x86_64 only.")
    destination = Path(__file__).resolve().parents[1] / ".runtime/blender"
    if destination.exists():
        raise FileExistsError("Runtime already exists; review it before replacing it.")
    with urllib.request.urlopen(
        BASE_URL + f"blender-{VERSION}.sha256", timeout=30
    ) as response:
        checksums = response.read(100_000).decode()
    expected = next(
        line.split()[0] for line in checksums.splitlines() if line.endswith(ARCHIVE)
    )
    with tempfile.TemporaryDirectory(prefix="studio-install-") as directory:
        archive = Path(directory) / ARCHIVE
        with (
            urllib.request.urlopen(BASE_URL + ARCHIVE, timeout=30) as response,
            archive.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(
                "Blender archive checksum does not match the official manifest."
            )
        with tarfile.open(archive) as bundle:
            bundle.extractall(directory, filter="data")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(Path(directory) / f"blender-{VERSION}-linux-x64"), destination)
    print(f"Installed Blender {VERSION}: {destination / 'blender'}")


if __name__ == "__main__":
    main()
