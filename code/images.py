from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from schemas import PreparedImage

SUPPORTED_DIRECT_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
AVIF_BRANDS = {b"avif", b"avis"}


def extract_image_id(image_path: str) -> str:
    return Path(image_path).stem


def resolve_image_path(repo_root: Path, image_path: str) -> Path:
    candidate = Path(image_path)
    if candidate.is_absolute():
        return candidate

    direct = repo_root / candidate
    if direct.exists():
        return direct

    dataset_relative = repo_root / "dataset" / candidate
    if dataset_relative.exists():
        return dataset_relative

    return dataset_relative


def detect_mime_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if _has_avif_brand(data):
        return "image/avif"
    return "application/octet-stream"


def _has_avif_brand(data: bytes) -> bool:
    if len(data) < 16 or data[4:8] != b"ftyp":
        return False

    box_size = int.from_bytes(data[0:4], "big")
    box_end = min(box_size, len(data)) if box_size >= 16 else len(data)
    brand_data = data[8:box_end]
    brands = [brand_data[:4]]
    brands.extend(
        brand_data[index : index + 4]
        for index in range(8, len(brand_data), 4)
        if len(brand_data[index : index + 4]) == 4
    )
    return any(brand in AVIF_BRANDS for brand in brands)


def _unreadable_image(
    image_id: str,
    image_path: str,
    absolute_path: Path,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    error: str,
) -> PreparedImage:
    return PreparedImage(
        image_id=image_id,
        original_path=image_path,
        absolute_path=absolute_path,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha256,
        data_base64="",
        readable=False,
        error=error,
    )


def _convert_avif_to_png_bytes(path: Path) -> bytes | None:
    try:
        import pillow_avif  # noqa: F401
        from PIL import Image
    except Exception:
        return None

    try:
        with Image.open(path) as image:
            output = BytesIO()
            image.convert("RGB").save(output, format="PNG")
            return output.getvalue()
    except Exception:
        return None


def _image_bytes_are_decodable(data: bytes) -> bool:
    try:
        from PIL import Image
    except Exception:
        return False

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        return True
    except Exception:
        return False


def prepare_image(repo_root: Path, image_path: str) -> PreparedImage:
    absolute_path = resolve_image_path(repo_root, image_path)
    image_id = extract_image_id(image_path)

    if not absolute_path.exists():
        return _unreadable_image(
            image_id=image_id,
            image_path=image_path,
            absolute_path=absolute_path,
            mime_type="application/octet-stream",
            size_bytes=0,
            sha256="",
            error=f"Image file not found: {image_path}",
        )

    try:
        original_bytes = absolute_path.read_bytes()
    except OSError as exc:
        return _unreadable_image(
            image_id=image_id,
            image_path=image_path,
            absolute_path=absolute_path,
            mime_type="application/octet-stream",
            size_bytes=0,
            sha256="",
            error=f"Image file could not be read: {exc}",
        )

    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    original_mime_type = detect_mime_type(original_bytes)
    payload = original_bytes
    mime_type = original_mime_type

    if original_mime_type == "image/avif":
        converted = _convert_avif_to_png_bytes(absolute_path)
        if converted is None:
            return _unreadable_image(
                image_id=image_id,
                image_path=image_path,
                absolute_path=absolute_path,
                mime_type=original_mime_type,
                size_bytes=len(original_bytes),
                sha256=original_sha256,
                error="AVIF image conversion is unsupported or failed",
            )
        payload = converted
        mime_type = "image/png"

    if mime_type not in SUPPORTED_DIRECT_MIME_TYPES:
        return _unreadable_image(
            image_id=image_id,
            image_path=image_path,
            absolute_path=absolute_path,
            mime_type=mime_type,
            size_bytes=len(original_bytes),
            sha256=original_sha256,
            error=f"Unsupported image MIME type: {mime_type}",
        )

    if not _image_bytes_are_decodable(payload):
        return _unreadable_image(
            image_id=image_id,
            image_path=image_path,
            absolute_path=absolute_path,
            mime_type=mime_type,
            size_bytes=len(payload),
            sha256=original_sha256,
            error=f"Image file could not be decoded as {mime_type}",
        )

    return PreparedImage(
        image_id=image_id,
        original_path=image_path,
        absolute_path=absolute_path,
        mime_type=mime_type,
        size_bytes=len(payload),
        sha256=original_sha256,
        data_base64=base64.b64encode(payload).decode("ascii"),
    )


def prepare_images(repo_root: Path, image_paths: str) -> list[PreparedImage]:
    return [
        prepare_image(repo_root, image_path.strip())
        for image_path in image_paths.split(";")
        if image_path.strip()
    ]
