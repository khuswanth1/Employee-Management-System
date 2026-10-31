"""Tenant-scoped file storage on local disk (swap for S3/MinIO in production)."""
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import AppError, NotFound

# Allow-list: extension -> how the content must look. Anything not listed is refused (active content such as
# .html/.svg/.js/.exe is therefore never stored). The check looks at the bytes, not at the client's Content-Type.
_OOXML = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_MAGIC: dict[str, tuple[bytes, ...] | None] = {
    ".pdf": (b"%PDF",), ".png": (_PNG,), ".jpg": (_JPEG,), ".jpeg": (_JPEG,), ".gif": (b"GIF87a", b"GIF89a"),
    ".docx": (_OOXML,), ".xlsx": (_OOXML,), ".pptx": (_OOXML,), ".doc": (_OLE,), ".xls": (_OLE,), ".ppt": (_OLE,),
    ".webp": None, ".txt": None, ".csv": None, ".md": None,  # None = special-cased below
}
ALLOWED_EXT = frozenset(_MAGIC)


def content_matches(ext: str, data: bytes) -> bool:
    if ext == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ext in (".txt", ".csv", ".md"):
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return any(data.startswith(m) for m in _MAGIC[ext] or ())


def _dir(company_id: int) -> Path:
    d = Path(get_settings().upload_dir) / f"t{company_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_filename(name: str | None) -> str:
    base = Path((name or "file").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:200]
    return base or "file"


async def save_upload(company_id: int, file: UploadFile) -> tuple[str, str, int]:
    """Returns (display_name, stored_name, size). Raises AppError on bad type / size."""
    name = safe_filename(file.filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise AppError("This file type is not allowed. Allowed: " + ", ".join(sorted(e.lstrip(".") for e in ALLOWED_EXT)))
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(f"File exceeds {limit // (1024 * 1024)} MB limit", status_code=413)
    if not content_matches(ext, data):
        raise AppError("The file content does not match its type")
    stored = uuid.uuid4().hex
    (_dir(company_id) / stored).write_bytes(data)
    return name, stored, len(data)


def path_for(company_id: int, stored_name: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", stored_name):
        raise NotFound()
    p = _dir(company_id) / stored_name
    if not p.exists():
        raise NotFound("File missing")
    return p


def delete_file(company_id: int, stored_name: str) -> None:
    try:
        path_for(company_id, stored_name).unlink(missing_ok=True)
    except NotFound:
        pass


AVATAR_MAX_BYTES = 2 * 1024 * 1024
_AVATAR_TYPES = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"))


def sniff_image(data: bytes) -> str | None:
    """Content type from magic bytes (never trust the client's filename or Content-Type)."""
    for magic, ctype in _AVATAR_TYPES:
        if data.startswith(magic):
            return ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def save_avatar(company_id: int, file: UploadFile) -> str:
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if len(data) > AVATAR_MAX_BYTES:
        raise AppError("Image exceeds 2 MB limit", status_code=413)
    if sniff_image(data) is None:
        raise AppError("Please upload a JPEG, PNG or WebP image")
    stored = uuid.uuid4().hex
    (_dir(company_id) / stored).write_bytes(data)
    return stored


# ---- chat media ---------------------------------------------------------------------------------------
# Images, audio and voice recordings are stored under the same rules as documents (allow-list, magic bytes, size limit)
# and are the only things the chat serves inline, with their own content type: never anything the browser could run.
_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
_AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".webm": "audio/webm"}
CHAT_MAX_BYTES = 25 * 1024 * 1024


def _audio_matches(ext: str, data: bytes) -> bool:
    if ext == ".mp3":
        return data[:3] == b"ID3" or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if ext == ".wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if ext in (".ogg", ".oga", ".opus"):
        return data[:4] == b"OggS"
    if ext == ".m4a":
        return data[4:8] == b"ftyp"
    if ext == ".webm":
        return data[:4] == b"\x1a\x45\xdf\xa3"
    return False


async def save_chat_media(company_id: int, file: UploadFile, *, voice: bool = False) -> tuple[str, str, int, str, str]:
    """Returns (display_name, stored_name, size, content_type, kind) with kind image | audio | file.
    A browser voice recording (webm/ogg/mp4) is only accepted when it is declared as `voice`."""
    name = safe_filename(file.filename)
    ext = Path(name).suffix.lower()
    limit = CHAT_MAX_BYTES  # music and recordings are larger than the 10 MB document limit
    if ext == ".webm" and not voice:
        raise AppError("Only voice recordings can be sent as WebM")
    if ext in _IMAGE_TYPES or ext in _AUDIO_TYPES or ext in ALLOWED_EXT:
        data = await file.read(limit + 1)
    else:
        raise AppError("This file type is not allowed in chat. Allowed: images, audio, PDF, Office documents and plain text")
    if len(data) > limit:
        raise AppError(f"File exceeds {limit // (1024 * 1024)} MB limit", status_code=413)
    if ext in _AUDIO_TYPES:
        if not _audio_matches(ext, data):
            raise AppError("The file content does not match its type")
        ctype, kind = _AUDIO_TYPES[ext], "audio"
    elif ext in _IMAGE_TYPES:
        if not content_matches(ext, data):
            raise AppError("The file content does not match its type")
        ctype, kind = _IMAGE_TYPES[ext], "image"
    else:
        if not content_matches(ext, data):
            raise AppError("The file content does not match its type")
        ctype, kind = "application/octet-stream", "file"
    stored = uuid.uuid4().hex
    (_dir(company_id) / stored).write_bytes(data)
    return name, stored, len(data), ctype, kind
