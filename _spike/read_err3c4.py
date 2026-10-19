import io, os
t = io.open(os.environ["TEMP"] + r"\err3c5.txt", encoding="utf-16", errors="replace").read()
lines = t.split("\n")
print("\n".join(lines[16:40]))
