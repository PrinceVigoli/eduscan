import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def main() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        raise SystemExit("Use pg_dump for PostgreSQL production backups.")
    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"eduscan-{timestamp}.zip"
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "eduscan.db"
        with closing(sqlite3.connect(database_path)) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database/eduscan.db")
            upload_root = Path(settings.upload_dir)
            if upload_root.is_dir():
                for file in upload_root.rglob("*"):
                    if file.is_file():
                        archive.write(file, Path("uploads") / file.relative_to(upload_root))
    print(f"Backup created: {destination.resolve()}")


if __name__ == "__main__":
    main()
