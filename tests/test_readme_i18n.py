# -*- coding: utf-8 -*-
"""The English and Chinese README sections must say the same thing.

A bilingual README drifts the moment someone edits one side. This runs the
checker from tools/check_readme_i18n.py as a test, so a drifted pair breaks
the suite instead of quietly misleading a reader.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECKER = os.path.join(ROOT, "tools", "check_readme_i18n.py")


def test_readme_english_and_chinese_are_in_sync():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", CHECKER],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def test_readme_language_links_resolve_on_github():
    """The top navigation must actually jump to the other language.

    Checks the LIVE rendered page: GitHub rewrites anchors, so "the link
    looks right in the source" is not proof. Skips when the network is not
    available - a judge's machine, or CI without egress, must not fail the
    suite for it.
    """
    import urllib.error
    import urllib.request

    url = "https://github.com/Fu93/shared-equipment-rescue"
    req = urllib.request.Request(url, headers={"User-Agent": "readme-link-check"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"network unavailable: {exc}")

    import re
    for anchor in ("shared-equipment-rescue", "共享儀器搶救"):
        # GitHub renders heading anchors as id="user-content-<slug>" and
        # strips a bare <a name="...">, so that is the id to look for.
        assert f'id="user-content-{anchor}"' in html, (
            f"the rendered README has no anchor for {anchor!r}; "
            f"the language switch would not jump")
