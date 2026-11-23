"""Decode the IPP requests/responses in an strace -xx log of ccpd (sendto/recvfrom on the CUPS socket)."""
import re, struct, sys, collections
OPS = {0x0002: "Print-Job", 0x0009: "Get-Job-Attributes", 0x000A: "Get-Jobs", 0x000B: "Get-Printer-Attributes",
       0x4001: "CUPS-Get-Default", 0x4002: "CUPS-Get-Printers"}
TAGS = {0x01: "operation", 0x02: "job", 0x03: "end", 0x04: "printer", 0x05: "unsupported"}
def parse(b):
    ver, code, rid = struct.unpack_from(">HHI", b); i = 8; attrs = []; group = None; name = None
    while i < len(b):
        t = b[i]; i += 1
        if t <= 0x0F:
            group = TAGS.get(t, hex(t))
            if t == 0x03: break
            continue
        nl = struct.unpack_from(">H", b, i)[0]; i += 2
        if nl: name = b[i:i+nl].decode(errors="replace")
        i += nl
        vl = struct.unpack_from(">H", b, i)[0]; i += 2
        v = b[i:i+vl]; i += vl
        if t in (0x21, 0x23) and vl == 4: v = struct.unpack(">i", v)[0]
        elif t == 0x22 and vl == 1: v = bool(v[0])
        else: v = v.decode(errors="replace")
        attrs.append((group, name, v))
    return code, rid, attrs
bodies = []
for line in open(sys.argv[1], errors="replace"):
    m = re.search(r'(sendto|recvfrom)\(\d+, "((?:\\x[0-9a-f]{2})*)"', line)
    if not m: continue
    data = bytes.fromhex(m.group(2).replace("\\x", ""))
    if data.startswith(b"HTTP/1.1 200") or data.startswith(b"POST"):
        k = data.find(b"\r\n\r\n")
        data = data[k+4:] if k >= 0 else b""
    if len(data) >= 9 and data[0] in (1, 2):
        bodies.append((m.group(1), data))
seen = collections.Counter()
shown = 0
for direction, b in bodies:
    try: code, rid, attrs = parse(b)
    except Exception as e: continue
    key = (direction, code, tuple(a[:2] for a in attrs))
    seen[key] += 1
    if seen[key] == 1 and shown < 6:
        shown += 1
        print(f"== {direction} {'op ' + OPS.get(code, hex(code)) if direction == 'sendto' else 'status ' + hex(code)} id={rid}")
        for g, n, v in attrs: print(f"   [{g}] {n} = {v!r}"[:160])
print("distinct message shapes and counts in 1 s:")
for (d, c, _), n in seen.most_common(6): print(f"  {d} {OPS.get(c, hex(c)) if d == 'sendto' else hex(c)}: {n}")
