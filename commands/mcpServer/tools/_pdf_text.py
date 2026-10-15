# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Read text runs from a bounded Fusion-exported drawing PDF."""

import math
import os
import re
import zlib

MAP_BLURB = ("the exported-PDF text reader, pure Python: read - (document, error) for a PDF "
             "path: its modified time and per page its label, size in mm and text runs as "
             "{text, x, y, angle, layer}; MAX_FILE_BYTES/MAX_STREAM_BYTES/MAX_INFLATED_BYTES - "
             "the file, one-stream and all-streams sizes it stops at")

# The reader runs on Fusion's main thread, so each size it will walk is capped: the file, one
# decoded stream, and every decoded stream of the file together.
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_INFLATED_BYTES = 4 * 1024 * 1024
# what an odd file's structure can raise from the walk below; each comes back as a refusal
_FAULTS = (IndexError, KeyError, TypeError, ValueError, AttributeError, OverflowError,
           RecursionError, zlib.error)
_PT_TO_MM = 25.4 / 72
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
# text operators that place a string from state this reader does not keep
_UNFOLLOWED = ("Td", "TD", "T*", "'", '"')

_TOKEN = re.compile(rb"""
    (?P<ref>\d+\s+\d+\s+R(?![A-Za-z]))
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<name>/[^\s()<>\[\]{}/%]*)
  | (?P<str>\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\))
  | (?P<open><<|\[)
  | (?P<close>>>|\])
  | (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<op>[^\s()<>\[\]{}/%]+)
  | %[^\r\n]*
""", re.X | re.S)
_NAME_HEX = re.compile(rb"#([0-9A-Fa-f]{2})")
_ESCAPE = re.compile(rb"\\([0-7]{1,3}|\r\n|.)", re.S)
_ESCAPED = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
            b"\n": b"", b"\r": b"", b"\r\n": b""}
_STARTXREF = re.compile(rb"startxref\s+(\d+)")
_SECTION = re.compile(rb"\s*(\d+)\s+(\d+)")
_ENTRY = re.compile(rb"\s*(\d{10}) (\d{5}) ([nf])")
_TRAILER = re.compile(rb"\s*trailer")
_STREAM = re.compile(rb"\s*stream\r?\n")
_ENDSTREAM = re.compile(rb"\s*endstream")
_CODESPACE = re.compile(rb"begincodespacerange\s*<([0-9A-Fa-f]+)>")
_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>")


class _Unread(Exception):
    """A structure this reader does not follow; its text completes the refusal."""


class _Name(str):
    """A PDF name object, told apart from a string object's bytes."""


class _Op(str):
    """A bare keyword: a content operator, or obj/stream/true/null."""


class _Ref(int):
    """An indirect reference, by object number."""


class _Stream:
    """A stream object: its dictionary and its undecoded bytes."""

    def __init__(self, info, raw):
        self.info, self.raw = info, raw


def _unescape(raw):
    """A literal string's bytes with its backslash escapes resolved."""
    def one(match):
        code = match.group(1)
        if code[:1].isdigit():
            return bytes([int(code, 8) & 255])
        return _ESCAPED.get(code, code)
    return _ESCAPE.sub(one, raw)


def _unhex(digits):
    """The bytes a hex string spells; whitespace is ignored and an odd digit count pads a zero."""
    digits = b"".join(digits.split())
    return bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode("ascii"))


def _values(data, pos=0):
    """(value, end offset) for each top-level PDF value from `pos` on, containers built whole."""
    stack = []
    for match in _TOKEN.finditer(data, pos):
        kind = match.lastgroup
        if kind is None:
            continue
        raw = match.group(kind)
        if kind == "open":
            stack.append([raw])
            continue
        if kind == "close":
            if not stack:
                raise _Unread(f"an unopened {raw.decode('ascii')} at byte {match.start()}")
            items = stack.pop()
            value = dict(zip(items[1::2], items[2::2])) if items[0] == b"<<" else items[1:]
        elif kind == "num":
            value = float(raw) if b"." in raw else int(raw)
        elif kind == "ref":
            value = _Ref(raw.split()[0])
        elif kind == "name":
            value = _Name(_NAME_HEX.sub(lambda h: bytes([int(h.group(1), 16)]), raw[1:])
                          .decode("latin-1"))
        elif kind == "str":
            value = _unescape(raw[1:-1])
        elif kind == "hex":
            value = _unhex(raw[1:-1])
        else:
            value = _Op(raw.decode("latin-1"))
        if stack:
            stack[-1].append(value)
        else:
            yield value, match.end()


