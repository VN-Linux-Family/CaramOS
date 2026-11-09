#!/usr/bin/python3
"""Which PPD the automatic printer setup picks for each supported printer, with cupsd running.

udev-add-printer and system-config-printer ask cupshelpers for the best PPD of the IEEE 1284 device ID the
printer reports. Status 0 is an exact match, which udev-add-printer sets up on its own; without captdriver's
device IDs an LBP2900 got status 3 (no driver) and an unrelated PostScript PPD.
"""

import sys

import cups
import cupshelpers

# MDL as each printer reports it: the LBP2900 string is from a real printer's CUPS log (agalakhov/captdriver
# issue #37); the others are the names captdriver registers and compares with what the printer reports.
PRINTERS = {
    "LBP2900": ("CanonLBP-2900-3000.ppd", 0),
    "LBP3010/LBP3018/LBP3050": ("CanonLBP-3010-3018-3050.ppd", 0),
    "LBP6000/LBP6018": ("CanonLBP-6000.ppd", 0),
    "LBP3000": ("CanonLBP-3000.ppd", 0),
    "LBP3100/LBP3108/LBP3150": ("CanonLBP-3100-3108-3150.ppd", 0),
}


def main() -> int:
    ppds = cupshelpers.ppds.PPDs(cups.Connection().getPPDs())
    failures = 0
    for mdl, (expected, best_status) in PRINTERS.items():
        device_id = f"MFG:Canon;MDL:{mdl};CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon {mdl}"
        fields = cupshelpers.parseDeviceID(device_id)
        status, name = ppds.getPPDNameFromDeviceID(fields["MFG"], fields["MDL"], fields["DES"],
                                                   fields["CMD"], f"usb://Canon/{mdl}?serial=0000A1B2C3D4")
        ok = name.endswith("/" + expected) and status <= best_status
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {mdl}: status {status}, {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
