# -*- coding: utf-8 -*-
"""Check that the English and Chinese README sections stay in sync.

A bilingual README drifts: someone edits the English side, updates a number
or a command, and the Chinese side quietly keeps the old value - which is
worse than not having it, because a reader has no way to tell.

This compares the parts that MUST agree between the two sections:
  * every fenced code block (commands and code samples),
  * every image reference,
  * every inline `identifier` (tool names, file paths, flags, status values),
  * every number that appears in a sentence (test counts, versions, ports).

Run:  python -X utf8 tools/check_readme_i18n.py
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

EN_ANCHOR = '<a name="shared-equipment-rescue"></a>'
ZH_ANCHOR = '<a name="共享儀器搶救"></a>'

problems = []


def _split(text: str):
    i = text.index(EN_ANCHOR)
    j = text.index(ZH_ANCHOR)
    return text[i:j], text[j:]


def _code_blocks(section: str):
    """(language, body) for every fenced block."""
    out = []
    for m in re.finditer(r"```([a-z]*)\n(.*?)```", section, re.S):
        out.append((m.group(1), m.group(2)))
    return out


def _code_signature(block: str, lang: str = ""):
    """The part of a code block that must match across languages.

    Comments are allowed to differ (they are prose), but every executable
    line - the command, the flag, the value - must be identical. Trailing
    comments are stripped too, so only the code itself is compared.
    """
    lines = []
    is_python = lang.startswith("py")
    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if is_python:
            # comments are prose: both standalone and trailing ones may be
            # translated, so only the code is compared
            if stripped.startswith("#"):
                continue
            code = re.split(r"\s+#", stripped, maxsplit=1)[0].rstrip()
            if code:
                lines.append(code)
            continue
        if stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def _images(section: str):
    return sorted(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", section))


def _identifiers(section: str):
    # inline code spans that look like identifiers we care about
    spans = re.findall(r"`([^`\n]+)`", section)
    keep = [s for s in spans
            if re.match(r"^[A-Za-z_][A-Za-z0-9_./\-]*$", s) and len(s) > 2]
    return sorted(set(keep))


def _numbers(section: str):
    """Numbers that state a fact, e.g. "28 browser checks", "68 passed".

    Compared as bare numbers: the English and Chinese wordings differ
    ("28 browser checks" vs "28 項瀏覽器檢查"), so pairing a number with an
    English noun would report every one of them as drift.
    """
    nums = re.findall(r"(?<![\w./-])(\d{1,4})(?:\.\d+)?\s*"
                      r"(passed|checks|tests|rows|tools|browser|fixtures|"
                      r"項瀏覽器檢查|個工具|tests green|passed)",
                      section)
    return sorted(set(n for n, _ in nums))


def main() -> int:
    text = open(README, encoding="utf-8").read()
    en, zh = _split(text)

    # 1 - code blocks must be identical (commands must not drift)
    en_code = _code_blocks(en)
    zh_code = _code_blocks(zh)
    if len(en_code) != len(zh_code):
        problems.append(
            f"code block count differs: en={len(en_code)} zh={len(zh_code)}")
    for i, ((lang_a, a), (lang_b, b)) in enumerate(zip(en_code, zh_code)):
        if lang_a != lang_b:
            problems.append(f"code block #{i} language differs: {lang_a} vs {lang_b}")
        sig_a = _code_signature(a, lang_a)
        sig_b = _code_signature(b, lang_b)
        if sig_a != sig_b:
            only_a = [x for x in sig_a if x not in sig_b]
            only_b = [x for x in sig_b if x not in sig_a]
            problems.append(
                f"code block #{i} executable lines differ:\n"
                f"  EN only: {only_a[:4]}\n  ZH only: {only_b[:4]}")

    # 2 - images must match
    en_img, zh_img = _images(en), _images(zh)
    if en_img != zh_img:
        only_en = [x for x in en_img if x not in zh_img]
        only_zh = [x for x in zh_img if x not in en_img]
        problems.append(f"image references differ: en-only={only_en} zh-only={only_zh}")

    # 3 - identifiers (tool names, flags, status values)
    en_ids, zh_ids = set(_identifiers(en)), set(_identifiers(zh))
    only_en = sorted(x for x in en_ids - zh_ids
                     if not x.startswith(("http", "127.", "GET", "POST", "PUT")))
    only_zh = sorted(zh_ids - en_ids)
    if only_en:
        problems.append(f"identifiers only in the English section: {only_en[:12]}")
    if only_zh:
        problems.append(f"identifiers only in the Chinese section: {only_zh[:12]}")

    # 4 - numbers in sentences
    en_nums, zh_nums = set(_numbers(en)), set(_numbers(zh))
    if en_nums != zh_nums:
        problems.append(f"numbers differ: en-only={sorted(en_nums - zh_nums)} "
                        f"zh-only={sorted(zh_nums - en_nums)}")

    if problems:
        print("README i18n drift detected:\n")
        for p in problems:
            print("  -", p)
        print("\nFix the sections so they say the same thing.")
        return 1
    print(f"README EN/ZH in sync: {len(en_code)} code blocks, "
          f"{len(en_img)} images, {len(en_ids)} identifiers, "
          f"{len(en_nums)} numbers all agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
