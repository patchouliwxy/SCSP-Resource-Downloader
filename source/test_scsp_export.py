import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scsp_export import dense_payload, export_sample


class ExportValidationTests(unittest.TestCase):
    def test_truncated_dense_frames_are_rejected(self):
        clip = {"m_MuscleClip": {"m_Clip": {"data": {"m_DenseClip": {
            "m_FrameCount": 2, "m_CurveCount": 3, "m_SampleArray": [0.0] * 5}}}}}
        with self.assertRaisesRegex(ValueError, "sample count"):
            dense_payload(clip)

    def test_modified_decoded_bundle_is_rejected_before_any_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample, output = root / "sample", root / "export"
            sample.mkdir()
            (sample / "bundle.unity3d").write_bytes(b"modified")
            manifest = {"entries": [{"file": "abc", "name": "model.prefab"}],
                        "outputs": [{"file": "abc", "output": "bundle.unity3d",
                                     "sha256": hashlib.sha256(b"original").hexdigest()}]}
            (sample / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Decoded output SHA-256 mismatch"):
                export_sample(sample, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
