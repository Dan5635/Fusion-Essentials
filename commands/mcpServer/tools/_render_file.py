"""Read rendered image dimensions and file completeness without image libraries."""

from pathlib import Path
import struct
import zlib


_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8"
_TIFF = (b"II*\x00", b"MM\x00*")
_BLOCK = 65536
_SUFFIX_FORMAT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg",
                  ".tif": "tiff", ".tiff": "tiff"}


def _read(stream, size):
    """Read exactly size bytes, or None at a short file."""
    data = stream.read(size)
    return data if len(data) == size else None


def _png(stream, size):
    """Read PNG chunks through the terminal IEND, checking their CRCs."""
    if _read(stream, 8) != _PNG:
        return "partial", None, None, "PNG signature is incomplete."
    width = height = None
    saw_data = False
    first = True
    while stream.tell() < size:
        header = _read(stream, 8)
        if header is None:
            return "partial", width, height, "PNG chunk header is incomplete."
        length, kind = struct.unpack(">I4s", header)
        if length > 0x7fffffff:
            return "invalid", width, height, "PNG chunk length is invalid."
        if stream.tell() + length + 4 > size:
            return "partial", width, height, "PNG chunk is incomplete."
        if first and (kind != b"IHDR" or length != 13):
            return "invalid", width, height, "PNG has no first IHDR chunk."
        first = False
        crc = zlib.crc32(kind)
        content = b""
        remaining = length
        while remaining:
            block = _read(stream, min(remaining, _BLOCK))
            if block is None:
                return "partial", width, height, "PNG chunk is incomplete."
            if kind == b"IHDR":
                content += block
            crc = zlib.crc32(block, crc)
            remaining -= len(block)
        recorded = _read(stream, 4)
        if recorded is None:
            return "partial", width, height, "PNG chunk CRC is incomplete."
        if struct.unpack(">I", recorded)[0] != crc:
            return "invalid", width, height, "PNG chunk CRC does not match."
        if kind == b"IHDR":
            if width is not None or length != 13:
                return "invalid", width, height, "PNG has an extra IHDR chunk."
            width, height = struct.unpack(">II", content[:8])
            if not width or not height or width > 0x7fffffff or height > 0x7fffffff:
                return "invalid", width, height, "PNG dimensions are invalid."
        elif kind == b"IDAT":
            if not length:
                return "invalid", width, height, "PNG image data is empty."
            saw_data = True
        elif kind == b"IEND":
            if length != 0 or not saw_data or stream.tell() != size:
                return "invalid", width, height, "PNG terminal chunk is invalid."
            return "valid", width, height, None
    return "partial", width, height, "PNG has no complete IEND chunk."


def _jpeg_marker(stream, scan, size):
    """Find the next JPEG marker, skipping stuffed bytes inside a scan."""
    while stream.tell() < size:
        if scan:
            start = stream.tell()
            block = stream.read(min(_BLOCK, size - start))
            offset = block.find(b"\xff")
            if offset < 0:
                continue
            stream.seek(start + offset + 1)
        elif stream.read(1) != b"\xff":
            return -1
        while stream.tell() < size:
            code = stream.read(1)[0]
            if code == 0xff:
                continue
            if scan and (code == 0 or 0xd0 <= code <= 0xd7):
                break
            return code
    return None


def _jpeg(stream, size):
    """Read JPEG frame dimensions and follow scans to EOI."""
    if _read(stream, 2) != _JPEG:
        return "partial", None, None, "JPEG signature is incomplete."
    width = height = None
    scan = False
    saw_scan = False
    while stream.tell() < size:
        marker = _jpeg_marker(stream, scan, size)
        if marker is None:
            break
        if marker == -1:
            return "invalid", width, height, "JPEG has data outside a scan."
        scan = False
        if marker == 0xd9:
            if width is None or not saw_scan or stream.tell() != size:
                return "invalid", width, height, "JPEG ending or frame is invalid."
            return "valid", width, height, None
        if marker in (0xd8, *range(0xd0, 0xd8), 0x01):
            return "invalid", width, height, "JPEG marker is out of place."
        raw_length = _read(stream, 2)
        if raw_length is None:
            return "partial", width, height, "JPEG segment length is incomplete."
        length = struct.unpack(">H", raw_length)[0]
        if length < 2:
            return "invalid", width, height, "JPEG segment length is invalid."
        payload = _read(stream, length - 2)
        if payload is None:
            return "partial", width, height, "JPEG segment is incomplete."
        if marker in tuple(m for m in range(0xc0, 0xd0) if m not in (0xc4, 0xc8, 0xcc)):
            if len(payload) < 6 or payload[0] == 0:
                return "invalid", width, height, "JPEG frame header is invalid."
            next_height, next_width = struct.unpack(">HH", payload[1:5])
            if not next_width or not next_height or (width is not None and
                                                    (width, height) != (next_width, next_height)):
                return "invalid", width, height, "JPEG dimensions are invalid."
            width, height = next_width, next_height
        if marker == 0xda:
            scan = True
            saw_scan = True
    return "partial", width, height, "JPEG has no complete EOI marker."


