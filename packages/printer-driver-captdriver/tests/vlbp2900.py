#!/usr/bin/env python3
"""Virtual Canon LBP2900 (CAPT) printer over USB/IP, for testing CaramOS without the hardware.

  serve   run the USB/IP server that emulates the printer (no root needed)
  attach  plug it into this machine through vhci-hcd (root; modprobe vhci-hcd first)
  detach  unplug it (root)
  render  decode a saved page (Hi-SCoA) into PNG files

The device looks like the real one: USB 04a9:2676, printer class 7/1/2, the same IEEE 1284
ID. The CAPT replies follow captdriver's SPECS and the reply sizes seen in USB captures of a
real LBP2900B. Pages sent by a driver are saved and decoded to PNG, so the output can be
checked by eye. Paper, toner and engine timing are simulated, not real.
"""
import argparse
import collections
import json
import os
import select
import socket
import struct
import subprocess
import sys
import time
import zlib

VID, PID, BCD = 0x04A9, 0x2676, 0x0100
BUSID = "1-1"
DEVICE_ID = "MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900"
STRINGS = {1: "Canon", 2: "LBP2900", 3: "0000A1B2C3D4"}
EPIPE, ECONNRESET = -32, -104
# How status bytes are filled (VLBP_STATUS):
#   capture  the values decoded from USB captures of a real LBP2900B: first status byte 0x00
#            when ready, 0x10 offline/waiting, 0x04 printing, 0x01 finishing a page; the
#            GetInputStatus reply of a ready printer with paper
#   specs    captdriver's reading of the bits (0x40 unit free, 0x01 printer free) plus the
#            constant bytes listed in captdriver's SPECS
#   hybrid   captdriver's status bits with the captured GetInputStatus reply (paper loaded);
#            the default, with which captdriver prints
#   jobactive  0x40 while no job holds the unit, 0x10 while one does (the captures' "1088")
STATUS_STYLE = os.environ.get("VLBP_STATUS", "hybrid")
INPUT_STATUS_READY = bytes.fromhex("0010" "00d0000c" "f60968109600fd0100000000")  # 18 bytes

NAMES = {
    0xA0A0: "Nop", 0xA0A1: "GetInputStatus", 0xA0A7: "A0A7", 0xA0A8: "GetExtendedStatus",
    0xA1A0: "GetIEEE1284ID", 0xA1A1: "GetPrinterInfo", 0xA2A0: "ReserveUnit", 0xA3A2: "Start0",
    0xC0A0: "VideoData", 0xC0A4: "BlackEnd", 0xD0A0: "BeginPage", 0xD0A1: "BeginData",
    0xD0A2: "EndPage", 0xD0A4: "BlackPlane", 0xD0A9: "Multi", 0xE0A0: "GetBasicStatus",
    0xE0A2: "ClearError", 0xE0A3: "ClearMisPrint", 0xE0A4: "DiscardData", 0xE0A5: "GoOnline",
    0xE0A6: "GoOffline", 0xE0A7: "StartPrint", 0xE0A9: "ReleaseUnit", 0xE0BA: "SetPowerDown",
    0xE1A1: "SetJobInfo2", 0xE1A2: "SetLEDStatus",
}
# GetPrinterInfo reply payload as captured from a real LBP2900B: Blk=0xFFF0, Buf=0x0040.
PRINTER_INFO = bytes.fromhex("000b312a0101f0ff400004004100010000000000") + bytes(32)


class Log:
    def __init__(self, path):
        self.f = open(path, "a", buffering=1)
        self.t0 = time.monotonic()

    def __call__(self, tag, text):
        self.f.write(f"{time.monotonic() - self.t0:9.3f} {tag:5} {text}\n")


