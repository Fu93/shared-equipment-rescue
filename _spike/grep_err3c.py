import io
t = io.open(r"C:\Users\nn201\OneDrive - University of Glasgow\Desktop\Amazon\shared-equipment-rescue\_spike\err3c.txt", encoding="utf-8", errors="replace").read()
lines = t.split("\n")
print("total:", len(lines))
for i, l in enumerate(lines):
    s = l.strip()
    if s and ("Error" in s or "Exception" in s or ".py" in s or "Traceback" in s):
        print(f"{i}: {s[:160]}")
