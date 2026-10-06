from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from random import Random
from typing import Literal

Kind = Literal["always", "sometimes"]


@dataclass(frozen=True, slots=True)
class Proof:
    statement: str
    kind: Kind
    seam: str
    fault_model: str
    axes: tuple[str, ...]
    sketch: str

    def __post_init__(self) -> None:
        if self.kind not in ("always", "sometimes"):
            raise ValueError(f"kind must be always or sometimes, got {self.kind!r}")
        for label, value in (
            ("statement", self.statement),
            ("seam", self.seam),
            ("fault_model", self.fault_model),
        ):
            if not value.strip():
                raise ValueError(f"proof {label} is empty")
        if not self.axes:
            raise ValueError("a proof names at least one axis")
        concluded = any(
            line.strip().startswith("Therefore") for line in self.sketch.splitlines()
        )
        if not concluded:
            raise ValueError("sketch needs a conclusion line starting with Therefore")
        missing = [axis for axis in self.axes if axis not in self.sketch]
        if missing:
            raise ValueError(f"sketch does not mention axes: {missing}")


@dataclass(frozen=True, slots=True)
class World:
    seed: int
    index: int
    axes: tuple[tuple[str, object], ...]

    def get(self, name: str) -> object:
        for key, value in self.axes:
            if key == name:
                return value
        raise KeyError(name)

    def __str__(self) -> str:
        shown = " ".join(f"{key}={value!r}" for key, value in self.axes)
        return f"seed={self.seed} index={self.index} {shown}"


def worlds(
    axes: Mapping[str, Sequence[object]],
    *,
    seed: int,
    limit: int = 256,
) -> tuple[World, ...]:
    if limit < 1:
        raise ValueError("limit must be positive")
    names = tuple(axes)
    if not names:
        raise ValueError("a multiverse needs at least one axis")
    columns = [tuple(axes[name]) for name in names]
    for name, column in zip(names, columns, strict=True):
        if not column:
            raise ValueError(f"axis {name!r} is empty")

    total = 1
    for column in columns:
        total *= len(column)
    if total <= limit:
        combos = list(product(*columns))
    else:
        chosen = sorted(Random(seed).sample(range(total), limit))
        combos = [_unrank(columns, index) for index in chosen]

    return tuple(
        World(seed, index, tuple(zip(names, combo, strict=True)))
        for index, combo in enumerate(combos)
    )


def check_always(
    proof: Proof,
    axes: Mapping[str, Sequence[object]],
    holds: Callable[[World], None],
    *,
    seed: int,
    limit: int = 256,
) -> None:
    universe = _universe(proof, axes, seed=seed, limit=limit, kind="always")
    for world in universe:
        try:
            holds(world)
        except Exception as exc:
            raise AssertionError(
                f"always-property failed: {proof.statement}\n"
                f"counterexample: {world}\n{exc}"
            ) from exc


def check_sometimes(
    proof: Proof,
    axes: Mapping[str, Sequence[object]],
    witness: Callable[[World], bool],
    *,
    seed: int,
    limit: int = 256,
) -> None:
    universe = _universe(proof, axes, seed=seed, limit=limit, kind="sometimes")
    if any(witness(world) for world in universe):
        return
    raise AssertionError(
        f"sometimes-property has no witness: {proof.statement}\n"
        f"seed={seed} worlds={len(universe)}"
    )


def _universe(
    proof: Proof,
    axes: Mapping[str, Sequence[object]],
    *,
    seed: int,
    limit: int,
    kind: Kind,
) -> tuple[World, ...]:
    if proof.kind != kind:
        raise AssertionError(f"proof kind is {proof.kind}, checker is {kind}")
    if tuple(axes) != proof.axes:
        raise AssertionError(
            f"proof axes {proof.axes} do not match multiverse axes {tuple(axes)}"
        )
    return worlds(axes, seed=seed, limit=limit)


def _unrank(columns: Sequence[Sequence[object]], index: int) -> tuple[object, ...]:
    chosen: list[object] = []
    for column in reversed(columns):
        size = len(column)
        chosen.append(column[index % size])
        index //= size
    return tuple(reversed(chosen))