def recvall(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


class Capt:
    """The printer side of the CAPT protocol."""

    def __init__(self, log, outdir, print_delay):
        self.log, self.outdir, self.print_delay = log, outdir, print_delay
        self.inbuf = bytearray()
        self.outq = collections.deque()
        self.timers = []
        self.saved = 0
        self.job = 0
        self.online_count = 0
        self.reset()

    def reset(self):
        self.offline = False
        self.reserved = False
        self.printing = 0
        self.dec = self.prt = self.out = self.done = self.recv = 0
        self.pages_in_job = 0
        self.xchanged = True
        self.page = None

    # -- byte stream from the host ------------------------------------------------
    def feed(self, data):
        if not self.inbuf and data[1:2] and data[1] >> 4 not in (0xA, 0xC, 0xD, 0xE):
            # Not a CAPT packet: show what the host sent (for example PostScript from a
            # wrong driver) and drop it, like a confused printer would.
            self.log("JUNK", f"{len(data)} bytes that are not CAPT: {data[:80]!r}")
            return
        self.inbuf += data
        while len(self.inbuf) >= 4:
            cmd, size = struct.unpack_from("<HH", self.inbuf)
            if size < 4:
                self.log("PROTO", f"bad packet size {size} for {cmd:04X}; dropped "
                                  f"{len(self.inbuf)} bytes: {bytes(self.inbuf[:32]).hex()}")
                self.inbuf.clear()
                return
            if len(self.inbuf) < size:
                return
            pkt = bytes(self.inbuf[:size])
            del self.inbuf[:size]
            self.command(cmd, pkt[4:])

    def pop(self, length):
        msg = self.outq.popleft()
        if len(msg) > length:
            self.outq.appendleft(msg[length:])
            msg = msg[:length]
        return msg

    def soft_reset(self):
        self.log("USB", "SOFT_RESET: buffers flushed")
        self.inbuf.clear()
        self.outq.clear()

    # -- timers -------------------------------------------------------------------
    def timer_due(self):
        if not self.timers:
            return None
        return max(0.0, min(t for t, _ in self.timers) - time.monotonic())

    def tick(self):
        now = time.monotonic()
        due = [t for t in self.timers if t[0] <= now]
        self.timers = [t for t in self.timers if t[0] > now]
        for _, fn in due:
            fn()

    # -- status -------------------------------------------------------------------
    def s0(self):
        v = 0
        if STATUS_STYLE in ("specs", "hybrid"):
            if not self.reserved:
                v |= 0x40  # UNIT_FREE
            if not self.printing:
                v |= 0x01  # PRINTER_FREE
        elif STATUS_STYLE == "jobactive":
            if not self.reserved:
                v |= 0x40  # unit free
            else:
                v |= 0x10  # captures: 1088 = "job active, waiting"
            if self.printing:
                v |= 0x04
            else:
                v |= 0x01  # printer free (ccpd only reserves the unit when 0x41 is set)
        elif self.printing:
            v |= 0x04      # printing in progress
        if self.offline:
            v |= 0x10      # OFFLINE (captures: "job active, waiting")
        return v

    def s1(self):
        return 0x88 | (0x01 if self.xchanged else 0)  # 0x01: extended status changed

    def basic_status(self):
        return bytes([self.s0(), self.s1(), 0, 0, 0x0F, 0, 0, 0])

    def ext_status(self):
        b = bytearray(52)
        b[0], b[1] = self.s0(), self.s1() & ~0x01
        b[4] = 0x0F                                   # buffer: 15 free slots
        b[8] = 0x04 if self.printing else 0x00        # Aux: paper delivery
        b[10] = 0x80                                  # Pap: paper loaded, engine ready
        struct.pack_into("<HHHH", b, 14, self.dec, self.prt, self.out, self.done)
        if STATUS_STYLE == "specs":
            struct.pack_into("<H", b, 24, 0x0050)      # STATUS4: bits 6 and 4 always 1 (SPECS)
            b[32] = 0x55                              # constant in SPECS
            b[33] = self.online_count & 0xFF          # number of GoOnline (E0A5) commands
        struct.pack_into("<H", b, 28, self.job)
        struct.pack_into("<H", b, 34, self.recv)
        struct.pack_into("<H", b, 40, self.pages_in_job)
        return bytes(b)

    # -- commands -----------------------------------------------------------------
    def reply(self, cmd, payload):
        msg = struct.pack("<HH", cmd, 4 + len(payload)) + payload
        self.log("D>H", f"{cmd:04X} {NAMES.get(cmd, '?')} {payload[:40].hex()}")
        # A real printer sends the first 6 bytes, then the rest in a second transfer.
        self.outq.append(msg[:6])
        if len(msg) > 6:
            self.outq.append(msg[6:])

    def command(self, cmd, p):
        name = NAMES.get(cmd, "UNKNOWN")
        if cmd != 0xC0A0:
            self.log("H>D", f"{cmd:04X} {name} len={len(p)} {p[:48].hex()}")
        if cmd == 0xD0A9:
            off = 0
            while off + 4 <= len(p):
                c, s = struct.unpack_from("<HH", p, off)
                if s < 4:
                    break
                self.command(c, p[off + 4:off + s])
                off += s
            return
        if cmd == 0xD0A0:
            self.begin_page(p)
            return
        if cmd == 0xD0A4:
            self.current_page()["hiscoa"] = p.hex()
            return
        if cmd in (0xD0A1, 0xD0A2):
            return
        if cmd == 0xC0A0:
            pg = self.current_page()
            pg["data"] += p
            pg["chunks"] += 1
            return
        if cmd == 0xC0A4:
            self.end_page()
            return
        if (cmd & 0xF000) not in (0xA000, 0xE000):
            self.log("NOTE", f"{cmd:04X}: unknown command without a reply")
            return
        payload = b"\0\0"
        if cmd == 0xE0A0:
            payload = self.basic_status()
        elif cmd == 0xA0A8:
            payload = self.ext_status()
            self.xchanged = False
        elif cmd == 0xA0A1:
            payload = INPUT_STATUS_READY if STATUS_STYLE != "specs" else bytes([0x00, 0x10]) + bytes(16)
        elif cmd == 0xA1A1:
            payload = PRINTER_INFO
        elif cmd == 0xA1A0:
            raw = DEVICE_ID.encode()
            self.log("D>H", "A1A0 raw IEEE 1284 ID")
            self.outq.append(struct.pack(">H", len(raw) + 2) + raw)
            return
        elif cmd == 0xA0A7:
            payload = bytes(136)
        elif cmd == 0xA2A0:
            self.reset()
            self.reserved = True
            self.job = self.job % 0xFFFF + 1
            payload = struct.pack("<BBH", 0, 0, self.job)
            self.log("JOB", f"unit reserved, job {self.job}")
        elif cmd == 0xE1A1:
            flag = p[16] if len(p) > 16 else None
            what = {1: "start", 2: "continue", 3: "end (Linux)", 4: "abort", 6: "end"}.get(flag, flag)
            self.log("JOB", f"job info: {what}")
        elif cmd == 0xE0A5:
            self.offline = False
            self.online_count += 1
            self.xchanged = True
        elif cmd == 0xE0A6:
            self.offline = True
            self.xchanged = True
        elif cmd == 0xE0A4:
            self.page = None
        elif cmd == 0xE0A7:
            self.start_print(struct.unpack("<H", p[:2])[0] if len(p) >= 2 else self.dec)
        elif cmd == 0xE0A9:
            self.reserved = False
            self.xchanged = True
            self.log("JOB", f"unit released after {self.done} printed page(s)")
        elif name == "UNKNOWN":
            self.log("NOTE", f"{cmd:04X}: unknown command, replied 00 00")
        self.reply(cmd, payload)

    def current_page(self):
        if self.page is None:
            self.page = {"params": "", "hiscoa": "", "data": bytearray(), "chunks": 0}
        return self.page

    def begin_page(self, p):
        self.page = None
        pg = self.current_page()
        pg["params"] = p.hex()
        if len(p) >= 34:
            mw, mh, ls, nl, pw, ph = struct.unpack_from("<HHHHHH", p, 22)
            pg.update(margin_w=mw, margin_h=mh, line_size=ls, lines=nl, paper_w=pw, paper_h=ph,
                      size_code=p[4], toner_density=p[8], paper_type=p[12], toner_save=p[19])
            self.log("PAGE", f"begin: {ls * 8}x{nl} px, paper {pw}x{ph}, size code {p[4]:02x}")

    def end_page(self):
        pg = self.current_page()
        self.page = None
        self.recv += 1
        self.dec = self.recv
        self.pages_in_job += 1
        self.xchanged = True
        self.saved += 1
        base = os.path.join(self.outdir, f"page-{self.saved:03d}")
        with open(base + ".capt", "wb") as f:
            f.write(pg["data"])
        meta = {k: v for k, v in pg.items() if k != "data"}
        meta.update(bytes=len(pg["data"]), job=self.job, page_in_job=self.dec)
        with open(base + ".json", "w") as f:
            json.dump(meta, f, indent=1)
        self.log("PAGE", f"page {self.dec} of job {self.job} received: {len(pg['data'])} bytes "
                         f"in {pg['chunks']} chunk(s) -> {base}.capt")
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "render", base],
                         stdout=subprocess.DEVNULL, stderr=open(base + ".render.log", "w"))

    def start_print(self, n):
        self.prt = n
        self.printing += 1
        self.xchanged = True
        self.log("PAGE", f"StartPrint page {n}")

        def finished():
            self.printing -= 1
            self.out = self.done = n
            self.xchanged = True
            self.log("PAGE", f"page {n} delivered")
        self.timers.append((time.monotonic() + self.print_delay, finished))


