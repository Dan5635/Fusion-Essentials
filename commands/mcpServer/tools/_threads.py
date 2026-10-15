# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Thread-table lookup shared by model_hole and model_thread."""

from difflib import SequenceMatcher

import adsk.fusion

from ._common import named_with_remainder, safe

MAP_BLURB = ("resolve_thread_info - the ONE thread-table walk turning a bare designation "
             "('M5x0.8', '1/4-20 UNC') into a ThreadInfo, shared by model_hole's tap and "
             "model_thread; also returns every thread type carrying that designation")


def thread_types_for(tdq, designation, candidates=None):
    """Every thread type whose table carries `designation`, in library order."""
    hits = []
    for ttype in (safe(lambda: list(tdq.allThreadTypes), []) or []):
        for size in (safe(lambda t=ttype: list(tdq.allSizes(t)), []) or []):
            desigs = safe(lambda t=ttype, s=size: list(tdq.allDesignations(t, s)), []) or []
            if candidates is not None:
                candidates.extend((ttype, d) for d in desigs)
            if designation in desigs:
                hits.append(ttype)
                break
    return hits


def _nearby_choices(tdq, candidates, designation, internal, thread_type, thread_class):
    """Return bounded actual nearby spellings, preferring the supplied type and class."""
    ranked = sorted(dict.fromkeys(candidates),
                    key=lambda row: (SequenceMatcher(None, designation, row[1]).ratio(), row[1]),
                    reverse=True)
    matching, alternatives, class_cache = [], [], {}
    def classes_for(ttype, desig):
        key = (ttype, desig)
        if key not in class_cache and len(class_cache) < 20:
            class_cache[key] = safe(lambda: list(tdq.allClasses(internal, ttype, desig)), []) or []
        return class_cache.get(key, [])
    compatible_ranked = ([row for row in ranked if row[0].lower() == thread_type.lower()]
                         if thread_type else ranked)
    for ttype, desig in compatible_ranked[:10]:
        if SequenceMatcher(None, designation, desig).ratio() < 0.6:
            continue
        classes = classes_for(ttype, desig)
        compatible_classes = ([c for c in classes if c.lower() == thread_class.lower()]
                              if thread_class else classes)
        if compatible_classes:
            matching.append(f"'{desig}' in '{ttype}' (classes: {', '.join(compatible_classes[:3])})")
            if len(matching) == 5:
                break
    if matching:
        return "; ".join(matching)
    for ttype, desig in ranked[:10]:
        if SequenceMatcher(None, designation, desig).ratio() < 0.6:
            continue
        classes = classes_for(ttype, desig)
        if classes:
            alternatives.append(f"'{desig}' in '{ttype}' (classes: {', '.join(classes[:3])})")
            if len(alternatives) == 5:
                break
    return "; ".join(alternatives)


def _nearest_per_type(candidates, designation, thread_type):
    """The closest designation each thread type lists, the supplied type first; past five, the rest counted."""
    best = {}
    for ttype, desig in dict.fromkeys(candidates):
        score = (SequenceMatcher(None, designation, desig).ratio(), desig)
        if ttype not in best or score > best[ttype]:
            best[ttype] = score
    ranked = sorted(best.items(), key=lambda row: (row[0].lower() == thread_type.lower(), row[1]),
                    reverse=True)
    more = f"; {len(ranked) - 5} more thread type(s) not listed" if len(ranked) > 5 else ""
    return "; ".join(f"'{desig}' in '{ttype}'" for ttype, (_ratio, desig) in ranked[:5]) + more


def resolve_thread_info(designation, internal=True, thread_type="", thread_class="",
                        right_handed=True):
    """Build a straight ThreadInfo for a thread DESIGNATION like 'M5x0.8'. `thread_type` picks the
    standard when several carry it, `thread_class` the fit within it, `right_handed` the hand.
    Returns (threadInfo, types_carrying_it, None) or (None, types, error)."""
    # The False is isTapered: the straight-thread library, as in ThreadInfo.create below.
    tdq = safe(lambda: adsk.fusion.ThreadDataQuery.create(False))
    if tdq is None:
        return None, [], "Thread data query unavailable."

    candidates = []
    hits = thread_types_for(tdq, designation, candidates)
    if not hits:
        wanted_type = (thread_type or "").strip()
        choices = _nearby_choices(tdq, candidates, designation, internal,
                                  wanted_type, (thread_class or "").strip())
        nearest = "" if choices else _nearest_per_type(candidates, designation, wanted_type)
        types = [] if choices or nearest else safe(lambda: list(tdq.allThreadTypes), []) or []
        remedy = (f"Nearby library spellings (not fit recommendations): {choices}. "
                  "Choose a listed designation, type and class, then retry; no selector was changed."
                  if choices else
                  "No nearby alternative with readable classes was found. Closest designation per "
                  f"thread type: {nearest}. Retry with one as designation and its thread_type."
                  if nearest else
                  "No designation in the thread library read; its thread types: "
                  f"{named_with_remainder([str(t) for t in types]) or '(none read)'}.")
        return None, [], f"No thread designation '{designation}' found in the thread library. {remedy}"
    want = (thread_type or "").strip()
    if want:
        chosen = next((t for t in hits if t.lower() == want.lower()), None)
        if chosen is None:
            return None, hits, (f"Thread type '{thread_type}' does not carry '{designation}'. "
                                f"Types that do: {', '.join(hits)}.")
    else:
        # Types sharing a designation build ThreadInfos equal in every scalar but threadType, so
        # library order picks one; the caller is returned `hits` to see what else carried it.
        chosen = hits[0]

    # A class is a fit tolerance, not interchangeable: 4g6g and 6g are different fits of one thread.
    classes = safe(lambda: list(tdq.allClasses(internal, chosen, designation)), []) or []
    want = (thread_class or "").strip()
    if want:
        cls = next((c for c in classes if c.lower() == want.lower()), None)
        if cls is None:
            return None, hits, (f"Thread class '{thread_class}' is not offered for '{designation}' "
                                f"in '{chosen}'. Classes that are: {', '.join(classes) or '(none)'}.")
    else:
        cls = classes[0] if classes else ""
    ti = safe(lambda: adsk.fusion.ThreadInfo.create(False, internal, chosen, designation, cls,
                                                    bool(right_handed)))
    if ti is None:
        return None, hits, f"ThreadInfo.create failed for '{designation}' in '{chosen}'."
    return ti, hits, None
