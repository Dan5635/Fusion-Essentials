"""Unit tests for ``param_set_favorite.py`` - the flag is published as the parameter reads it back."""

import pytest

from conftest import (FakeUserParameter, FakeUserParameters, MakeDesign, load_tool, make_timeline,
                      payload as _payload)

params = load_tool("param_set_favorite")


def _design(user_params, timeline, all_params=()):
    """A design carrying the two collections the param write path walks."""
    return MakeDesign(user_parameters=user_params, timeline=timeline,
                      all_parameters=list(all_params))


def _stub_design(monkeypatch, design):
    monkeypatch.setattr(params._common, "design", lambda: design)


@pytest.fixture
def favorite_design(monkeypatch):
    def setup(parameter):
        _stub_design(monkeypatch, _design(FakeUserParameters([parameter]), make_timeline()))
    return setup


class TestFavoriteHandler:
    @pytest.mark.parametrize("favorite", [True, False])
    def test_sets_favorite_flag(self, monkeypatch, favorite):
        p = FakeUserParameter(name="PartX", expression="10 mm")
        design = _design(FakeUserParameters([p]), make_timeline())
        _stub_design(monkeypatch, design)
        out = _payload(params.handler(name="PartX", favorite=favorite))
        assert out["favorite"] is favorite
        assert p.isFavorite is favorite

    def test_unknown_param_errors(self, monkeypatch):
        design = _design(FakeUserParameters([]), make_timeline())
        _stub_design(monkeypatch, design)
        res = params.handler(name="Ghost")
        assert res["isError"] is True and "No USER parameter" in res["message"]

    def test_favorite_set_failure_surfaces(self, monkeypatch):
        p = FakeUserParameter(name="PartX", expression="10 mm", favorite_write_raises=True)
        design = _design(FakeUserParameters([p]), make_timeline())
        _stub_design(monkeypatch, design)
        res = params.handler(name="PartX", favorite=True)
        assert res["isError"] is True and "Could not set favorite" in res["content"][0]["text"]

    def test_empty_name_errors(self, monkeypatch):
        design = _design(FakeUserParameters([]), make_timeline())
        _stub_design(monkeypatch, design)
        res = params.handler(name="")
        assert res["isError"] is True
        assert "Provide 'name'" in res["message"]

    def test_a_stuck_favorite_is_refused(self, favorite_design):
        p = FakeUserParameter(name="PartX", expression="10 mm", favorite_write_ok=False)
        favorite_design(p)
        res = params.handler(name="PartX", favorite=True)
        assert res["isError"] is True
        assert "Favorite on 'PartX' reads False after requesting True" in res["content"][0]["text"]
        assert "param_get(name='PartX')" in res["content"][0]["text"]

    def test_an_unreadable_favorite_is_refused(self, favorite_design):
        p = FakeUserParameter(name="PartX", expression="10 mm", favorite_read_ok=False)
        favorite_design(p)
        res = params.handler(name="PartX", favorite=False)
        assert res["isError"] is True
        assert "Favorite on 'PartX' could not be read after requesting False" in res["content"][0]["text"]
        assert "param_get(name='PartX')" in res["content"][0]["text"]