class Device:
    def __init__(self, log, capt):
        self.log, self.capt = log, capt
        self.config = 0

    @staticmethod
    def descriptor(dtype, index):
        if dtype == 1:
            return struct.pack("<BBHBBBBHHHBBBB", 18, 1, 0x0200, 0, 0, 0, 64, VID, PID, BCD, 1, 2, 3, 1)
        if dtype == 2:
            body = (struct.pack("<BBBBBBBBB", 9, 4, 0, 0, 2, 7, 1, 2, 0)
                    + struct.pack("<BBBBHB", 7, 5, 0x01, 2, 512, 0)
                    + struct.pack("<BBBBHB", 7, 5, 0x82, 2, 512, 0))
            return struct.pack("<BBHBBBBB", 9, 2, 9 + len(body), 1, 1, 0, 0xC0, 1) + body
        if dtype == 3:
            if index == 0:
                return bytes([4, 3, 0x09, 0x04])
            if index in STRINGS:
                b = STRINGS[index].encode("utf-16-le")
                return bytes([2 + len(b), 3]) + b
        if dtype == 6:
            return struct.pack("<BBHBBBBBB", 10, 6, 0x0200, 0, 0, 0, 64, 1, 0)
        return None

    def control(self, setup, data):
        rt, req, value, index, length = struct.unpack("<BBHHH", setup)
        kind, din = (rt >> 5) & 3, rt & 0x80
        st, resp = EPIPE, b""
        if kind == 0:
            if req == 6 and din:
                d = self.descriptor(value >> 8, value & 0xFF)
                if d is not None:
                    st, resp = 0, d[:length]
            elif req == 0 and din:
                st, resp = 0, (b"\x01\x00" if rt & 0x1F == 0 else b"\x00\x00")[:length]
            elif req == 8 and din:
                st, resp = 0, bytes([self.config])[:length]
            elif req == 10 and din:
                st, resp = 0, b"\x00"[:length]
            elif req == 9:
                self.config, st = value & 0xFF, 0
            elif req in (1, 3, 5, 11):
                st = 0
        elif kind == 1:
            if req == 0 and din:
                raw = DEVICE_ID.encode()
                st, resp = 0, (struct.pack(">H", len(raw) + 2) + raw)[:length]
            elif req == 1 and din:
                st, resp = 0, b"\x18"[:length]
            elif req == 2 and not din:
                self.capt.soft_reset()
                st = 0
        if not (kind == 0 and req == 6):
            self.log("USB", f"control {setup.hex()} -> {st} {resp[:16].hex()}")
        return st, resp

    def usbip_dev(self):
        path = b"/sys/devices/pci0000:00/0000:00:1d.0/usb1/" + BUSID.encode()
        return struct.pack(">256s32sIIIHHHBBBBBB", path, BUSID.encode(), 1, 2, 3,
                           VID, PID, BCD, 0, 0, 0, 1, 1, 1)

    def run_urbs(self, conn):
        pending = collections.OrderedDict()
        self.log("USB", "attached")
        while True:
            r, _, _ = select.select([conn], [], [], self.capt.timer_due())
            if r:
                hdr = recvall(conn, 48)
                if hdr is None:
                    break
                cmd, seq, _devid, direction, ep = struct.unpack(">IIIII", hdr[:20])
                if cmd == 1:
                    length = struct.unpack(">I", hdr[24:28])[0]
                    data = b""
                    if direction == 0 and length:
                        data = recvall(conn, length)
                        if data is None:
                            break
                    if ep == 0:
                        st, resp = self.control(hdr[40:48], data)
                        self.ret_submit(conn, seq, st, resp, None if direction else len(data) * (st == 0))
                    elif direction == 0:
                        if self.capt.page is None or len(data) < 64:
                            self.log("OUT", f"{len(data)} bytes: {data[:24].hex()}")
                        self.capt.feed(data)
                        self.ret_submit(conn, seq, 0, b"", len(data))
                    else:
                        pending[seq] = length
                elif cmd == 2:
                    victim = struct.unpack(">I", hdr[20:24])[0]
                    if pending.pop(victim, None) is not None:
                        self.ret_unlink(conn, seq, ECONNRESET)
                    else:
                        self.ret_unlink(conn, seq, 0)
                else:
                    self.log("USB", f"unknown USB/IP command {cmd}; closing")
                    break
            self.capt.tick()
            while pending and self.capt.outq:
                seq, length = pending.popitem(last=False)
                self.ret_submit(conn, seq, 0, self.capt.pop(length))
        self.log("USB", "detached")

    @staticmethod
    def ret_submit(conn, seq, status, data, actual=None):
        actual = len(data) if actual is None else actual
        conn.sendall(struct.pack(">IIIIIiiiii", 3, seq, 0, 0, 0, status, actual, 0, 0, 0)
                     + bytes(8) + data)

    @staticmethod
    def ret_unlink(conn, seq, status):
        conn.sendall(struct.pack(">IIIIIi", 4, seq, 0, 0, 0, status) + bytes(24))


