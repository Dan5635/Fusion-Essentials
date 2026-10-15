"""Image-file reads distinguish complete renders from missing or partial files."""

import struct
import zlib

from conftest import load_tool


inspect_image_file = load_tool("_render_file").inspect_image_file


def _chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data)))


def _png(width=3, height=2):
    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", head)
            + _chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00" * (width * 3)) * height))
            + _chunk(b"IEND", b""))


def _jpeg(width=3, height=2):
    frame = b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    return (b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame
            + b"\xff\xda\x00\x02" + b"\x12\x34\xff\x00\x56\xff\xd9")


def _tiff(width=3, height=2, byte_count=2):
    def tag(number, value):
        return struct.pack("<HHII", number, 4, 1, value)
    data_offset = 8 + 2 + 4 * 12 + 4
    return (b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 4)
            + tag(256, width) + tag(257, height) + tag(273, data_offset)
            + tag(279, byte_count) + struct.pack("<I", 0) + b"\x00" * 2)


def test_png_dimensions_and_crc_require_a_complete_file(tmp_path):
    file = tmp_path / "render.png"
    data = _png()
    file.write_bytes(data)
    assert inspect_image_file(file, 3, 2) == {
        "status": "valid", "format": "png", "width": 3, "height": 2,
        "bytes": len(data), "reason": None}
    file.write_bytes(data[:-6])
    partial = inspect_image_file(file)
    assert partial["status"] == "partial" and partial["format"] == "png"
    damaged = bytearray(data)
    damaged[20] ^= 1
    file.write_bytes(damaged)
    assert inspect_image_file(file)["status"] == "invalid"
    file.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", data[16:29])
                     + _chunk(b"IDAT", b"") + _chunk(b"IEND", b""))
    assert inspect_image_file(file)["status"] == "invalid"


def test_jpeg_frame_and_terminal_marker_are_checked(tmp_path):
    file = tmp_path / "render.jpg"
    data = _jpeg()
    file.write_bytes(data)
    assert inspect_image_file(file, 3, 2)["status"] == "valid"
    file.write_bytes(data[:-2])
    partial = inspect_image_file(file)
    assert (partial["status"], partial["width"], partial["height"]) == ("partial", 3, 2)
    file.write_bytes(data[:2] + b"stray" + data[2:])
    assert inspect_image_file(file)["status"] == "invalid"


def test_tiff_directory_and_pixel_range_are_checked(tmp_path):
    file = tmp_path / "render.tif"
    file.write_bytes(_tiff())
    assert inspect_image_file(file, 3, 2)["status"] == "valid"
    file.write_bytes(_tiff(byte_count=3))
    result = inspect_image_file(file)
    assert result["status"] == "partial" and result["format"] == "tiff"
    assert (result["width"], result["height"]) == (3, 2)


def test_missing_corrupt_and_wrong_size_are_distinct(tmp_path):
    file = tmp_path / "render.png"
    assert inspect_image_file(file)["status"] == "missing"
    file.write_bytes(b"not an image")
    assert inspect_image_file(file)["status"] == "invalid"
    file.write_bytes(_png())
    result = inspect_image_file(file, expected_width=4)
    assert result["status"] == "invalid" and result["reason"] == "Image dimensions differ from the request."
    assert (result["width"], result["height"]) == (3, 2)


def test_complete_jpeg_under_png_extension_is_not_verified(tmp_path):
    file = tmp_path / "render.png"
    file.write_bytes(_jpeg())
    result = inspect_image_file(file, 3, 2)
    assert result["format"] == "jpeg" and result["status"] == "invalid"
    assert result["reason"] == "Image format differs from the output extension."
