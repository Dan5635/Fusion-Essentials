# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The harness reaper's filter: which Local library assets a run may delete from the operator's library."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live"))
import verify_core  # noqa: E402

NOW = time.mktime(time.strptime("20261011-120000", "%Y%m%d-%H%M%S"))


def _leaves(assets, **kw):
    return [leaf for _, _, leaf in verify_core.harness_leftovers(assets, NOW, **kw)]


def _asset(leaf, kind="machine"):
    return (kind, "user://" + leaf, leaf)


def test_an_operators_asset_that_merely_contains_a_harness_name_is_kept():
    assets = [_asset("My SweepMach3Axis 20261001-080000.mch"),
              _asset("SweepMach3Axis 20261001-080000 copy.mch"),
              _asset("MeasureDeleteMe2.mch"),
              _asset("Generic 3-axis.mch"),
              _asset("Copy G59 to G55.f3dhsm-template", "template")]
    assert _leaves(assets) == []


def test_an_old_stamped_asset_and_every_unstamped_measure_asset_go():
    assets = [_asset("SweepMach3Axis 20261008-090458.mch"),
              _asset("SweepMach4Axis 20261008-090458.mch"),
              _asset("SweepTmpl 20261008-090458.f3dhsm-template", "template"),
              _asset("MeasureKeepsCopy.mch"),
              _asset("MeasureTmplRaise_" + "ab" * 16 + ".f3dhsm-template", "template")]
    assert _leaves(assets) == [leaf for _, _, leaf in assets]


def test_a_young_stamped_asset_of_another_run_is_kept_but_this_runs_own_goes():
    other = _asset("SweepMach3Axis 20261011-090000.mch")
    own = _asset("SweepMach3Axis 20261011-113000.mch")
    since = time.mktime(time.strptime("20261011-112900", "%Y%m%d-%H%M%S"))
    assert _leaves([other, own]) == []
    assert _leaves([other, own], own_since=since) == [own[2]]
