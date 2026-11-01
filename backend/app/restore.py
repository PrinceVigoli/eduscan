import shutil
import tempfile
import zipfile
from pathlib import Path

from .config import settings


def main(archive_name: str) -> None:
    if not settings.database_url.startswith("sqlite:///"):
        raise SystemExit("Use pg_restore for PostgreSQL production restoration.")
    archive_path = Path(archive_name).resolve()
    backup_root = Path("backups").resolve()
    if backup_root not in archive_path.parents or not archive_path.is_file():
        raise SystemExit("Restore archive must be an existing file inside backend/backups.")
    if input("Type RESTORE to overwrite the local database and uploads: ") != "RESTORE":
        raise SystemExit("Restore cancelled.")
    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                member_path = (target / member.filename).resolve()
                if target.resolve() not in member_path.parents and member_path != target.resolve():
                    raise SystemExit("Backup contains an unsafe file path.")
                if not (member.filename == "database/eduscan.db" or member.filename.startswith("uploads/")):
                    raise SystemExit("Backup contains an unexpected file.")
            archive.extractall(target)
        restored_database = target / "database" / "eduscan.db"
        if not restored_database.is_file():
            raise SystemExit("Backup does not contain an EduScan database.")
        shutil.copy2(restored_database, database_path)
        restored_uploads = target / "uploads"
        if restored_uploads.is_dir():
            upload_root = Path(settings.upload_dir)
            upload_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(restored_uploads, upload_root, dirs_exist_ok=True)
    print("Restore completed.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.restore backups/eduscan-YYYYMMDDTHHMMSSZ.zip")
    main(sys.argv[1])
