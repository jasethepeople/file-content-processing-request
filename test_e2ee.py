from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.core.e2ee import E2EEManager, EncryptionError


class E2EEManagerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.manager = E2EEManager(
            passphrase="correct horse battery staple!",
            salt_path=Path(self.tempdir.name) / "salt.bin",
        )

    def tearDown(self):
        self.manager.destroy()
        self.tempdir.cleanup()

    def test_round_trip_uses_authenticated_associated_data(self):
        envelope = self.manager.encrypt(b"local-only record", aad=b"hermes:record:1")
        actual = self.manager.decrypt(envelope.as_text(), aad=b"hermes:record:1")
        self.assertEqual(actual, b"local-only record")

    def test_wrong_associated_data_is_rejected(self):
        envelope = self.manager.encrypt(b"local-only record", aad=b"hermes:record:1")
        with self.assertRaises(EncryptionError):
            self.manager.decrypt(envelope.as_text(), aad=b"hermes:record:2")

    def test_tampered_envelope_is_rejected(self):
        envelope = self.manager.encrypt(b"local-only record", aad=b"hermes:record:1").as_text()
        position = len(envelope) // 2
        replacement = "A" if envelope[position] != "A" else "B"
        tampered = envelope[:position] + replacement + envelope[position + 1:]
        with self.assertRaises(EncryptionError):
            self.manager.decrypt(tampered, aad=b"hermes:record:1")


if __name__ == "__main__":
    unittest.main()