def _text(raw):
    """A PDF text string decoded: UTF-16 behind its byte-order mark, else one byte per character."""
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be", "replace")
    return raw.decode("latin-1")


def _xref(data):
    """(object number -> byte offset, trailer) off the one classic xref table of the file."""
    found = _STARTXREF.findall(data[-2048:])
    if not data.startswith(b"%PDF-") or not found:
        raise _Unread("it has no %PDF- header with a startxref")
    at, offsets = int(found[-1]), {}
    if not data.startswith(b"xref", at):
        raise _Unread(f"byte {at} holds no xref table")
    pos = at + 4
    while not _TRAILER.match(data, pos):
        head = _SECTION.match(data, pos)
        if not head:
            raise _Unread(f"the xref table at byte {at} has no trailer")
        pos = head.end()
        for number in range(int(head.group(1)), int(head.group(1)) + int(head.group(2))):
            entry = _ENTRY.match(data, pos)
            if not entry:
                raise _Unread(f"the xref table at byte {at} is cut short")
            pos = entry.end()
            if entry.group(3) == b"n":
                offsets[number] = int(entry.group(1))
    trailer = next(_values(data, _TRAILER.match(data, pos).end()), (None, 0))[0]
    if not isinstance(trailer, dict):
        raise _Unread(f"the trailer after byte {at} is not a dictionary")
    if "Prev" in trailer:
        raise _Unread(f"the xref table at byte {at} continues an earlier one")
    return offsets, trailer


class _Document:
    """A PDF's objects, fetched by number through its xref offsets."""

    def __init__(self, data):
        self.data = data
        self.offsets, self.trailer = _xref(data)
        self.cache, self.cmaps, self.inflated = {}, {}, 0

    def get(self, value):
        """`value`, with an indirect reference followed to the object it names."""
        hops = 0
        while isinstance(value, _Ref):
            hops += 1
            if hops > 16:
                raise _Unread(f"object {int(value)} is a reference loop")
            value = self._object(int(value))
        return value

    def _object(self, number):
        if number in self.cache:
            return self.cache[number]
        offset = self.offsets.get(number)
        value = None
        if offset is not None:
            values = _values(self.data, offset)
            head = [next(values, (None, 0))[0] for _ in range(3)]
            if head[0] != number or head[2] != "obj":
                raise _Unread(f"object {number} is not at its xref offset {offset}")
            value, end = next(values, (None, 0))
            started = _STREAM.match(self.data, end) if isinstance(value, dict) else None
            if started:
                value = _Stream(value, self._raw(value, started.end()))
        self.cache[number] = value
        return value

    def _raw(self, info, start):
        length = self.get(info.get("Length"))
        end = start + length if type(length) is int else -1
        if end < 0 or not _ENDSTREAM.match(self.data, end):
            end = self.data.find(b"endstream", start)
        if end < 0:
            raise _Unread(f"the stream at byte {start} has no endstream")
        return self.data[start:end]

    def decoded(self, stream, what):
        """Decode one stream under the one-stream and all-streams caps."""
        filters = self.get(stream.info.get("Filter"))
        filters = [] if filters is None else filters if isinstance(filters, list) else [filters]
        out = stream.raw
        if filters:
            parms = self.get(stream.info.get("DecodeParms"))
            parms = self.get(parms[0]) if isinstance(parms, list) and parms else parms
            predictor = self.get(parms.get("Predictor")) if isinstance(parms, dict) else None
            names = [str(self.get(f)) for f in filters]
            if names != ["FlateDecode"] or predictor not in (None, 1):
                raise _Unread(f"{what} is stored with filter {'+'.join(names)} and predictor "
                              f"{predictor}")
            try:
                out = zlib.decompressobj().decompress(stream.raw, MAX_STREAM_BYTES + 1)
            except zlib.error as ex:
                raise _Unread(f"{what} did not inflate ({ex})")
        if len(out) > MAX_STREAM_BYTES:
            raise _Unread(f"{what} decodes to more than {MAX_STREAM_BYTES} bytes")
        self.inflated += len(out)
        if self.inflated > MAX_INFLATED_BYTES:
            raise _Unread(f"its streams decode to more than {MAX_INFLATED_BYTES} bytes together")
        return out


def _mul(m, n):
    """The matrix that applies m, then n - both in PDF [a b c d e f] order."""
    a, b, c, d, e, f = m
    g, h, i, j, k, l = n
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j,
            e * g + f * i + k, e * h + f * j + l)


