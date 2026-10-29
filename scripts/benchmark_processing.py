"""Repeatable local processing measurements; no providers or retained assets."""

import json
import tempfile
from pathlib import Path
from timeit import repeat

from PIL import Image

from gensprite_mcp.assets import AssetStore
from gensprite_mcp.image_ops import _quantize


def main() -> None:
    gradient = Image.new("RGBA", (256, 256))
    gradient.putdata([(x, y, (x + y) % 256, 255) for y in range(256) for x in range(256)])
    palette = ["#%02X%02X%02X" % (i * 8, i * 4, 255 - i * 8) for i in range(32)]
    probe = Image.new("RGBA", (8, 8), (1, 0, 0, 255))
    probe.putpixel((0, 0), (9, 8, 7, 0))
    mapped = _quantize(probe, ["#000000", "#020000"])
    assert mapped.getpixel((1, 0)) == (0, 0, 0, 255), "Ties must retain palette order"
    assert mapped.getpixel((0, 0)) == (9, 8, 7, 0), "Transparent RGB and alpha must remain exact"
    converted = _quantize(gradient, palette)
    with tempfile.TemporaryDirectory(prefix="gensprite-benchmark-") as temporary:
        store = AssetStore(Path(temporary))
        asset = store.save_image(converted, "Benchmark", palette=palette)
        assert not store.validate_sprite(asset["asset_id"])["errors"]
        measurements = {
            "palette_256_gradient_ms": min(repeat(
                lambda: _quantize(gradient, palette), number=1, repeat=3,
            )) * 1000,
            "validate_256_sprite_ms": min(repeat(
                lambda: store.validate_sprite(asset["asset_id"]), number=1, repeat=5,
            )) * 1000,
        }
    print(json.dumps({name: round(value, 2) for name, value in measurements.items()}, indent=2))


if __name__ == "__main__":
    main()
