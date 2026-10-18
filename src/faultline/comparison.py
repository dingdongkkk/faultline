"""Comparator selection and count-aware alignment of observations.

Alignment never infers unambiguity from incomplete capture: if either side's
hit count is a lower bound, entries are labelled ``incomplete``.
"""

from __future__ import annotations

from fractions import Fraction

from .contracts import AlignedValue, Comparison, HitCount, Observation, ObservationRun, SnapshotValue, TestClass
from .execution import Baseline

MAX_ALIGNED = 40
_UNCOMPARABLE = {"opaque", "redacted", "depth_limit", "cycle", "unavailable"}


def _test_function(nodeid: str) -> str:
    return nodeid.split("[", 1)[0]


def select_comparators(baseline: Baseline, target: str, call_cov: dict[str, set[tuple[str, int]]],
                       focus: set[tuple[str, int]], k: int = 2,
                       suspects: set[tuple[str, int]] | None = None) -> list[tuple[str, str]]:
    """Eligible passing tests whose call phase covers ``focus`` or any suspect line, ranked by
    (1) number of top-tie-group lines covered (so probes on suspects have a passing counterpart),
    (2) exact Jaccard overlap with the target, (3) parametrize sibling, (4) nodeid."""
    suspects = suspects or set()
    tgt = call_cov.get(target, set())
    cands = []
    for n, rec in baseline.records.items():
        if rec.klass is not TestClass.PASSING:
            continue
        cov = call_cov.get(n, set())
        if not (cov & focus or cov & suspects):
            continue
        hits = len(cov & suspects)
        union = len(cov | tgt)
        jac = Fraction(len(cov & tgt), union) if union else Fraction(0)
        sibling = _test_function(n) == _test_function(target)
        cands.append((-hits, -jac, not sibling, n, hits, jac, sibling))
    cands.sort()
    return [(n, f"suspects_covered={hits};jaccard={float(jac):.3f};sibling={'yes' if sib else 'no'}")
            for *_, n, hits, jac, sib in cands[:k]]


def _comparable(v: SnapshotValue) -> bool:
    if v.kind in _UNCOMPARABLE or v.truncated:
        return False
    return all(_comparable(i) for i in (v.items or [])) and all(
        _comparable(a) and _comparable(b) for a, b in (v.entries or []))


def relation(a: SnapshotValue | None, b: SnapshotValue | None) -> str:
    if a is None or b is None:
        return "missing"
    if a.kind == b.kind == "unavailable" and a.reason == b.reason:
        return "equal"  # e.g. unbound on both sides
    if _comparable(a) and _comparable(b):
        return "equal" if a == b else "differs"
    if a.kind != b.kind:
        return "differs"
    if a.kind == "opaque" and a.type_name != b.type_name:
        return "differs"
    return "incomparable"


def _label(hf: HitCount, hp: HitCount) -> str:
    if not (hf.exact and hp.exact):
        return "incomplete"
    if hf.count == hp.count == 1:
        return "unambiguous"
    if hf.count == hp.count:
        return "ordinal"
    return "ambiguous"


def align(evidence_id: str, failing: ObservationRun, f_obs: list[Observation], passing: ObservationRun,
          p_obs: list[Observation], comparator_reason: str) -> Comparison:
    def group(obs):
        g: dict[tuple[str, str], dict[int, Observation]] = {}
        for o in obs:
            g.setdefault((o.probe_id, o.event.value), {})[o.timing.hit_ordinal] = o
        return g

    fg, pg = group(f_obs), group(p_obs)
    keys = sorted(set(fg) | set(pg))
    aligned: list[tuple[int, AlignedValue]] = []
    diffs: dict[str, tuple[HitCount, HitCount]] = {}
    for probe, event in keys:
        hk = f"{probe}:{event}"
        # Absent key = zero hits, exact only if that run's tracing completed.
        hf = failing.probe_hits.get(hk, HitCount(count=0, exact=failing.counts_exact))
        hp = passing.probe_hits.get(hk, HitCount(count=0, exact=passing.counts_exact))
        label = _label(hf, hp)
        if label != "unambiguous" and (hf.count != hp.count or not (hf.exact and hp.exact)):
            diffs[hk] = (hf, hp)
        fo, po = fg.get((probe, event), {}), pg.get((probe, event), {})
        for ordinal in sorted(set(fo) | set(po)):
            a, b = fo.get(ordinal), po.get(ordinal)
            names = sorted(set(a.values if a else {}) | set(b.values if b else {}))
            seq = a.timing.event_seq if a else 10**9 + (b.timing.event_seq if b else 0)
            for name in names:
                av = a.values.get(name) if a else None
                bv = b.values.get(name) if b else None
                aligned.append((seq, AlignedValue(probe_id=probe, event=event, hit_ordinal=ordinal, alignment=label,
                                                  name=name, failing=av, passing=bv, relation=relation(av, bv))))
            if not names and (a is None) != (b is None):
                aligned.append((seq, AlignedValue(probe_id=probe, event=event, hit_ordinal=ordinal, alignment=label,
                                                  name="<event>", relation="missing")))
    aligned.sort(key=lambda x: (x[0], x[1].name))
    def noise(a: AlignedValue) -> bool:  # incomparable with nothing to tell apart
        return (a.relation == "incomparable" and a.failing is not None and a.passing is not None
                and a.failing.kind == a.passing.kind and a.failing.type_name == a.passing.type_name)

    equal = sum(1 for _, a in aligned if a.relation == "equal")
    incomparable = sum(1 for _, a in aligned if noise(a))
    entries = [a for _, a in aligned if a.relation != "equal" and not noise(a)][:MAX_ALIGNED]
    first = next((i for i, a in enumerate(entries)
                  if a.relation == "differs" and a.alignment in ("unambiguous", "ordinal")), None)
    return Comparison(evidence_id=evidence_id, failing_run_id=failing.run_id, passing_run_id=passing.run_id,
                      comparator_reason=comparator_reason, aligned=entries, equal_count=equal,
                      incomparable_count=incomparable,
                      hit_count_differences=diffs,
                      first_divergence_index=first)
