# -*- coding: utf-8 -*-
"""The English and Chinese README sections must say the same thing.

A bilingual README drifts the moment someone edits one side. This runs the
checker from tools/check_readme_i18n.py as a test, so a drifted pair breaks
the suite instead of quietly misleading a reader.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECKER = os.path.join(ROOT, "tools", "check_readme_i18n.py")


def test_readme_english_and_chinese_are_in_sync():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", CHECKER],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")
