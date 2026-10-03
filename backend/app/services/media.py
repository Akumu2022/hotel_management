"""Image upload: decode with Pillow, drop EXIF (location!), re-encode to WebP plus a thumbnail.

Storage is behind a tiny interface: a local folder in development, Cloudflare R2 in production
(added at deploy, M9). Keys are random, so files can be cached forever.
"""

import io
import secrets
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_config
from app.core.errors import AppError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
FULL_SIZE = 1200
THUMB_SIZE = 400

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def url(self, key: str) -> str: ...


class LocalStorage:
    def __init__(self, root: str, base_url: str):
        self.root = Path(root)
        self.base_url = base_url.rstrip("/")

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"


def get_storage() -> Storage:
    cfg = get_config()
    return LocalStorage(cfg.media_dir, cfg.media_url)


def _encode(img: Image.Image, size: int, quality: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((size, size), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    # Saving fresh pixels writes no EXIF / GPS metadata.
    copy.save(out, "WEBP", quality=quality, method=4)
    return out.getvalue()


def process_image(data: bytes) -> tuple[bytes, bytes]:
    """Return (full WebP, thumbnail WebP). Rejects anything that is not a real image."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(413, "too_large", "Photo is larger than 8 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise AppError(422, "bad_image", "That file is not a photo we can read") from None
    img = ImageOps.exif_transpose(img)  # keep the photo the right way up
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    return _encode(img, FULL_SIZE, 80), _encode(img, THUMB_SIZE, 72)


def save_image(storage: Storage, hotel_id, data: bytes) -> tuple[str, str]:
    full, thumb = process_image(data)
    stem = f"hotels/{hotel_id}/{secrets.token_urlsafe(12)}"
    storage.put(f"{stem}.webp", full, "image/webp")
    storage.put(f"{stem}-thumb.webp", thumb, "image/webp")
    return f"{stem}.webp", f"{stem}-thumb.webp"
