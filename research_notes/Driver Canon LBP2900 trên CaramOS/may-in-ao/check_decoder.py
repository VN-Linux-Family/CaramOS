"""Decode harness output with vlbp2900's Hi-SCoA decoder and compare with the raw raster."""
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("vlbp2900", sys.argv[1])
v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
ls, lines = 620, 1400
raw = open("raster.bin", "rb").read()
data = open("stream.bin", "rb").read()
t = time.time()
bs, out, bands, eob = v.Bits(data), bytearray(), 0, None
while bs.p < bs.n and eob != 1:
    o, eob = v.decode_band(bs, ls, 1, 4, 0, -7, 0)
    out += o; bands += 1
    bs.p = (bs.p + 31) & ~31
print("bands", bands, "eob", eob, "bytes", len(out), "expected", len(raw), "equal", bytes(out) == raw,
      "left bits", bs.n - bs.p, "seconds %.2f" % (time.time() - t))
if bytes(out) != raw:
    i = next(i for i in range(min(len(out), len(raw))) if out[i] != raw[i])
    print("first difference at byte", i, "line", i // ls, "col", i % ls)
# Render through the same path the emulator uses.
json.dump({"line_size": ls, "lines": lines, "hiscoa": "0104010100f90000"}, open("page-test.json", "w"))
open("page-test.capt", "wb").write(data)
