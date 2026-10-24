"""Native-grid artwork supplied by the connected AI agent."""

from PIL import Image
from pydantic import Field, field_validator, model_validator

from .models import Color, Model, normalize_palette


class PixelDrawing(Model):
    rows: list[str] = Field(min_length=8, max_length=256)
    palette: dict[str, Color] = Field(min_length=1, max_length=32)

    @field_validator("palette")
    @classmethod
    def validate_symbols(cls, palette: dict[str, str]) -> dict[str, str]:
        if any(
            len(symbol) != 1 or symbol == "." or not symbol.isascii() or symbol.isspace()
            for symbol in palette
        ):
            raise ValueError(
                "Palette keys are single ASCII symbols; '.' is reserved for transparency"
            )
        normalize_palette(list(palette.values()))
        return {symbol: color.upper() for symbol, color in palette.items()}

    @model_validator(mode="after")
    def validate_grid(self) -> "PixelDrawing":
        width = len(self.rows[0])
        if not 8 <= width <= 256 or any(len(row) != width for row in self.rows):
            raise ValueError("Pixel rows must have one consistent width from 8 through 256")
        if set("".join(self.rows)) - set(self.palette) - {"."}:
            raise ValueError("Pixel rows use undefined palette symbols")
        return self

    def image(self) -> Image.Image:
        image = Image.new("RGBA", (len(self.rows[0]), len(self.rows)))
        colors = {
            symbol: (*bytes.fromhex(color[1:]), 255) for symbol, color in self.palette.items()
        }
        image.putdata([colors.get(symbol, (0, 0, 0, 0)) for row in self.rows for symbol in row])
        return image
