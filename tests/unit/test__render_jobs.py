# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Bound process-local render jobs without losing a running future."""

from conftest import load_tool

jobs = load_tool("_render_jobs")


def test_full_registry_evicts_a_terminal_job_but_keeps_running_jobs(monkeypatch):
    monkeypatch.setattr(jobs, "_JOBS", {})
    monkeypatch.setattr(jobs, "_NEXT", 0)
    monkeypatch.setattr(jobs, "_LIMIT", 2)
    first = jobs.add(object(), "a.png", "first")
    second = jobs.add(object(), "b.png", "second")
    assert first != second and jobs.capacity() is False
    assert jobs.add(object(), "c.png", "third") is None
    jobs.set_terminal(first)
    assert jobs.capacity() is True and jobs.get(first) is not None
    third = jobs.add(object(), "c.png", "third")
    assert third not in (first, second)
    assert jobs.get(first) is None and jobs.get(second) is not None
    assert jobs.get(third)["path"] == "c.png"


def test_unknown_id_is_not_the_current_process_job(monkeypatch):
    monkeypatch.setattr(jobs, "_JOBS", {})
    monkeypatch.setattr(jobs, "_NEXT", 0)
    current = jobs.add(object(), "current.png", "doc")
    assert jobs.get("render:old-process:1") is None
    assert jobs.get(current)["document"] == "doc"
