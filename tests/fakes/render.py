# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""The Render world: a scene's ground offset."""

from tests.fakes.scaffold import fusion_fake


@fusion_fake(scenario_double="the groundOffset member of a render scene's settings alone: that "
                             "type has no SHAPES dump to sweep, and every other attribute on one "
                             "is what the tool under test assigned")
class GroundOffsetScene:
    """Scene settings whose groundOffset assignment adds to the offset held, plus injected faults."""

    def __init__(self, held_cm=0.0, injected_read=None, injected_setter_adds_nothing=False,
                 injected_shift_on=None):
        self.__dict__.update(held=held_cm, sent=[], _injected_read=injected_read,
                             _injected_setter_adds_nothing=injected_setter_adds_nothing,
                             _injected_shift_on=injected_shift_on)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        # INJECTED: a write of the attribute injected_shift_on names moves the offset by 0.1 cm.
        if name == self._injected_shift_on:
            self.held += 0.1

    @property
    def groundOffset(self):
        # INJECTED: injected_read is raised when it is an exception and answered when a number.
        if isinstance(self._injected_read, Exception):
            raise self._injected_read
        if self._injected_read is not None:
            return self._injected_read
        # MEASURED: a zero reached by adding reads as a negative zero.
        return -0.0 if self.sent and self.held == 0 else self.held

    @groundOffset.setter
    def groundOffset(self, amount):
        self.sent.append(amount)
        # MEASURED: an assignment adds to the offset held. INJECTED: the setter adds nothing.
        if not self._injected_setter_adds_nothing:
            self.held += amount
