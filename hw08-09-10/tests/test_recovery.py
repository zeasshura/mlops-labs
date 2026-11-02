import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import lab
import release


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'workspace';lab.initialize(self.root)
        self.m=lab.read(self.root/'manifest-B.json');self.r=lab.read(self.root/'report-B.json')

    def test_pointer_ledger_crash_recovers_once(self):
        with self.assertRaises(RuntimeError):release.publish_event(self.m,self.r,self.root,True)
        self.assertTrue((self.root/'pending-release.json').exists())
        release.publish_event(self.m,self.r,self.root)
        release.publish_event(self.m,self.r,self.root)
        events=(self.root/'publications.jsonl').read_text().splitlines()
        self.assertEqual(len(events),1)
        self.assertFalse((self.root/'pending-release.json').exists())
        self.assertEqual(json.loads(events[0])['release_id'],lab.read(self.root/'accepted.json')['release_id'])

    def test_runtime_or_evaluation_changes_release_identity(self):
        release.publish_event(self.m,self.r,self.root)
        r={**self.r,'evaluation_run_id':'fixture-eval-B-second'}
        release.publish_event(self.m,r,self.root)
        self.assertEqual(len((self.root/'publications.jsonl').read_text().splitlines()),2)

    def test_tampered_weights_preserve_accepted(self):
        before=(self.root/'accepted.json').read_bytes()
        (self.root/'model-B.txt').write_text('tampered')
        with self.assertRaises(ValueError):release.publish_event(self.m,self.r,self.root)
        self.assertEqual((self.root/'accepted.json').read_bytes(),before)

    def test_publication_disk_failure_preserves_pointer(self):
        before=(self.root/'accepted.json').read_bytes()
        real=release.atomic_bytes
        def fail_pointer(path,data):
            if Path(path).name=='accepted.json':raise OSError('simulated pointer failure')
            return real(path,data)
        with patch('release.atomic_bytes',side_effect=fail_pointer):
            with self.assertRaises(OSError):release.publish_event(self.m,self.r,self.root)
        self.assertEqual((self.root/'accepted.json').read_bytes(),before)
        self.assertFalse((self.root/'pending-release.json').exists())
