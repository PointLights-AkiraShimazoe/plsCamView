# -*- coding: utf-8 -*-
u"""継続84: plsCamView.show() の版検出（ロード中 __version__ vs ディスク）の限定検証。実 Maya ではない。"""
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import plsCamView as PC


class UpdatePath(unittest.TestCase):
    def test_disk_version_matches_loaded(self):
        self.assertEqual(PC._disk_version(), PC.__version__)

    def test_mismatch_triggers_restart(self):
        with patch.object(PC, "_disk_version", return_value=u"9.9.9"), \
             patch.object(PC, "restart", return_value="new-ui") as rs:
            r = PC.show()
        self.assertEqual(r, "new-ui")
        rs.assert_called_once_with()

    def test_same_version_opens_without_restart(self):
        fake_ui = types.SimpleNamespace(PlsCamViewWindow=lambda: "win",
                                        cleanup_stale_ui=lambda: None)
        with patch.object(PC, "restart", side_effect=AssertionError(u"版一致で restart してはいけない")), \
             patch.object(PC, "_restore_language", lambda: None), \
             patch.dict(sys.modules, {"plsCamView.ui": fake_ui}):
            PC._instance = None
            r = PC.show()
        self.assertEqual(r, "win")
        PC._instance = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
