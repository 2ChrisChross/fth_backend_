import shutil
import sqlite3
import tempfile
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TILE_ARCHIVE_URL = (
    "https://data.bbbike.org/osm/mbtiles/region/asia/philippines/"
    "philippines.osm.mbtiles-shortbread.zip"
)
TILE_ARCHIVE_MEMBER = "philippines-mbtiles-shortbread/philippines.mbtiles"


def validate_tiles(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        format_row = db.execute(
            "SELECT value FROM metadata WHERE name = 'format'"
        ).fetchone()
        low_zoom = db.execute(
            "SELECT 1 FROM tiles WHERE zoom_level = 0 LIMIT 1"
        ).fetchone()
        high_zoom = db.execute(
            "SELECT 1 FROM tiles WHERE zoom_level = 14 LIMIT 1"
        ).fetchone()
    if format_row != ("pbf",) or not low_zoom or not high_zoom:
        raise CommandError(
            "The map file is not a complete zoom 0-14 PBF tile database."
        )


class Command(BaseCommand):
    help = "Download the Philippines Shortbread tile archive for the simulator map."

    def handle(self, *args, **options):
        maplibre_dir = settings.BASE_DIR / "node_modules" / "maplibre-gl" / "dist"
        for name in ("maplibre-gl.js", "maplibre-gl.css"):
            if not (maplibre_dir / name).is_file():
                raise CommandError("MapLibre assets are missing. Run npm ci first.")

        target = settings.BASE_DIR / "local_map_data" / "philippines.mbtiles"
        try:
            if target.exists():
                validate_tiles(target)
                self.stdout.write(f"Using existing simulator tiles at {target}.")
                return

            target.parent.mkdir(parents=True, exist_ok=True)
            self.stdout.write("Downloading the Philippines map archive; this is large.")
            with tempfile.TemporaryDirectory(dir=target.parent) as temp_dir:
                archive_path = Path(temp_dir) / "tiles.zip"
                output_path = Path(temp_dir) / "tiles.mbtiles"
                with urllib.request.urlopen(TILE_ARCHIVE_URL, timeout=60) as response:
                    with archive_path.open("wb") as file:
                        shutil.copyfileobj(response, file, length=1024 * 1024)
                with zipfile.ZipFile(archive_path) as archive:
                    matches = [
                        entry
                        for entry in archive.infolist()
                        if entry.filename == TILE_ARCHIVE_MEMBER
                    ]
                    if len(matches) != 1:
                        raise CommandError("The map archive has an unexpected layout.")
                    with (
                        archive.open(matches[0]) as source,
                        output_path.open("wb") as output,
                    ):
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                validate_tiles(output_path)
                target.hardlink_to(output_path)
        except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
            raise CommandError(
                f"Could not prepare simulator map assets: {exc}"
            ) from exc
        self.stdout.write(self.style.SUCCESS(f"Simulator tiles installed at {target}."))
