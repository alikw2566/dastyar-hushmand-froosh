import tempfile
import unittest
from pathlib import Path

from scripts.backup import create_backup
from scripts.restore import restore_backup


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "backups"
        self.source.mkdir()
        (self.source / "data.txt").write_text("safe fixture", encoding="utf-8")
        (self.source / ".env").write_text(
            "API_KEY=real-looking-secret", encoding="utf-8"
        )
        (self.source / "credentials.json").write_text(
            '{"token":"secret"}', encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_dry_run_does_not_create_archive_and_reports_secret_exclusions(self):
        result = create_backup(self.output, [("fixture", self.source)], dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.output.exists())
        excluded = {item["path"] for item in result["excluded_files"]}
        self.assertIn("payload/fixture/.env", excluded)
        self.assertIn("payload/fixture/credentials.json", excluded)

    def test_backup_integrity_and_restore(self):
        result = create_backup(self.output, [("fixture", self.source)])
        archive = Path(result["archive"])
        self.assertTrue(result["integrity_verified"])
        preview = restore_backup(archive, self.root / "preview")
        self.assertTrue(preview["dry_run"])
        restored = self.root / "restored"
        applied = restore_backup(archive, restored, apply=True)
        self.assertFalse(applied["dry_run"])
        self.assertEqual(
            (restored / "fixture" / "data.txt").read_text(encoding="utf-8"),
            "safe fixture",
        )
        self.assertFalse((restored / "fixture" / ".env").exists())

    def test_tampered_archive_fails_checksum(self):
        result = create_backup(self.output, [("fixture", self.source)])
        archive = Path(result["archive"])
        with archive.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(ValueError):
            restore_backup(archive, self.root / "restored")

    def test_keycloak_backup_requires_compose_and_is_reported(self):
        with self.assertRaises(ValueError):
            create_backup(
                self.output,
                [("fixture", self.source)],
                dry_run=True,
                include_keycloak=True,
            )
        compose = self.root / "compose.yml"
        compose.write_text("services: {}\n", encoding="utf-8")
        result = create_backup(
            self.output,
            [("fixture", self.source)],
            dry_run=True,
            include_keycloak=True,
            compose_file=compose,
        )
        self.assertTrue(result["include_keycloak"])


if __name__ == "__main__":
    unittest.main()
