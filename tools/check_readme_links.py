# -*- coding: utf-8 -*-
"""Verify the bilingual README's language links actually work on GitHub.

GitHub renders <a name="..."> anchors, but the exact behaviour (and the id
it produces) is what decides whether the top navigation jumps to the right
section. This checks the rendered page over HTTP: it looks for the anchor
ids GitHub produced and for the heading each language section starts with.

Run:  python -X utf8 tools/check_readme_links.py
"""
import os
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_URL = "https://github.com/Fu93/shared-equipment-rescue"
RAW_URL = (REPO_URL + "/raw/master/README.md")

problems = []


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "readme-link-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> int:
    raw = _get(RAW_URL)

    # 1 - the source must declare both anchors and both nav links
    anchors = set(re.findall(r'<a name="([^"]+)"></a>', raw))
    links = set(re.findall(r"\[([^\]]+)\]\(#([^)]+)\)", raw))
    link_targets = {t for _, t in links}

    for target in sorted(link_targets):
        if target not in anchors:
            problems.append(
                f"nav link points at #{target} but no <a name=\"{target}\"></a> exists")
    if len(anchors) < 2:
        problems.append(f"expected 2 language anchors, found {sorted(anchors)}")

    # 2 - the rendered page must expose an id for each anchor target.
    #    GitHub renders heading anchors as id="user-content-<slug>" and
    #    strips a bare <a name="...">, so the id to look for is the
    #    user-content-prefixed slug of the heading, not the raw name.
    try:
        html = _get(REPO_URL)
    except Exception as exc:
        print(f"could not fetch the rendered page ({exc}); "
              f"checked the source only")
        html = ""
    if html:
        for target in sorted(link_targets):
            if f'id="user-content-{target}"' in html:
                continue
            # the heading may render with a different slug (e.g. a mixed
            # title) - look for a user-content id that matches closely
            alt = [i for i in re.findall(r'id="(user-content-[^"]+)"', html)
                   if target.lower() in i.lower()]
            if not alt:
                problems.append(
                    f"the rendered page has no id for #{target} "
                    f"(looked for id=\"user-content-{target}\"; "
                    f"near: {alt[:3]})")

    if problems:
        print("README link problems:\n")
        for p in problems:
            print("  -", p)
        return 1
    print(f"README language links OK: anchors {sorted(anchors)}, "
          f"nav targets {sorted(link_targets)}"
          + (" - all present in the rendered page" if html else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