def _tiff_values(stream, size, endian, kind, count, slot):
    """Read one bounded TIFF SHORT/LONG tag array."""
    item_size = {3: 2, 4: 4}.get(kind)
    if item_size is None or count < 1 or count > 65536:
        return None
    byte_count = item_size * count
    if byte_count <= 4:
        data = slot[:byte_count]
    else:
        offset = int.from_bytes(slot, endian)
        if offset > size or byte_count > size - offset:
            return None
        place = stream.tell()
        stream.seek(offset)
        data = _read(stream, byte_count)
        stream.seek(place)
        if data is None:
            return None
    return [int.from_bytes(data[i:i + item_size], endian)
            for i in range(0, byte_count, item_size)]


def _tiff(stream, size, signature):
    """Read the first TIFF IFD and verify its strip or tile byte ranges."""
    endian = "little" if signature == _TIFF[0] else "big"
    stream.seek(4)
    raw = _read(stream, 4)
    if raw is None:
        return "partial", None, None, "TIFF header is incomplete."
    offset = int.from_bytes(raw, endian)
    if offset > size - 2:
        return "partial", None, None, "TIFF image directory is incomplete."
    stream.seek(offset)
    raw = _read(stream, 2)
    if raw is None:
        return "partial", None, None, "TIFF image directory is incomplete."
    count = int.from_bytes(raw, endian)
    if count > 4096:
        return "invalid", None, None, "TIFF image directory is too large to verify."
    if stream.tell() + count * 12 + 4 > size:
        return "partial", None, None, "TIFF image directory is incomplete."
    tags = {}
    for _ in range(count):
        entry = _read(stream, 12)
        tag = int.from_bytes(entry[:2], endian)
        kind = int.from_bytes(entry[2:4], endian)
        n = int.from_bytes(entry[4:8], endian)
        if tag in (256, 257, 273, 279, 324, 325):
            if tag in tags:
                return "invalid", None, None, "TIFF repeats a required tag."
            tags[tag] = _tiff_values(stream, size, endian, kind, n, entry[8:12])
    width = tags.get(256)
    height = tags.get(257)
    width = width[0] if width and len(width) == 1 else None
    height = height[0] if height and len(height) == 1 else None
    if not width or not height:
        return "invalid", width, height, "TIFF dimensions are absent or invalid."
    pair = (273, 279) if 273 in tags or 279 in tags else (324, 325)
    offsets, lengths = tags.get(pair[0]), tags.get(pair[1])
    if not offsets or not lengths or len(offsets) != len(lengths):
        return "partial", width, height, "TIFF pixel byte ranges are not readable."
    if any(not length or start > size or length > size - start
           for start, length in zip(offsets, lengths)):
        return "partial", width, height, "TIFF pixel data is incomplete."
    return "valid", width, height, None


def inspect_image_file(path, expected_width=None, expected_height=None):
    """Return a bounded image-file verification result, including incomplete states."""
    result = {"status": "invalid", "format": None, "width": None, "height": None,
              "bytes": 0, "reason": None}
    try:
        file = Path(path)
        result["bytes"] = file.stat().st_size
        with file.open("rb") as stream:
            signature = stream.read(8)
            stream.seek(0)
            if signature.startswith(_PNG) or _PNG.startswith(signature) and signature:
                result["format"] = "png"
                status, width, height, reason = _png(stream, result["bytes"])
            elif signature.startswith(_JPEG) or _JPEG.startswith(signature) and signature:
                result["format"] = "jpeg"
                status, width, height, reason = _jpeg(stream, result["bytes"])
            elif signature[:4] in _TIFF or any(s.startswith(signature) for s in _TIFF) and signature:
                result["format"] = "tiff"
                status, width, height, reason = _tiff(stream, result["bytes"], signature[:4])
            else:
                return {**result, "reason": "Image signature is not PNG, JPEG or TIFF."}
    except FileNotFoundError:
        return {**result, "status": "missing", "reason": "Image file does not exist."}
    except OSError:
        return {**result, "reason": "Image file could not be read."}
    result.update(status=status, width=width, height=height, reason=reason)
    expected_format = _SUFFIX_FORMAT.get(file.suffix.lower())
    if result["status"] == "valid" and expected_format is not None and result["format"] != expected_format:
        result.update(status="invalid", reason="Image format differs from the output extension.")
    try:
        if file.stat().st_size != result["bytes"]:
            result.update(status="partial", reason="Image file changed during verification.")
    except OSError:
        result.update(status="partial", reason="Image file changed during verification.")
    if result["status"] == "valid" and (expected_width is not None and width != expected_width
                                        or expected_height is not None and height != expected_height):
        result.update(status="invalid", reason="Image dimensions differ from the request.")
    return result
