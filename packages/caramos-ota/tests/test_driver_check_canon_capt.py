"""Canon's own CAPT printer driver (canon_capt): Driver Check downloads it from Canon and sets up the Canon laser
printers captdriver does not drive (LBP6300dn, LBP3300...)."""

from __future__ import annotations

import hashlib
import io
import os
import re
import signal
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

PACKAGE = Path(__file__).parents[1]
# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(PACKAGE / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import canon_capt, helper, knowledge
from caramos_driver_check.canon_capt import CanonError, UsbPrinter
from caramos_driver_check.events import parse_event

UDEV_RULE = PACKAGE / "usr/lib/udev/rules.d/72-caramos-canon-capt.rules"
QUIRKS = PACKAGE / "usr/share/cups/usb/caramos-canon-capt.usb-quirks"
SERVICE = PACKAGE / "usr/lib/systemd/system/caramos-canon-capt.service"
SETUP_SERVICE = PACKAGE / "usr/lib/systemd/system/caramos-canon-capt-setup.service"
INSTALL_LIST = PACKAGE / "debian/install"

CCPD_CONF = """\
# Canon Printer Daemon for CUPS Configuration Data

<Path>
CUPS_ConfigPath   /etc/cups/
</Path>

#  you can use the following three lines example just by removing the
#  comment symbol "#" of each line.
#<Printer  LBP3200>
#DevicePath  /dev/usb/lp0
#</Printer>

<Printer LBP6300>
DevicePath /dev/usb/canon-capt-26ff-0000A1B2C3D4
</Printer>

<Printer   LBP6300-LAN >
  DevicePath   net:192.168.1.50
</Printer>

<Ports>
UI_Port  59787
PDATA_Port  59687
</Ports>
"""


class Events:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event: str, **fields) -> None:
        self.events.append((event, fields))

    def of(self, kind: str) -> list[dict]:
        return [fields for event, fields in self.events if event == kind]


def write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


class TemporaryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)