def _six(args, op, page):
    """An operator's six matrix numbers, refused when it does not carry them."""
    tail = tuple(args[-6:])
    if len(tail) != 6 or not all(type(v) in (int, float) for v in tail):
        raise _Unread(f"page {page} has a {op} operator without six numbers")
    return tail


def _cmap(doc, font, label):
    """(bytes per code, code -> text) off a font's ToUnicode map, decoded once per document."""
    font = doc.get(font)
    stream = doc.get(font.get("ToUnicode")) if isinstance(font, dict) else None
    if not isinstance(stream, _Stream):
        raise _Unread(f"font {label} carries no ToUnicode map")
    if id(stream) not in doc.cmaps:
        doc.cmaps[id(stream)] = _cmap_table(doc.decoded(
            stream, f"the ToUnicode map of font {label}"), label)
    return doc.cmaps[id(stream)]


def _cmap_table(body, label):
    """(bytes per code, code -> text) for one decoded ToUnicode map."""
    table = {}
    for block in _BFCHAR.findall(body):
        for source, target in _PAIR.findall(block):
            table[_unhex(source)] = _unhex(target).decode("utf-16-be", "replace")
    if b"beginbfrange" in body:
        raise _Unread(f"the ToUnicode map of font {label} maps codes by bfrange")
    spans = _CODESPACE.findall(body)
    width = len(spans[0]) // 2 if spans else len(next(iter(table), b""))
    if not width:
        raise _Unread(f"the ToUnicode map of font {label} maps no code")
    return width, table


def _shown(piece, cmap, label, page):
    """The text one shown string spells through its font's map; an unmapped code is refused."""
    width, table = cmap
    out = []
    for at in range(0, len(piece), width):
        code = piece[at:at + width]
        if code not in table:
            raise _Unread(f"page {page} shows code <{code.hex()}>, which font {label} maps to no "
                          "text")
        out.append(table[code])
    return "".join(out)


def _layer(doc, layers, given):
    """The name of the optional-content layer a BDC operator opens, or None when it opens none."""
    if len(given) < 2 or given[-2] != "OC" or not isinstance(layers, dict):
        return None
    entry = doc.get(layers.get(given[-1])) if isinstance(given[-1], _Name) else None
    name = doc.get(entry.get("Name")) if isinstance(entry, dict) else None
    return _text(name) if isinstance(name, bytes) else None


def _runs(doc, resources, content, page):
    """One page's text runs in default user space: [{text, x, y, angle, layer}] in stream order."""
    resources = doc.get(resources)
    resources = resources if isinstance(resources, dict) else {}
    fonts = doc.get(resources.get("Font"))
    layers = doc.get(resources.get("Properties"))
    xobjects = doc.get(resources.get("XObject"))
    cmaps, ctm, saved, tm, font, marks, placed = {}, _IDENTITY, [], _IDENTITY, None, [], False
    runs, args = [], []
    for value, _end in _values(content):
        if not isinstance(value, _Op):
            args.append(value)
            continue
        op, args, given = value, [], args
        if op == "q":
            saved.append(ctm)
        elif op == "Q":
            ctm = saved.pop() if saved else ctm
        elif op == "cm":
            ctm = _mul(_six(given, op, page), ctm)
        elif op == "BT":
            tm, placed = _IDENTITY, False
        elif op == "Tm":
            tm, placed = _six(given, op, page), True
        elif op == "Tf":
            font = given[-2] if len(given) >= 2 else None
        elif op == "BDC":
            marks.append(_layer(doc, layers, given))
        elif op == "BMC":
            marks.append(None)
        elif op == "EMC":
            if marks:
                marks.pop()
        elif op in ("Tj", "TJ"):
            shown = given[-1] if given else None
            pieces = ([p for p in shown if isinstance(p, bytes)] if isinstance(shown, list)
                      else [shown] if isinstance(shown, bytes) else None)
            if pieces is None or not placed:
                raise _Unread(f"page {page} shows text with {op} that no Tm of its own places")
            placed = False
            if font not in cmaps:
                cmaps[font] = _cmap(doc, fonts.get(font) if isinstance(fonts, dict) else None,
                                    font)
            a, b, _c, _d, e, f = _mul(tm, ctm)
            runs.append({"text": "".join(_shown(p, cmaps[font], font, page) for p in pieces),
                         "x": e, "y": f, "angle": math.degrees(math.atan2(b, a)),
                         "layer": next((m for m in reversed(marks) if m is not None), None)})
        elif op in _UNFOLLOWED:
            raise _Unread(f"page {page} places text with the {op} operator")
        elif op == "ID":
            raise _Unread(f"page {page} holds an inline image")
        elif op == "Do":
            name = given[-1] if given else None
            target = doc.get(xobjects.get(name)) if isinstance(xobjects, dict) else None
            info = target.info if isinstance(target, _Stream) else {}
            subtype = doc.get(info.get("Subtype"))
            if subtype != "Image":
                raise _Unread(f"page {page} draws XObject {name}, whose Subtype reads {subtype}")
    return runs


