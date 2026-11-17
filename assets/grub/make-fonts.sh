#!/bin/sh
# Make the GRUB fonts of the live USB boot menu (live-theme.txt) from DejaVu Sans: ASCII, Latin-1, Latin
# Extended-A/B (Ơ ơ Ư ư), combining marks, Latin Extended Additional (the Vietnamese letters), punctuation and
# arrows. Needs grub-common (grub-mkfont) and fonts-dejavu-core. The .pf2 files are committed, so ISO builds do
# not need either package.
set -eu
cd "$(dirname "$0")"
DEJAVU=/usr/share/fonts/truetype/dejavu
RANGES=0x20-0x7E,0xA0-0x24F,0x300-0x36F,0x1E00-0x1EFF,0x2000-0x206F,0x2190-0x21FF
grub-mkfont -s 24 -r "$RANGES" -o dejavu-sans-bold-24.pf2 "$DEJAVU/DejaVuSans-Bold.ttf"
grub-mkfont -s 18 -r "$RANGES" -o dejavu-sans-18.pf2 "$DEJAVU/DejaVuSans.ttf"
