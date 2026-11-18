import unittest
from unittest.mock import Mock
from scsp_preview import read_preview_mesh

class NullMeshTests(unittest.TestCase):
    def test_explicit_null_is_reported_without_dereferencing(self):
        p=Mock(m_PathID=0);warnings=[]
        self.assertIsNone(read_preview_mesh(p,'empty',warnings))
        p.deref.assert_not_called()
        self.assertIn('empty',warnings[0])

    def test_nonzero_missing_reference_is_not_silently_skipped(self):
        p=Mock(m_PathID=123);p.deref.side_effect=ValueError('missing mesh')
        with self.assertRaisesRegex(ValueError,'missing mesh'):read_preview_mesh(p,'required',[])

    def test_valid_mesh_is_kept(self):
        p=Mock(m_PathID=123);warnings=[]
        self.assertIs(read_preview_mesh(p,'dress',warnings),p.deref.return_value.read.return_value)
        self.assertEqual(warnings,[])
