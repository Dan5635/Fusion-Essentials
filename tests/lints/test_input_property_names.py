# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Every property assigned onto a FeatureInput must exist on that input's real class.

A SWIG proxy ACCEPTS an assignment to a name it does not define: the value lands on a dead Python
attribute, the object keeps its API default, and set_verified's read-back reads that back."""

import _corpus
import api_surface
from _input_resolution import _iter_tool_files, _named_assignments_in, _offenders_in, input_scopes

class TestInputPropertyNamesAreReal:
    def test_every_assigned_input_property_exists_on_its_class(self):
        offenders, checked = [], 0
        for name, path in _iter_tool_files():
            for nodes, bound in input_scopes(_corpus.tree(path)):
                checked += sum(1 for _l, var, _p in _named_assignments_in(nodes) if var in bound)
            for lineno, var, prop, cls in _offenders_in(path):
                members = api_surface.PROPERTIES[cls]
                near = [m for m in members if m.lower() == prop.lower()] or \
                       [m for m in members if prop.lower() in m.lower()]
                hint = f" Did you mean {near[0]}?" if near else \
                       f" {cls} has: {', '.join(members[:12])}."
                offenders.append(f"{name}:{lineno}: {var}.{prop} is not a member of {cls}.{hint}")
        assert checked, "nothing was checked: no property assignment on a resolved feature input was found"
        assert not offenders, (
            "a SWIG proxy accepts an unknown property name silently - the operation runs on its "
            "DEFAULT while the tool reports what was requested:\n  " + "\n  ".join(offenders))