def serve(args):
    os.makedirs(args.out, exist_ok=True)
    log = Log(args.log)
    capt = Capt(log, args.out, args.print_delay)
    dev = Device(log, capt)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(4)
    log("INFO", f"virtual LBP2900 listening on {args.host}:{args.port}, pages in {args.out}")
    while True:
        conn, _ = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        hdr = recvall(conn, 8)
        code = struct.unpack(">HHI", hdr)[1] if hdr else None
        if code == 0x8005:
            conn.sendall(struct.pack(">HHII", 0x0111, 0x0005, 0, 1) + dev.usbip_dev()
                         + bytes([7, 1, 2, 0]))
        elif code == 0x8003:
            busid = recvall(conn, 32) or b""
            if busid.rstrip(b"\0").decode(errors="replace") == BUSID:
                conn.sendall(struct.pack(">HHI", 0x0111, 0x0003, 0) + dev.usbip_dev())
                capt.inbuf.clear()
                capt.outq.clear()
                dev.run_urbs(conn)
            else:
                conn.sendall(struct.pack(">HHI", 0x0111, 0x0003, 1))
        conn.close()


VHCI = "/sys/devices/platform/vhci_hcd.0"


def attach(args):
    s = socket.create_connection((args.host, args.port))
    s.sendall(struct.pack(">HHI32s", 0x0111, 0x8003, 0, BUSID.encode()))
    hdr = recvall(s, 8)
    if not hdr or struct.unpack(">HHI", hdr)[2] != 0:
        sys.exit("the server refused the import")
    dev = recvall(s, 312)
    busnum, devnum, speed = struct.unpack_from(">III", dev, 288)
    port = None
    with open(VHCI + "/status") as f:
        for line in f:
            p = line.split()
            if len(p) >= 3 and p[0] == "hs" and p[2] == "004":
                port = int(p[1])
                break
    if port is None:
        sys.exit("no free high-speed vhci port")
    with open(VHCI + "/attach", "w") as f:
        f.write(f"{port} {s.fileno()} {(busnum << 16) | devnum} {speed}")
    print(port)