class TableTests(unittest.TestCase):
    """The printers, the udev rule, CUPS's quirks and the units must agree with each other."""

    def test_every_usb_printer_has_a_model_with_a_ppd(self) -> None:
        for product, key in canon_capt.USB_MODELS.items():
            with self.subTest(product=product):
                self.assertIn(product, knowledge.CAPT_PRINTERS)
                self.assertIn(key, canon_capt.MODELS)
        # Canon's driver has no PPD for the LBP810, LBP3600 and LBP5200.
        self.assertEqual({"260a", "2654", "266e"}, set(knowledge.CAPT_PRINTERS) - set(canon_capt.USB_MODELS))
        for model in canon_capt.MODELS.values():
            self.assertRegex(model.ppd, r"^CNCUPS[A-Za-z0-9]+CAPTK\.ppd$")
        self.assertIn("LBP6300", canon_capt.MODELS)
        self.assertTrue(canon_capt.MODELS["LBP6300"].network)
        self.assertEqual("LBP6300", canon_capt.USB_MODELS["26ff"])

    def test_captdriver_models(self) -> None:
        self.assertEqual(frozenset(knowledge.CAPTDRIVER_MODELS), canon_capt.CAPTDRIVER_PRODUCTS)

    def test_every_model_fits_a_network_target(self) -> None:
        for key, model in canon_capt.MODELS.items():
            with self.subTest(model=key):
                target = canon_capt.network_target(key, "192.168.1.50")
                self.assertTrue(helper.TARGET_RE.fullmatch(target))
                self.assertEqual((model, "192.168.1.50"), canon_capt.parse_network_target(target))
                self.assertTrue(canon_capt.is_target(target))

    def test_the_udev_rule_names_the_same_printers(self) -> None:
        rule = UDEV_RULE.read_text(encoding="utf-8")
        [products] = re.findall(r'ATTRS\{idProduct\}=="([0-9a-f|]+)"', rule)
        self.assertEqual(set(canon_capt.USB_MODELS), set(products.split("|")))
        self.assertIn(f'SYMLINK+="usb/{canon_capt.DEVICE_PREFIX}$attr{{idProduct}}-$attr{{serial}}"', rule)
        self.assertEqual(str(canon_capt.DEVICE_DIR), "/dev/usb")
        self.assertIn(f'TEST=="{canon_capt.CCPD}"', rule)
        self.assertIn('ENV{SYSTEMD_WANTS}+="caramos-canon-capt-setup.service"', rule)

    def test_cups_leaves_alone_the_printers_only_canons_driver_drives(self) -> None:
        lines = [line for line in QUIRKS.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
        for line in lines:
            self.assertRegex(line, r"^0x04a9 0x[0-9a-f]{4} blacklist$")
        self.assertEqual(set(knowledge.CAPT_PRINTERS) - set(knowledge.CAPTDRIVER_MODELS),
                         {line.split()[1][2:] for line in lines})

    def test_units(self) -> None:
        daemon = SERVICE.read_text(encoding="utf-8")
        self.assertNotRegex(daemon, r"(?m)^\[Install\]")   # the package must not start it everywhere
        for line in ("ExecStart=/usr/sbin/ccpd", "KillSignal=SIGKILL", "IPAddressDeny=any", "IPAddressAllow=localhost",
                     "ConditionPathExists=/usr/sbin/ccpd"):
            self.assertIn(f"\n{line}\n", daemon)
        self.assertEqual(f"{canon_capt.SERVICE}.d", canon_capt.DROPIN.parent.name)
        self.assertEqual(Path("/etc/systemd/system/multi-user.target.wants") / SERVICE.name, canon_capt.BOOT_WANTS)
        setup = SETUP_SERVICE.read_text(encoding="utf-8")
        self.assertNotRegex(setup, r"(?m)^\[Install\]")
        self.assertIn("\nExecStart=/usr/share/caramos-ota/driver-check/caramos-driver-check-helper setup canon-capt\n",
                      setup)
        installed = INSTALL_LIST.read_text(encoding="utf-8")
        for path in (UDEV_RULE, QUIRKS, SERVICE, SETUP_SERVICE):
            self.assertIn(str(path.relative_to(PACKAGE)), installed)
        # Upgrading caramos-ota neither starts nor stops Canon's daemon (debhelper would, by default).
        rules = (PACKAGE / "debian/rules").read_text(encoding="utf-8")
        self.assertIn("\tdh_installsystemd --no-start --no-stop-on-upgrade caramos-canon-capt.service "
                      "caramos-canon-capt-setup.service\n", rules)


class AddressTests(unittest.TestCase):
    def test_printer_addresses(self) -> None:
        self.assertEqual("192.168.1.50", canon_capt.valid_address("192.168.1.50"))
        self.assertEqual("10.0.0.7", canon_capt.valid_address(" 10.0.0.7\n"))

    def test_addresses_no_printer_has(self) -> None:
        for text in ("127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "240.0.0.1", "192.168.1",
                     "192.168.1.256", "192.168.001.050", "printer.local", "", "::1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                canon_capt.valid_address(text)

    def test_network_targets(self) -> None:
        model, address = canon_capt.parse_network_target("canon-capt-net:LBP6300@192.168.1.50")
        self.assertEqual(("LBP6300", "192.168.1.50"), (model.key, address))
        for target in ("canon-capt-net:LBP9999@192.168.1.50", "canon-capt-net:LBP6300@127.0.0.1",
                       "canon-capt-net:LBP6300@192.168.1.50 ", "canon-capt", "canon-capt-net:LBP6300"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                canon_capt.parse_network_target(target)
        self.assertTrue(canon_capt.is_target("canon-capt"))
        self.assertFalse(canon_capt.is_target("canon-capt-foo"))
        self.assertFalse(canon_capt.is_target("printer-driver-captdriver"))


class ConfigurationTests(TemporaryTestCase):
    def test_printers_registered_with_ccpd(self) -> None:
        self.assertEqual({"LBP6300": "/dev/usb/canon-capt-26ff-0000A1B2C3D4", "LBP6300-LAN": "net:192.168.1.50"},
                         canon_capt.registered(CCPD_CONF))
        self.assertEqual({}, canon_capt.registered(""))
        self.assertEqual({}, canon_capt.registered("DevicePath /dev/usb/lp0\n"))   # outside a <Printer> block
        self.assertEqual({}, canon_capt.read_registered(self.temp / "none.conf"))

    def test_network_addresses(self) -> None:
        printers = {"a": "net:192.168.1.50", "b": "net:192.168.1.50", "c": "/dev/usb/lp0", "d": "net:127.0.0.1",
                    "e": "net:bogus", "f": "net:10.0.0.7"}
        self.assertEqual(["192.168.1.50", "10.0.0.7"], canon_capt.network_addresses(printers))

    def test_the_drop_in_follows_the_network_printers(self) -> None:
        dropin = self.temp / "caramos-canon-capt.service.d/50-printers.conf"
        with mock.patch.object(canon_capt, "DROPIN", dropin):
            self.assertFalse(canon_capt.write_dropin({"LBP6300": "/dev/usb/canon-capt-26ff-X"}))
            self.assertFalse(dropin.exists())
            self.assertTrue(canon_capt.write_dropin({"LBP6300-LAN": "net:192.168.1.50", "B": "net:10.0.0.7"}))
            self.assertIn("\n[Service]\nIPAddressAllow=192.168.1.50 10.0.0.7\n", dropin.read_text(encoding="utf-8"))
            self.assertFalse(canon_capt.write_dropin({"LBP6300-LAN": "net:192.168.1.50", "B": "net:10.0.0.7"}))
            self.assertTrue(canon_capt.write_dropin({}))
            self.assertFalse(dropin.exists())

    def test_the_service_starts_at_boot_and_canons_init_script_never(self) -> None:
        wants = self.temp / "multi-user.target.wants" / canon_capt.SERVICE
        dropin = self.temp / "caramos-canon-capt.service.d/50-printers.conf"
        emit = Events()
        with mock.patch.multiple(canon_capt, BOOT_WANTS=wants, DROPIN=dropin,
                                 read_registered=mock.Mock(return_value={"LBP6300-LAN": "net:192.168.1.50"})), \
                mock.patch.object(canon_capt, "_systemctl") as systemctl:
            canon_capt.configure_service(emit)
            canon_capt.configure_service(emit)   # again: nothing breaks
        self.assertEqual(f"/usr/lib/systemd/system/{canon_capt.SERVICE}", os.readlink(wants))
        self.assertIn("IPAddressAllow=192.168.1.50", dropin.read_text(encoding="utf-8"))
        self.assertIn(mock.call("mask", "ccpd.service"), systemctl.call_args_list)
        self.assertEqual(mock.call("daemon-reload"), systemctl.call_args_list[-1])


class ProcessTests(TemporaryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.proc = self.temp / "proc"
        for pid, comm, cmdline in (
            ("100", "ccpd", b"/usr/sbin/ccpd\0"),
            ("101", "captmoncnabb", b"/usr/bin/captmoncnabb\0-s\0"),
            ("102", "vim", b"vim\0/etc/ccpd.conf\0"),
            ("103", "bash", b"bash\0"),
            ("104", "kworker/0:1", b""),
            ("105", "grep", b"grep\0captmon\0"),
            (str(os.getpid()), "python3", b"python3\0caramos-driver-check-helper\0install\0canon-capt-net:ccpd\0"),
        ):
            write(self.proc / pid / "comm", comm + "\n")
            write(self.proc / pid / "cmdline", cmdline)
        write(self.proc / "self" / "comm", "python3\n")

    def test_canons_daemons(self) -> None:
        self.assertEqual([100, 101], canon_capt.canon_processes(self.proc))

    def test_programs_canons_maintainer_scripts_would_kill(self) -> None:
        self.assertEqual([(102, "vim /etc/ccpd.conf"), (105, "grep captmon")],
                         canon_capt.blocking_processes(self.proc))

    def test_no_proc(self) -> None:
        self.assertEqual([], canon_capt.canon_processes(self.temp / "none"))
        self.assertEqual([], canon_capt.blocking_processes(self.temp / "none"))

    def test_stopping_the_daemon(self) -> None:
        emit = Events()
        with mock.patch.object(canon_capt, "_systemctl") as systemctl, \
                mock.patch.object(canon_capt, "canon_processes", side_effect=[[100, 101], []]), \
                mock.patch.object(canon_capt, "blocking_processes", return_value=[]), \
                mock.patch.object(canon_capt.os, "kill") as kill:
            canon_capt.stop_daemon(emit)
        systemctl.assert_called_once_with("stop", canon_capt.SERVICE)
        self.assertEqual([mock.call(100, signal.SIGKILL), mock.call(101, signal.SIGKILL)], kill.call_args_list)

    def test_another_program_named_like_the_daemon_stops_the_install(self) -> None:
        emit = Events()
        with mock.patch.object(canon_capt, "_systemctl") as systemctl, \
                mock.patch.object(canon_capt, "canon_processes", return_value=[100]), \
                mock.patch.object(canon_capt, "blocking_processes", return_value=[(102, "vim /etc/ccpd.conf")]), \
                mock.patch.object(canon_capt.os, "kill") as kill, \
                self.assertRaises(CanonError) as caught:
            canon_capt.stop_daemon(emit)
        self.assertEqual("canon-busy", caught.exception.code)
        self.assertIn("vim /etc/ccpd.conf", emit.of("log")[0]["line"])
        # Nothing was stopped: the printers keep working.
        systemctl.assert_not_called()
        kill.assert_not_called()


class UsbTests(TemporaryTestCase):
    def test_canon_printers_plugged_in(self) -> None:
        sysfs = self.temp / "devices"
        for name, values in (
            ("3-1", {"idVendor": "04a9", "idProduct": "26FF", "serial": "0000A1B2C3D4"}),
            ("3-1:1.0", {"bInterfaceClass": "07"}),
            ("3-2", {"idVendor": "04a9", "idProduct": "1909"}),   # a Canon scanner
            ("3-3", {"idVendor": "03f0", "idProduct": "26ff"}),
            ("3-4", {"idVendor": "04a9", "idProduct": "2654"}),   # LBP3600: Canon's driver has no PPD for it
            ("3-5", {"idVendor": "04a9", "idProduct": "2676"}),   # LBP2900, no serial number
        ):
            for attribute, value in values.items():
                write(sysfs / name / attribute, value + "\n")

        first, second = canon_capt.usb_printers(sysfs)

        self.assertEqual(("26ff", "0000A1B2C3D4", "LBP6300"), (first.product, first.serial, first.model.key))
        self.assertEqual("/dev/usb/canon-capt-26ff-0000A1B2C3D4", first.device)
        self.assertEqual(("2676", "/dev/usb/canon-capt-2676-"), (second.product, second.device))
        self.assertEqual([], canon_capt.usb_printers(self.temp / "none"))
        self.assertIsNone(UsbPrinter("1909", "", "").model)


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self.data = io.BytesIO(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.data.read(size)


class DownloadTests(TemporaryTestCase):
    DATA = bytes(range(256)) * 40
    URL = "https://gdlp01.c-wss.com.invalid/linux-capt-drv-v271-uken.tar.gz"

    def download(self, urlopen, sha256: str | None = None) -> tuple[Path, Events]:
        emit = Events()
        with mock.patch.object(canon_capt.urllib.request, "urlopen", urlopen), \
                mock.patch.object(canon_capt, "CHUNK", 1000), \
                mock.patch.object(canon_capt.time, "sleep"):
            path = canon_capt.download(emit, 10, 55, url=self.URL, size=len(self.DATA),
                                       sha256=sha256 or hashlib.sha256(self.DATA).hexdigest(),
                                       directory=self.temp / "cache")
        return path, emit

    def test_download(self) -> None:
        urlopen = mock.Mock(return_value=FakeResponse(self.DATA))
        path, emit = self.download(urlopen)

        self.assertEqual(self.DATA, path.read_bytes())
        self.assertEqual("linux-capt-drv-v271-uken.tar.gz", path.name)
        self.assertEqual(0o700, (self.temp / "cache").stat().st_mode & 0o777)
        request = urlopen.call_args.args[0]
        self.assertEqual(self.URL, request.full_url)
        self.assertIsNone(request.get_header("Range"))
        percents = [fields["percent"] for fields in emit.of("progress")]
        self.assertEqual(55, percents[-1])
        self.assertTrue(all(10 <= percent <= 55 for percent in percents))
        self.assertEqual(percents, sorted(percents))

    def test_a_cut_download_resumes(self) -> None:
        write(self.temp / "cache/linux-capt-drv-v271-uken.tar.gz", self.DATA[:3000])
        urlopen = mock.Mock(return_value=FakeResponse(self.DATA[3000:], status=206))
        path, _emit = self.download(urlopen)

        self.assertEqual("bytes=3000-", urlopen.call_args.args[0].get_header("Range"))
        self.assertEqual(self.DATA, path.read_bytes())

    def test_a_server_that_sends_the_whole_file_again(self) -> None:
        write(self.temp / "cache/linux-capt-drv-v271-uken.tar.gz", self.DATA[:3000])
        path, _emit = self.download(mock.Mock(return_value=FakeResponse(self.DATA, status=200)))
        self.assertEqual(self.DATA, path.read_bytes())

    def test_a_dropped_connection_is_retried(self) -> None:
        urlopen = mock.Mock(side_effect=[OSError("timed out"), FakeResponse(self.DATA)])
        path, emit = self.download(urlopen)
        self.assertEqual(self.DATA, path.read_bytes())
        self.assertIn("attempt 1/4", emit.of("log")[0]["line"])

    def test_no_network(self) -> None:
        urlopen = mock.Mock(side_effect=OSError("Name or service not known"))
        with self.assertRaises(CanonError) as caught:
            self.download(urlopen)
        self.assertEqual("download", caught.exception.code)
        self.assertEqual(canon_capt.DOWNLOAD_ATTEMPTS, urlopen.call_count)

    def test_a_file_canon_changed_is_not_installed(self) -> None:
        with self.assertRaises(CanonError) as caught:
            self.download(mock.Mock(return_value=FakeResponse(self.DATA)), sha256="0" * 64)
        self.assertEqual("checksum", caught.exception.code)
        self.assertFalse((self.temp / "cache/linux-capt-drv-v271-uken.tar.gz").exists())

    def test_a_downloaded_file_is_used_again(self) -> None:
        write(self.temp / "cache/linux-capt-drv-v271-uken.tar.gz", self.DATA)
        urlopen = mock.Mock()
        path, emit = self.download(urlopen)
        urlopen.assert_not_called()
        self.assertEqual([{"percent": 55}], emit.of("progress"))
        self.assertEqual(self.DATA, path.read_bytes())

    def test_the_pinned_archive(self) -> None:
        self.assertTrue(canon_capt.TARBALL_URL.startswith("https://gdlp01.c-wss.com/"))
        self.assertTrue(canon_capt.TARBALL_URL.endswith(f"/{canon_capt.TARBALL_ROOT}.tar.gz"))
        self.assertRegex(canon_capt.TARBALL_SHA256, r"^[0-9a-f]{64}$")


class ExtractTests(TemporaryTestCase):
    def tarball(self, members: dict[str, bytes], links: tuple[str, ...] = ()) -> Path:
        path = self.temp / "canon.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(f"{canon_capt.TARBALL_ROOT}/{name}")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            for name in links:
                info = tarfile.TarInfo(f"{canon_capt.TARBALL_ROOT}/{name}")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/shadow"
                archive.addfile(info)
        return path

    def members(self) -> dict[str, bytes]:
        return {
            canon_capt.DEBS[0]: b"common deb",
            canon_capt.DEBS[1]: b"capt deb",
            canon_capt.LICENSE: b"licence",
            "32-bit_Driver/Debian/cndrvcups-capt_2.71-1_i386.deb": b"32-bit",
            "64-bit_Driver/RPM/cndrvcups-capt-2.71-1.x86_64.rpm": b"rpm",
            "../../evil": b"outside",
        }

    def test_only_the_two_packages_and_the_licence(self) -> None:
        out = self.temp / "out"
        debs, licence = canon_capt.extract(self.tarball(self.members()), out)

        self.assertEqual([out / "cndrvcups-common_3.21-1_amd64.deb", out / "cndrvcups-capt_2.71-1_amd64.deb"], debs)
        self.assertEqual([b"common deb", b"capt deb"], [deb.read_bytes() for deb in debs])
        self.assertEqual(b"licence", licence.read_bytes())
        self.assertEqual(sorted(path.name for path in (*debs, licence)), sorted(path.name for path in out.iterdir()))
        self.assertFalse((self.temp / "evil").exists())

    def test_a_link_in_place_of_a_package(self) -> None:
        members = self.members()
        del members[canon_capt.DEBS[1]]
        with self.assertRaises(CanonError) as caught:
            canon_capt.extract(self.tarball(members, links=(canon_capt.DEBS[1],)), self.temp / "out")
        self.assertEqual("checksum", caught.exception.code)

    def test_a_missing_package(self) -> None:
        members = self.members()
        del members[canon_capt.LICENSE]
        with self.assertRaises(CanonError) as caught:
            canon_capt.extract(self.tarball(members), self.temp / "out")
        self.assertEqual("checksum", caught.exception.code)


class QueueTests(TemporaryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ppds = self.temp / "model"
        for model in ("LBP6300", "LBP2900"):
            write(self.ppds / canon_capt.MODELS[model].ppd, "*PPD-Adobe: \"4.3\"\n")
        self.commands: list[list[str]] = []
        patches = mock.patch.multiple(
            canon_capt, PPD_DIR=self.ppds, CAPTDRIVER_FILTER=self.temp / "rastertocapt",
            _run=mock.Mock(side_effect=lambda args, emit=None, check=True: self.commands.append(args)))
        patches.start()
        self.addCleanup(patches.stop)

    def setup_usb(self, printers, registered=None, queues=None) -> list[str]:
        with mock.patch.object(canon_capt, "usb_printers", return_value=printers), \
                mock.patch.object(canon_capt, "read_registered", return_value=registered or {}), \
                mock.patch.object(canon_capt, "queues", return_value=queues or {}):
            return canon_capt.setup_usb(Events())

    def test_a_queue_for_a_printer_plugged_in(self) -> None:
        added = self.setup_usb([UsbPrinter("26ff", "0000A1B2C3D4", "/sys/bus/usb/devices/3-1")],
                               queues={"LBP6300": "ipp://192.168.1.20/ipp/print",
                                       "Canon_LBP6300": "usb://Canon/LBP6300?serial=0000A1B2C3D4",
                                       "Other": "usb://Canon/LBP6300?serial=0000A1B2C3D45"})

        self.assertEqual(["LBP6300-2"], added)
        self.assertEqual([
            # A usb:// queue for the printer bypasses Canon's daemon: it goes, the other printer's stays.
            ["lpadmin", "-x", "Canon_LBP6300"],
            ["lpadmin", "-p", "LBP6300-2", "-P", str(self.ppds / "CNCUPSLBP6300CAPTK.ppd"), "-v",
             "ccp://localhost:59687", "-D", "Canon LBP6300dn", "-E", "-o", "PageSize=A4",
             "-o", "printer-is-shared=false"],
            [str(canon_capt.CCPDADMIN), "-p", "LBP6300-2", "-o", "/dev/usb/canon-capt-26ff-0000A1B2C3D4"],
        ], self.commands)

    def test_a_printer_that_has_its_queue(self) -> None:
        added = self.setup_usb([UsbPrinter("26ff", "S1", "")],
                               registered={"LBP6300": "/dev/usb/canon-capt-26ff-S1"},
                               queues={"LBP6300": canon_capt.QUEUE_URI})
        self.assertEqual(([], []), (added, self.commands))

    def test_captdriver_keeps_its_printers(self) -> None:
        write(self.temp / "rastertocapt", "")
        added = self.setup_usb([UsbPrinter("2676", "S2", ""), UsbPrinter("26ff", "S1", "")],
                               queues={"LBP2900": "usb://Canon/LBP2900?serial=S2"})
        self.assertEqual(["LBP6300"], added)
        self.assertNotIn(["lpadmin", "-x", "LBP2900"], self.commands)

    def test_without_captdriver_canons_driver_takes_every_model(self) -> None:
        self.assertEqual(["LBP2900"], self.setup_usb([UsbPrinter("2676", "S2", "")]))

    def test_a_network_printer(self) -> None:
        with mock.patch.object(canon_capt, "read_registered", return_value={"LBP6300": "/dev/usb/x"}), \
                mock.patch.object(canon_capt, "queues", return_value={"LBP6300": canon_capt.QUEUE_URI}):
            name = canon_capt.setup_network(canon_capt.MODELS["LBP6300"], "192.168.1.50", Events())
        self.assertEqual("LBP6300-LAN", name)
        self.assertEqual([str(canon_capt.CCPDADMIN), "-p", "LBP6300-LAN", "-o", "net:192.168.1.50"], self.commands[-1])
        self.assertIn("Canon LBP6300dn (192.168.1.50)", self.commands[0])

    def test_a_network_printer_set_up_already(self) -> None:
        with mock.patch.object(canon_capt, "read_registered", return_value={"Office": "net:192.168.1.50"}), \
                mock.patch.object(canon_capt, "queues", return_value={}):
            name = canon_capt.setup_network(canon_capt.MODELS["LBP6300"], "192.168.1.50", Events())
        self.assertEqual(("Office", []), (name, self.commands))

    def test_a_model_without_its_ppd(self) -> None:
        with self.assertRaises(CanonError) as caught:
            canon_capt.add_queue("LBP3300", canon_capt.MODELS["LBP3300"], "net:192.168.1.50", Events(), "x")
        self.assertEqual("setup", caught.exception.code)

    def test_free_names(self) -> None:
        self.assertEqual("LBP6300", canon_capt._free_name("LBP6300", set()))
        self.assertEqual("LBP6300-3", canon_capt._free_name("LBP6300", {"LBP6300", "LBP6300-2"}))


class InstallTests(unittest.TestCase):
    PRINTER = UsbPrinter("26ff", "0000A1B2C3D4", "/sys/bus/usb/devices/3-1")

    def install(self, targets, *, printers=(PRINTER,), installed=False, online=True, **changes):
        emit = Events()
        run_apt = mock.Mock(return_value=0)
        steps = {"install_driver": mock.Mock(return_value=["cndrvcups-common", "cndrvcups-capt"]),
                 "configure_service": mock.Mock(), "setup_usb": mock.Mock(return_value=["LBP6300"]),
                 "setup_network": mock.Mock(return_value="LBP6300-LAN"), "restart": mock.Mock()}
        steps.update(changes)
        with mock.patch.multiple(canon_capt, usb_printers=mock.Mock(return_value=list(printers)),
                                 installed=mock.Mock(return_value=installed), **steps):
            result = canon_capt.install(targets, emit, run_apt, lambda: online)
        return result, emit, run_apt, steps

    def test_install_and_set_up(self) -> None:
        result, emit, run_apt, steps = self.install(["canon-capt", "canon-capt-net:LBP6300@192.168.1.50"])

        self.assertEqual((True, False, ["cndrvcups-common", "cndrvcups-capt"], ""), result)
        run_apt.assert_called_once_with(["update"], 0, 8)
        steps["setup_network"].assert_called_once_with(canon_capt.MODELS["LBP6300"], "192.168.1.50", emit)
        steps["restart"].assert_called_once()
        self.assertEqual(["LBP6300", "LBP6300-LAN"], [fields["name"] for fields in emit.of("printer")])
        self.assertEqual(["update", "canon-printers"], [fields["stage"] for fields in emit.of("stage")])
        self.assertEqual({"percent": 100}, emit.of("progress")[-1])

    def test_a_network_printer_needs_none_plugged_in(self) -> None:
        result, _emit, run_apt, _steps = self.install(["canon-capt-net:LBP6300@192.168.1.50"], printers=(),
                                                      installed=True)
        self.assertTrue(result[0])
        run_apt.assert_not_called()

    def test_no_printer_canons_driver_drives(self) -> None:
        result, _emit, run_apt, steps = self.install(["canon-capt"], printers=(UsbPrinter("2654", "", ""),))
        self.assertEqual((False, False, [], "refused"), result)
        run_apt.assert_not_called()
        steps["install_driver"].assert_not_called()

    def test_offline(self) -> None:
        result, *_ = self.install(["canon-capt"], online=False)
        self.assertEqual((False, False, [], "offline"), result)

    def test_a_failed_step_says_which(self) -> None:
        result, emit, *_ = self.install(["canon-capt"],
                                        install_driver=mock.Mock(side_effect=CanonError("checksum", "changed")))
        self.assertEqual((False, False, [], "checksum"), result)
        self.assertEqual("changed", emit.of("log")[-1]["line"])

    def test_installing_the_driver(self) -> None:
        emit = Events()
        run_apt = mock.Mock(return_value=0)
        with tempfile.TemporaryDirectory() as temp:
            cache, state = Path(temp) / "cache", Path(temp) / "state"
            debs = [cache / "canon-capt" / Path(deb).name for deb in canon_capt.DEBS]
            licence = cache / "canon-capt" / "LICENSE-EN.txt"
            write(licence, "Canon's licence")
            tarball = cache / "canon.tar.gz"
            write(tarball, "")
            with mock.patch.multiple(canon_capt, CACHE_DIR=cache, STATE_DIR=state,
                                     installed=mock.Mock(side_effect=[False, True]),
                                     download=mock.Mock(return_value=tarball),
                                     extract=mock.Mock(return_value=(debs, licence)), stop_daemon=mock.Mock(),
                                     _ensure_i386=mock.Mock(return_value=True)):
                packages = canon_capt.install_driver(emit, run_apt)
            self.assertEqual("Canon's licence", (state / "LICENSE-EN.txt").read_text(encoding="utf-8"))
            self.assertFalse(tarball.exists())
            self.assertFalse((cache / "canon-capt").exists())
        self.assertEqual([mock.call(["update"], 55, 60),
                          mock.call(["install", "-y", "--", *map(str, debs), *canon_capt.I386_LIBRARIES], 60, 85)],
                         run_apt.call_args_list)
        self.assertEqual([*canon_capt.PACKAGES, *canon_capt.I386_LIBRARIES], packages)
        self.assertEqual(["canon-download", "install"], [fields["stage"] for fields in emit.of("stage")])


class RemoveTests(TemporaryTestCase):
    def test_remove(self) -> None:
        wants = self.temp / "wants" / canon_capt.SERVICE
        dropin = self.temp / "caramos-canon-capt.service.d/50-printers.conf"
        state = self.temp / "state"
        wants.parent.mkdir()
        os.symlink("/usr/lib/systemd/system/caramos-canon-capt.service", wants)
        write(dropin, "[Service]\n")
        write(state / "LICENSE-EN.txt", "Canon's licence")
        commands = []
        run_apt = mock.Mock(return_value=0)
        with mock.patch.multiple(
                canon_capt, BOOT_WANTS=wants, DROPIN=dropin, STATE_DIR=state, stop_daemon=mock.Mock(),
                installed=mock.Mock(return_value=True), _systemctl=mock.Mock(),
                read_registered=mock.Mock(return_value={"LBP6300": "/dev/usb/x", "Office": "net:192.168.1.50"}),
                queues=mock.Mock(return_value={"LBP6300": canon_capt.QUEUE_URI, "Office": "ipp://192.168.1.50/"}),
                _run=mock.Mock(side_effect=lambda args, emit=None, check=True: commands.append(args))):
            self.assertEqual((True, ""), canon_capt.remove(Events(), run_apt))
            systemctl = canon_capt._systemctl

        self.assertIn(["lpadmin", "-x", "LBP6300"], commands)
        self.assertNotIn(["lpadmin", "-x", "Office"], commands)   # not a queue of Canon's driver
        self.assertIn([str(canon_capt.CCPDADMIN), "-x", "Office"], commands)
        self.assertFalse(wants.is_symlink())
        self.assertFalse(dropin.parent.exists())
        self.assertFalse(state.exists())
        self.assertIn(mock.call("unmask", "ccpd.service"), systemctl.call_args_list)
        self.assertEqual(mock.call("daemon-reload"), systemctl.call_args_list[-1])
        run_apt.assert_called_once_with(["purge", "-y", "cndrvcups-common", "cndrvcups-capt"], 20, 95)

    def test_a_removal_that_stops_early_leaves_the_printers_working(self) -> None:
        wants = self.temp / "wants" / canon_capt.SERVICE
        wants.parent.mkdir()
        os.symlink("/usr/lib/systemd/system/caramos-canon-capt.service", wants)
        with mock.patch.multiple(
                canon_capt, BOOT_WANTS=wants, installed=mock.Mock(return_value=True), _systemctl=mock.Mock(),
                read_registered=mock.Mock(return_value={}),
                stop_daemon=mock.Mock(side_effect=CanonError("canon-busy", "close vim first"))):
            self.assertEqual((False, "canon-busy"), canon_capt.remove(Events(), mock.Mock()))
            canon_capt._systemctl.assert_called_once_with("start", canon_capt.SERVICE)
        self.assertTrue(wants.is_symlink())


class HelperTests(TemporaryTestCase):
    def main(self, argv: list[str], **patches) -> tuple[int, list[dict]]:
        out = io.StringIO()
        with mock.patch.object(helper.os, "geteuid", return_value=0), \
                mock.patch.object(helper, "LOCK_FILE", self.temp / "lock"), \
                mock.patch.multiple(canon_capt, **patches), redirect_stdout(out):
            code = helper.main(argv)
        return code, [event for event in map(parse_event, out.getvalue().splitlines()) if event]

    def test_canon_targets_go_to_canons_install(self) -> None:
        def install(targets, emit, run_apt, online):
            emit("printer", name="LBP6300")
            return True, False, ["cndrvcups-capt"], ""

        code, events = self.main(["install", "canon-capt"], install=mock.Mock(side_effect=install))
        self.assertEqual(helper.EXIT_OK, code)
        self.assertEqual({"event": "printer", "name": "LBP6300"}, events[0])
        self.assertEqual({"event": "done", "ok": True, "restart": False, "packages": ["cndrvcups-capt"], "error": ""},
                         events[-1])

    def test_setup_and_remove(self) -> None:
        setup = mock.Mock(return_value=True)
        self.assertEqual(helper.EXIT_OK, self.main(["setup", "canon-capt"], setup=setup)[0])
        setup.assert_called_once()
        code, events = self.main(["remove", "canon-capt"], remove=mock.Mock(return_value=(False, "apt")))
        self.assertEqual(helper.EXIT_FAILED, code)
        self.assertEqual({"event": "done", "ok": False, "restart": False, "packages": [], "error": "apt"}, events[-1])

    def test_setup_does_nothing_without_canons_driver(self) -> None:
        with mock.patch.object(canon_capt, "setup_usb") as setup_usb:
            code, _events = self.main(["setup", "canon-capt"], installed=mock.Mock(return_value=False))
        self.assertEqual(helper.EXIT_OK, code)
        setup_usb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
