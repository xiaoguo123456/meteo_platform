import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import build_info as module
from app.main import app


class BuildInfoTests(unittest.TestCase):
    def tearDown(self):
        module.build_info.cache_clear()

    def test_deployed_file_takes_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'build_info.json'
            path.write_text(json.dumps({'commit': 'a'*40, 'short': 'aaaaaaa'}))
            with patch.object(module, 'INFO_PATH', path), patch.object(module, '_git', side_effect=AssertionError('不应调用 git')):
                module.build_info.cache_clear()
                response = TestClient(app).get('/api/version')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['commit'], 'a'*40)
        self.assertEqual(response.json()['source'], 'build')
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_local_falls_back_to_git(self):
        with patch.object(module, 'INFO_PATH', Path('/不存在/build_info.json')):
            module.build_info.cache_clear()
            info = module.build_info()
        self.assertEqual(info['source'], 'git')
        self.assertEqual(len(info['commit']), 40)
        self.assertEqual(info['short'], info['commit'][:7])
