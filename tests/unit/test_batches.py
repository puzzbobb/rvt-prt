"""Unit tests for sheets drawn in groups by the models they show (render.batches)."""
import random
from types import SimpleNamespace

import numpy as np

from rvt_prt.render import batches


def _sheet(n):
    return SimpleNamespace(number=n)


def test_everything_fits_one_group():
    sheets = [_sheet(f"A{i}") for i in range(5)]
    shows = {s.number: frozenset({1, 2}) for s in sheets}
    assert batches.plan(sheets, shows, {1: 100, 2: 100}, 1000) == [(sheets, frozenset({1, 2}))]


def test_sheets_needing_models_already_loaded_stay_in_the_group_over_the_limit():
    # Snowdon: every plan shows the same six models, together over the budget: one group, not one a sheet
    sheets = [_sheet(f"M{i}") for i in range(8)]
    shows = {s.number: frozenset(range(1, 7)) for s in sheets}
    groups = batches.plan(sheets, shows, {k: 100 for k in range(1, 7)}, 250)
    assert len(groups) == 1 and len(groups[0][0]) == 8


def test_a_campus_is_drawn_within_the_budget_loading_each_model_a_few_times():
    rng = random.Random(1)
    need = {k: rng.randint(150, 400) * 10**6 for k in range(1, 51)}
    sheets = [_sheet(f"S{i:04}") for i in range(1000)]
    # each sheet a building or two and its neighbours: models of one area shown together
    shows = {}
    for s in sheets:
        a = rng.randint(1, 50)
        shows[s.number] = frozenset(k for k in (a, a + 1, a + rng.choice((2, 3))) if k <= 50 and rng.random() < 0.8) or frozenset({a})
    limit = 3 * 10**9
    groups = batches.plan(sheets, shows, need, limit)
    assert sorted(s.number for g, _m in groups for s in g) == sorted(s.number for s in sheets)
    for g, models in groups:
        assert all(shows[s.number] <= models for s in g)
        assert sum(need[k] for k in models) <= limit
    loads, held = 0, set()
    for _g, models in groups:  # as api._batched does: keep what the next group shows, load the rest
        loads += len(models - held)
        held = set(models)
    assert loads < 200  # a model loaded about four times, not once a sheet (some 2,400 loads)


def test_a_model_is_shown_by_a_plan_whose_crop_reaches_it():
    plan = SimpleNamespace(view_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), view_origin=(0.0, 0.0, 0.0),
                           crop=(-50.0, -50.0, 50.0, 50.0), view_range=(0.0, 4.0, 4.0, 0.0, 10.0), depth=None)
    near = (np.array([40.0, 0.0, 0.0]), np.array([80.0, 10.0, 30.0]))
    far = (np.array([500.0, 500.0, 0.0]), np.array([600.0, 600.0, 30.0]))
    assert batches.reaches(plan, near) and not batches.reaches(plan, far) and not batches.reaches(plan, None)
    drafting = SimpleNamespace(view_basis=None, view_origin=None, crop=None, view_range=None, depth=None)
    assert not batches.reaches(drafting, near)
    assert batches.sheet_models([SimpleNamespace(number="A1", viewports=[plan, drafting])], {1: near, 2: far}) == {"A1": frozenset({1})}