def detach(args):
    with open(VHCI + "/detach", "w") as f:
        f.write(str(args.port))


# -- Hi-SCoA decoder (inverse of captdriver's hiscoa-compress.c) --------------------------
class Bits:
    def __init__(self, data):
        self.d = bytes(b ^ 0x43 for b in data)
        self.n = len(self.d) * 8
        self.p = 0

    def bit(self):
        if self.p >= self.n:
            raise EOFError
        b = (self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1
        self.p += 1
        return b

    def bits(self, k):
        v = 0
        for _ in range(k):
            v = (v << 1) | self.bit()
        return v


def read_len(bs):
    k = 0
    while k < 6 and bs.bit():
        k += 1
    if k == 6:
        return 0
    if k == 0:
        if not bs.bit():
            return 1
        return 2 if bs.bit() else 3
    nb = k + 1
    return (1 << (nb + 1)) - 1 - bs.bits(nb)


def decode_band(bs, line_size, o3, o5, o0, o2, o4):
    origin = [o0 + line_size, 0, o2 + line_size, o3, o4, o5]
    out, stash, prefix = bytearray(), [], 0
    while True:
        k = 0
        while k < 8 and bs.bit():
            k += 1
        if k == 8:
            continue                                   # 11111111: alignment NOP
        if k == 1:                                     # REPBYTE
            b = stash.pop(15 - bs.bits(4))
            stash.insert(0, b)
            out.append(b)
            continue
        if k == 2 and bs.bit():                        # BYTE
            b = bs.bits(8)
            stash.insert(0, b)
            del stash[16:]
            out.append(b)
            continue
        if k == 6:
            if bs.bit():                               # ZEROBYTE
                stash.insert(0, 0)
                del stash[16:]
                out.append(0)
            else:                                      # PREFIX
                nb = bs.bits(2)
                prefix = 128 * ((1 << (nb + 1)) - 1 - bs.bits(nb))
            continue
        if k == 7:                                     # END
            return out, bs.bits(2)
        cmd = k                                        # LONGREP 0, 2, 3, 4, 5
        n = prefix + read_len(bs)
        prefix = 0
        d = origin[cmd]
        if d <= 0:
            raise ValueError(f"LONGREP{cmd} with distance {d}")
        for _ in range(n):
            pos = len(out) - d
            out.append(out[pos] if pos >= 0 else 0)
        if cmd == 2:
            origin[0], origin[2] = origin[2], origin[0]
        elif cmd == 5:
            origin[3], origin[5] = origin[5], origin[3]


def write_png(path, width, height, pixels, depth):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(pixels, 6)) + chunk(b"IEND", b""))


