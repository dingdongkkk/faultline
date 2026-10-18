"""Target-focused Ochiai ranking over call-phase coverage, with exact ties.

score = ef / sqrt(F * (ef + ep)); ordering uses the exact squared score
Fraction(ef^2, F*(ef+ep)), so ties are decided on integers, not floats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from .contracts import ExclusionReason, TestClass
from .execution import Baseline


def ochiai_squared(ef: int, ep: int, total_failing: int) -> Fraction | None:
    """Exact squared Ochiai score, or None where the score is undefined."""
    if ef < 0 or ep < 0 or total_failing < 0:
        raise ValueError("counts must be non-negative")
    if ef > total_failing:
        raise ValueError("ef cannot exceed total_failing")
    if total_failing == 0 or ef + ep == 0:
        return None
    return Fraction(ef * ef, total_failing * (ef + ep))


def display_score(sq: Fraction) -> float:
    return round(math.sqrt(sq.numerator / sq.denominator), 4)


@dataclass(frozen=True)
class LineStat:
    path: str
    line: int
    ef: int
    ep: int
    sq: Fraction


@dataclass(frozen=True)
class TieGroupStat:
    index: int  # 1-based dense rank
    members: tuple[LineStat, ...]


@dataclass
class Ranking:
    total_failing: int
    total_passing: int
    unrelated_failing: list[str]
    excluded: dict[ExclusionReason, int]
    groups: list[TieGroupStat]
    unattributed_line_count: int
    setup_teardown_only_line_count: int
    zero_ef_line_count: int

    @property
    def lines(self) -> list[LineStat]:
        return [m for g in self.groups for m in g.members]


def group_ties(stats: list[LineStat]) -> list[TieGroupStat]:
    ordered = sorted(stats, key=lambda s: (-s.sq, s.path, s.line))
    groups: list[TieGroupStat] = []
    for s in ordered:
        if groups and groups[-1].members[0].sq == s.sq:
            groups[-1] = TieGroupStat(groups[-1].index, groups[-1].members + (s,))
        else:
            groups.append(TieGroupStat(len(groups) + 1, (s,)))
    return groups


def rank(baseline: Baseline, target: str, is_app) -> Ranking:
    recs = baseline.records
    passing = {n for n, r in recs.items() if r.klass is TestClass.PASSING}
    failing = {n for n, r in recs.items() if r.klass is TestClass.TARGET_FAILING}
    if failing - {target}:
        raise AssertionError("target-focused policy violated: non-target failing test classified as failing")
    excluded: dict[ExclusionReason, int] = {}
    for r in recs.values():
        if r.exclusion is not None:
            excluded[r.exclusion] = excluded.get(r.exclusion, 0) + 1
    unrelated = sorted(n for n, r in recs.items() if r.exclusion is ExclusionReason.UNRELATED_FAILURE)
    F = len(failing)

    stats: list[LineStat] = []
    unattributed = st_only = zero_ef = 0
    for path, lines in baseline.coverage.items():
        if not is_app(path):
            continue
        for line, ctxs in lines.items():
            call_tests = {n for n, ph in ctxs if ph == "call"}
            if not call_tests:
                if any(ph in ("setup", "teardown") for _, ph in ctxs):
                    st_only += 1
                else:
                    unattributed += 1
                continue
            ef = len(call_tests & failing)
            ep = len(call_tests & passing)
            if ef == 0:
                zero_ef += 1
                continue
            sq = ochiai_squared(ef, ep, F)
            if sq is not None:
                stats.append(LineStat(path, line, ef, ep, sq))
    return Ranking(
        total_failing=F, total_passing=len(passing), unrelated_failing=unrelated, excluded=excluded,
        groups=group_ties(stats), unattributed_line_count=unattributed,
        setup_teardown_only_line_count=st_only, zero_ef_line_count=zero_ef,
    )


def call_coverage_by_test(baseline: Baseline, is_app) -> dict[str, set[tuple[str, int]]]:
    """nodeid -> set of (path, line) covered in its call phase (app files only)."""
    out: dict[str, set[tuple[str, int]]] = {}
    for path, lines in baseline.coverage.items():
        if not is_app(path):
            continue
        for line, ctxs in lines.items():
            for n, ph in ctxs:
                if ph == "call":
                    out.setdefault(n, set()).add((path, line))
    return out
