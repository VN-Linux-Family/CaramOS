/* Compress a synthetic page with captdriver's Hi-SCoA compressor, band by band. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hiscoa-common.h"
#include "hiscoa-compress.h"
int main(int argc, char **argv) {
	unsigned ls = 620, lines = 1400, band = 70;
	uint8_t *r = calloc(ls, lines);
	uint32_t s = 12345;
	for (unsigned y = 0; y < lines; y++) for (unsigned x = 0; x < ls; x++) {
		uint8_t v = 0;
		s = s * 1103515245u + 12345u;
		if (y % 200 < 40 && x > 50 && x < 300) v = (s >> 16) & 0xFF;           /* noise: "text" */
		else if (y % 200 > 60 && y % 200 < 80) v = 0xFF;                       /* black bar */
		else if (y % 200 > 100 && y % 200 < 140 && x % 16 < 3) v = 0xF0;       /* stripes */
		else if (y % 200 > 150) v = ((x * 8 + y) % 37 < 3) ? 0x81 : 0x00;      /* diagonals */
		r[y * ls + x] = v;
	}
	FILE *fr = fopen(argv[1], "wb"); fwrite(r, ls, lines, fr); fclose(fr);
	FILE *fs = fopen(argv[2], "wb");
	size_t cap = ls * band * 2 + 64; uint8_t *buf = malloc(cap); size_t total = 0;
	for (unsigned y = 0; y < lines; y += band) {
		unsigned n = (y + band > lines) ? lines - y : band;
		size_t sz = hiscoa_compress_band(buf, cap, r + y * ls, ls, n,
			(y + band >= lines) ? HISCOA_EOB_LAST : HISCOA_EOB_NORMAL, &hiscoa_default_params);
		fwrite(buf, 1, sz, fs); total += sz;
	}
	fclose(fs);
	printf("%u %u %zu\n", ls, lines, total);
	return 0;
}
