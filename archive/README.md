# Archive

Ad-hoc debug probes, moved from `tools/_deep4.py` … `tools/_deep8.py`. They are kept, not deleted. They are not part of `pytest tests/`.

`_deep5.py`, `_deep7.py`, and `_deep8.py` used to pass the Windows-only `creationflags` value on every OS. They now pass it only when `os.name == "nt"`, same as the tests.

Each script still computes the repository root as the parent of this directory. Run one from the repository root, for example `python archive/_deep4.py`.

**TODO for the author:** these probes were one-off checks. The original notes in `docs/dev-notes/COLLAB/STATUS.md` record pass counts for them. Those counts were not re-measured when the files were moved.
