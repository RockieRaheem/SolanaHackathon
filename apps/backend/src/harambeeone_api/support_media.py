import base64
import binascii
import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SOURCE_BYTES = 1_500_000
MAX_PIXELS = 12_000_000
MAX_OUTPUT_BYTES = 800_000


class CampaignMediaError(ValueError):
    pass


@dataclass(frozen=True)
class SanitizedCampaignImage:
    content: bytes
    mime_type: str
    content_hash: str
    width: int
    height: int


def sanitize_campaign_image(encoded: str, declared_mime: str) -> SanitizedCampaignImage:
    try:
        source = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise CampaignMediaError("The campaign image is not valid base64 data") from error
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise CampaignMediaError("Use a campaign image no larger than 1.5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(source)) as opened:
                opened.verify()
            with Image.open(io.BytesIO(source)) as opened:
                expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
                if expected.get(declared_mime) != opened.format:
                    raise CampaignMediaError("The image content does not match its file type")
                if opened.width * opened.height > MAX_PIXELS:
                    raise CampaignMediaError("The image dimensions are too large")
                if opened.width < 320 or opened.height < 240:
                    raise CampaignMediaError("Use an image at least 320 by 240 pixels")
                clean = ImageOps.exif_transpose(opened).convert("RGB")
                clean.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                clean.save(output, format="WEBP", quality=82, method=6)
                content = output.getvalue()
                width, height = clean.size
    except CampaignMediaError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise CampaignMediaError("The campaign image is invalid or unsafe") from error
    if len(content) > MAX_OUTPUT_BYTES:
        raise CampaignMediaError("The processed image is too large")
    return SanitizedCampaignImage(
        content=content,
        mime_type="image/webp",
        content_hash=hashlib.sha256(content).hexdigest(),
        width=width,
        height=height,
    )
