# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Publish source-stamped guidance resources captured at add-in load."""

from . import loader
from . import render

# The address space this server names its packaged documents in. The id in the address is the
# document's own, so the URI a tool payload publishes and the URI the resource listing carries are
# one string built one way.
URI_PREFIX = "fusion-essentials://guidance/"

# Rendered guidance is Markdown - headings and rules, not a data structure to parse.
MIME_TYPE = "text/markdown"


def uri_for(guidance_id):
    """The resource URI naming one guidance document."""
    return f"{URI_PREFIX}{guidance_id}"


def section_uri_for(guidance_id, section_id):
    """The resource URI naming ONE section of one guidance document."""
    return f"{URI_PREFIX}{guidance_id}/{section_id}"


def _entry(uri, name, title, description, text):
    return {
        "uri": uri,
        "name": name,
        "title": title,
        "description": description,
        "mimeType": MIME_TYPE,
        # Bytes of the text a read returns - the size the client is deciding whether to fetch.
        "size": len(text.encode("utf-8")),
        "text": text,
    }


def catalog(path=None):
    """Return whole and section resource snapshots, or raise GuidanceUnavailable."""
    doc, sha256 = loader.load(path)
    guidance_id = doc.get("guidance_id")
    stamp = (f"\n\nSource: guidance_id={guidance_id}; sha256={sha256}. "
             "Resource snapshot: reload the add-in after packaged guidance changes.\n")
    entries = [_entry(uri_for(guidance_id), doc.get("name"), doc.get("title"),
                      doc.get("description"), render.body(doc) + stamp)]
    for sec in (doc.get("sections") or []):
        if not isinstance(sec, dict) or sec.get("id") == loader.KERNEL:
            continue
        section_id = sec.get("id")
        entries.append(_entry(section_uri_for(guidance_id, section_id),
                              f"{guidance_id}/{section_id}", sec.get("title"),
                              sec.get("use_when"), render.section_text(doc, section_id) + stamp))
    return entries
