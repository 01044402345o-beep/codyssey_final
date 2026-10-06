"""/health 가 배포 커밋 정보를 노출하는지.  실행: cd backend && python -m unittest discover -s tests -t ."""
import os
import unittest
from unittest import mock

from app.main import health


class T(unittest.TestCase):
    def test_deploy_info_from_render_env(self):
        env = {"RENDER_GIT_COMMIT": "abc1234", "RENDER_GIT_BRANCH": "main", "RENDER_GIT_REPO_SLUG": "owner/repo"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(health()["deploy"], {"commit": "abc1234", "branch": "main", "repo": "owner/repo"})

    def test_deploy_info_absent_is_null(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("RENDER_GIT_COMMIT", "RENDER_GIT_BRANCH", "RENDER_GIT_REPO_SLUG"):
                os.environ.pop(k, None)
            self.assertEqual(health()["deploy"], {"commit": None, "branch": None, "repo": None})


if __name__ == "__main__":
    unittest.main()