def render(args):
    base = args.base
    meta = json.load(open(base + ".json"))
    data = open(base + ".capt", "rb").read()
    ls = meta["line_size"]
    o3, o5, _f1, _f2, o0, o2, o4 = struct.unpack("<bbBBbbh", bytes.fromhex(meta["hiscoa"])[:8])
    bs, raster, bands, eob = Bits(data), bytearray(), 0, None
    while bs.p < bs.n and eob != 1:
        out, eob = decode_band(bs, ls, o3, o5, o0, o2, o4)
        raster += out
        bands += 1
        bs.p = (bs.p + 31) & ~31
    height = len(raster) // ls
    width = ls * 8
    inv = bytes(255 - i for i in range(256))
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows += raster[y * ls:(y + 1) * ls].translate(inv)
    write_png(base + ".png", width, height, bytes(rows), 1)
    # 1/8 preview in grey levels.
    pop = [bin(i).count("1") for i in range(256)]
    pw, ph = ls, height // 8
    prev = bytearray()
    for by in range(ph):
        prev.append(0)
        acc = [0] * ls
        for y in range(by * 8, by * 8 + 8):
            row = raster[y * ls:(y + 1) * ls]
            for x in range(ls):
                acc[x] += pop[row[x]]
        prev += bytes(255 - (a * 255 // 64) for a in acc)
    write_png(base + "-preview.png", pw, ph, bytes(prev), 8)
    black = sum(pop[b] for b in raster)
    result = dict(bands=bands, width=width, height=height, expected_lines=meta.get("lines"),
                  last_band_flag=eob, black_pixels=black, unused_bits=bs.n - bs.p)
    with open(base + ".decoded.json", "w") as f:
        json.dump(result, f)
    print(json.dumps(result))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=3240)
    s.add_argument("--log", default="/tmp/vlbp2900/vlbp2900.log")
    s.add_argument("--out", default="/tmp/vlbp2900")
    s.add_argument("--print-delay", type=float, default=1.0, help="seconds a page takes to print")
    a = sub.add_parser("attach")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=3240)
    d = sub.add_parser("detach")
    d.add_argument("port", type=int)
    r = sub.add_parser("render")
    r.add_argument("base", help="page path without extension, e.g. /tmp/vlbp2900/page-001")
    args = ap.parse_args()
    if args.cmd == "serve":
        os.makedirs(os.path.dirname(args.log), exist_ok=True)
    {"serve": serve, "attach": attach, "detach": detach, "render": render}[args.cmd](args)


if __name__ == "__main__":
    main()
