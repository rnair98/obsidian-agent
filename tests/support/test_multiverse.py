from __future__ import annotations

import pytest

from tests.support.multiverse import (
    Kind,
    Proof,
    World,
    check_always,
    check_sometimes,
    worlds,
)


def _proof(kind: Kind, axes: tuple[str, ...] = ("n",)) -> Proof:
    return Proof(
        statement="n stays non-negative",
        kind=kind,
        seam="checker",
        fault_model="the n axis only",
        axes=axes,
        sketch="1. n is the only axis.\nTherefore the checker can see it.",
    )


def test_same_seed_replays_the_same_sample() -> None:
    axes = {"n": tuple(range(30)), "m": tuple(range(30))}
    assert worlds(axes, seed=7, limit=10) == worlds(axes, seed=7, limit=10)
    assert worlds(axes, seed=7, limit=10) != worlds(axes, seed=8, limit=10)


def test_always_reports_the_counterexample_world() -> None:
    def holds(world: World) -> None:
        if world.get("n") == 2:
            raise AssertionError("hit 2")

    with pytest.raises(AssertionError, match=r"seed=4 .*n=2") as caught:
        check_always(_proof("always"), {"n": (1, 2, 3)}, holds, seed=4)
    assert "hit 2" in str(caught.value)


def test_sometimes_fails_closed_without_a_witness() -> None:
    with pytest.raises(AssertionError, match="no witness"):
        check_sometimes(
            _proof("sometimes"),
            {"n": (1, 2)},
            lambda _world: False,
            seed=4,
        )


def test_proof_axes_must_match_the_multiverse() -> None:
    with pytest.raises(AssertionError, match="do not match"):
        check_always(_proof("always"), {"other": (1,)}, lambda _world: None, seed=0)
