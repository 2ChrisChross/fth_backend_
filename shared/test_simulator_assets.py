import io
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from shared.management.commands.prepare_simulator_assets import TILE_ARCHIVE_MEMBER


class PrepareSimulatorAssetsTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        renderer = self.base / "node_modules" / "maplibre-gl" / "dist"
        renderer.mkdir(parents=True)
        (renderer / "maplibre-gl.js").touch()
        (renderer / "maplibre-gl.css").touch()
        self.override = override_settings(BASE_DIR=self.base)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def archive(self):
        tile_file = self.base / "fixture.mbtiles"
        with closing(sqlite3.connect(tile_file)) as db, db:
            db.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
            db.execute("INSERT INTO metadata VALUES ('format', 'pbf')")
            db.execute("CREATE TABLE tiles (zoom_level INTEGER)")
            db.executemany("INSERT INTO tiles VALUES (?)", [(0,), (14,)])
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as file:
            file.writestr(TILE_ARCHIVE_MEMBER, tile_file.read_bytes())
        return archive.getvalue()

    @patch("shared.management.commands.prepare_simulator_assets.urllib.request.urlopen")
    def test_downloads_validates_and_reuses_tiles(self, urlopen):
        urlopen.return_value = io.BytesIO(self.archive())
        call_command("prepare_simulator_assets", stdout=io.StringIO())
        target = self.base / "local_map_data" / "philippines.mbtiles"
        self.assertTrue(target.is_file())
        urlopen.assert_called_once()
        call_command("prepare_simulator_assets", stdout=io.StringIO())
        urlopen.assert_called_once()

    @patch("shared.management.commands.prepare_simulator_assets.urllib.request.urlopen")
    def test_rejects_bad_archive_without_leaving_partial_tiles(self, urlopen):
        urlopen.return_value = io.BytesIO(b"not a zip archive")
        with self.assertRaises(CommandError):
            call_command("prepare_simulator_assets", stdout=io.StringIO())
        self.assertFalse(
            (self.base / "local_map_data" / "philippines.mbtiles").exists()
        )

    @patch("shared.management.commands.prepare_simulator_assets.urllib.request.urlopen")
    def test_missing_renderer_stops_before_downloading(self, urlopen):
        (
            self.base / "node_modules" / "maplibre-gl" / "dist" / "maplibre-gl.js"
        ).unlink()
        with self.assertRaises(CommandError):
            call_command("prepare_simulator_assets", stdout=io.StringIO())
        urlopen.assert_not_called()
