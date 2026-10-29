# Processing measurements

The refactor preserves exact nearest-RGB palette matching and source-integrity checks.
Palette matching uses direct squared RGB distances without per-candidate generators;
native asset validation counts distinct RGBA colors in Pillow and decodes/hashes one
bounded byte buffer. Component slicing sorts its seeds once instead of rescanning all
remaining pixels for each component. Generation saves supplied PNGs once and renders
pixel drawings once. AI image preparation runs outside the MCP event loop.

Measured on this Windows checkout using Python 3.12 and Pillow 12.1, comparing commit
`b6fddcd` with the refactor in the same process, best of three runs per operation:

| Operation | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Exact 32-color mapping, 256x256 RGBA gradient | 1862.14 ms | 533.38 ms | 3.49x |
| Validate a 256x256 sprite | 44.61 ms | 3.67 ms | 12.14x |

Input pixels and palette were identical; the comparison asserted byte-identical
mapped pixels and equal validation reports before timing. These measurements cover
local processing, not model generation latency or an across-the-board MCP speedup.
Disk, antivirus activity, image color diversity, and hardware affect results.

Run the retained current-version benchmark from the repository root:

```powershell
uv run --locked python scripts/benchmark_processing.py
```

It uses a deterministic gradient, checks palette tie ordering and transparent-pixel
preservation, validates the processed sprite, and removes its temporary asset store.