def _page_nodes(doc, node, inherited, out, seen):
    """Append every leaf page under `node`, each with the attributes it inherits."""
    node = doc.get(node)
    if not isinstance(node, dict) or id(node) in seen:
        return
    seen.add(id(node))
    facts = dict(inherited)
    facts.update({k: node[k] for k in ("MediaBox", "Resources", "Rotate") if k in node})
    kids = doc.get(node.get("Kids"))
    if isinstance(kids, list):
        for kid in kids:
            _page_nodes(doc, kid, facts, out, seen)
    else:
        out.append(dict(facts, Contents=node.get("Contents"), UserUnit=node.get("UserUnit")))


def _labels(doc, node):
    """page index -> the label prefix a PageLabels entry starting at that page carries."""
    node = doc.get(node)
    nums = doc.get(node.get("Nums")) if isinstance(node, dict) else None
    nums = nums if isinstance(nums, list) else []
    out = {}
    for index, entry in zip(nums[0::2], nums[1::2]):
        entry = doc.get(entry)
        prefix = doc.get(entry.get("P")) if isinstance(entry, dict) else None
        if type(index) is int and isinstance(prefix, bytes):
            out[index] = _text(prefix)
    return out


def _page(doc, facts, number, label):
    """One page as {page, label, width, height, runs}, lengths in mm from its lower-left corner."""
    box = doc.get(facts.get("MediaBox"))
    box = [doc.get(v) for v in box] if isinstance(box, list) else []
    rotate, unit = doc.get(facts.get("Rotate")), doc.get(facts.get("UserUnit"))
    if len(box) != 4 or not all(type(v) in (int, float) for v in box):
        raise _Unread(f"page {number} has no four-number MediaBox")
    if rotate not in (None, 0) or unit not in (None, 1):
        raise _Unread(f"page {number} carries Rotate {rotate} and UserUnit {unit}")
    contents = doc.get(facts.get("Contents"))
    streams = [doc.get(c) for c in (contents if isinstance(contents, list) else [contents])]
    body = b"\n".join(doc.decoded(s, f"the content of page {number}")
                      for s in streams if isinstance(s, _Stream))
    left, bottom = min(box[0], box[2]), min(box[1], box[3])
    # a blank-only run is dropped; one starting off the page stays, as its glyphs can reach onto it
    runs = [{"text": r["text"], "x": round((r["x"] - left) * _PT_TO_MM, 2),
             "y": round((r["y"] - bottom) * _PT_TO_MM, 2), "angle": round(r["angle"], 1),
             "layer": r["layer"]}
            for r in _runs(doc, facts.get("Resources"), body, number) if r["text"].strip()]
    return {"page": number, "label": label,
            "width": round(abs(box[2] - box[0]) * _PT_TO_MM, 2),
            "height": round(abs(box[3] - box[1]) * _PT_TO_MM, 2), "runs": runs}


def read(path):
    """Return the pages and file modification time, or a PDF refusal."""
    try:
        with open(path, "rb") as handle:
            facts = os.fstat(handle.fileno())
            if facts.st_size > MAX_FILE_BYTES:
                return None, (f"'{path}' is {facts.st_size} bytes; this reader takes a PDF of up "
                              f"to {MAX_FILE_BYTES} bytes - export fewer sheets into it.")
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError as ex:
        return None, f"'{path}' could not be opened: {ex}"
    try:
        doc = _Document(data)
        catalog = doc.get(doc.trailer.get("Root"))
        if not isinstance(catalog, dict):
            raise _Unread("its trailer names no catalog")
        nodes, labels = [], _labels(doc, catalog.get("PageLabels"))
        _page_nodes(doc, catalog.get("Pages"), {}, nodes, set())
        pages = [_page(doc, node, i + 1, labels.get(i)) for i, node in enumerate(nodes)]
    except _Unread as ex:
        return None, f"'{path}' is not a PDF this reader follows: {ex}."
    except _FAULTS as ex:
        return None, (f"'{path}' is not a PDF this reader follows: its structure raised "
                      f"{type(ex).__name__} ({ex}).")
    return {"modified": facts.st_mtime, "page_count": len(pages), "pages": pages}, None
