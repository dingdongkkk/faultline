"""Shared typed contracts for Faultline.

Everything that crosses a module, process or MCP boundary is defined here.
Models are pydantic v2 so the same definitions give runtime validation (for
planner output, which is untrusted) and exported JSON Schemas (``schemas/``).
Code that runs inside the target interpreter (``_probe``) emits plain JSON
that is validated against these models on the Faultline side.

Conventions
- Paths are POSIX, relative to the configured repository root.
- IDs are opaque strings minted by the engine. Planners and clients may only
  reference IDs the engine has issued for the current investigation.
- ``score`` fields are display values. Ordering and ties are decided from the
  integer counts (exact fractions), never from floats.
- Nullable fields default to ``None`` so compact ``exclude_none``
  serialization round-trips (enforced by a test).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "0.2"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchHit(_Model):
    id: str  # content/version/window ID; use in seen_ids to avoid repeat context
    path: str
    symbol: str
    start: int
    end: int
    reason: list[str]
    code: str
    truncated: bool


class SearchResponse(_Model):
    search_version: str = "1"
    status: Literal["ok", "no_matches", "no_new_context", "budget_too_small"]
    hits: list[SearchHit]
    scanned_files: int
    matched_regions: int
    suppressed: int
    omitted: int
    limitations: list[str]
    budget_tokens: int
    budget_scope: Literal["json_payload", "mcp_result"]
    response_bytes: int = 0
    tokens_estimate: int = 0
    token_method: Literal["utf8_bytes_div_3"] = "utf8_bytes_div_3"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class InvestigationStatus(StrEnum):
    COMPLETED = "completed"  # bounded investigation finished; NOT "root cause proven"
    INCONCLUSIVE = "inconclusive"
    FAILURE_NOT_REPRODUCED = "failure_not_reproduced"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    UNSUPPORTED = "unsupported"
    TIMED_OUT = "timed_out"  # the deadline ended the investigation (partial evidence kept)
    EXECUTION_ERROR = "execution_error"


class StoppingReason(StrEnum):
    PLANNER_STOPPED = "planner_stopped"
    MAX_ROUNDS = "max_rounds"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    NO_NEW_ACTIONS = "no_new_actions"
    BASELINE_NOT_FAILING = "baseline_not_failing"
    NO_RANKABLE_LINES = "no_rankable_lines"
    UNSUPPORTED_EXECUTION = "unsupported_execution"
    COLLECTION_ERROR = "collection_error"
    WORKSPACE_CHANGED = "workspace_changed"
    WORKER_FAILURE = "worker_failure"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class Phase(StrEnum):
    SETUP = "setup"
    CALL = "call"
    TEARDOWN = "teardown"


class PhaseOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


class XfailClass(StrEnum):
    """Explicit xfail classification; ``wasxfail`` alone is insufficient.

    pytest reports a strict XPASS as a plain *failed* call without
    ``wasxfail``, and an xfail whose ``raises=`` does not match as a plain
    failure, so both are classified from the evaluated xfail mark.
    """

    NONE = "none"  # no active xfail
    XFAIL = "xfail"  # expected failure happened (reported skipped + wasxfail)
    XPASS = "xpass"  # non-strict unexpected pass (reported passed + wasxfail)
    XPASS_STRICT = "xpass_strict"  # strict unexpected pass (reported failed, no wasxfail)
    XFAIL_RAISES_MISMATCH = "xfail_raises_mismatch"  # active xfail, other exception type
    XFAIL_MARKED_UNKNOWN = "xfail_marked_unknown"  # mark present, state not determinable


class TestClass(StrEnum):
    """Binary-ranking class of a test after applying eligibility policy."""

    __test__ = False  # not a pytest test class

    PASSING = "passing"
    TARGET_FAILING = "target_failing"
    EXCLUDED = "excluded"


class ExclusionReason(StrEnum):
    SKIPPED = "skipped"
    XFAIL = "xfail"
    XPASS = "xpass"
    XPASS_STRICT = "xpass_strict"
    XFAIL_RAISES_MISMATCH = "xfail_raises_mismatch"
    XFAIL_MARKED_UNKNOWN = "xfail_marked_unknown"
    SETUP_FAILED = "setup_failed"
    TEARDOWN_FAILED = "teardown_failed"
    INCOMPLETE_PHASES = "incomplete_phases"
    DUPLICATE_REPORT = "duplicate_report"
    TRACE_CONFLICT = "trace_conflict"  # test replaced the coverage tracer
    UNRELATED_FAILURE = "unrelated_failure"  # failing, but not the target (F=1 policy)


class Freshness(StrEnum):
    FRESH = "fresh"  # all fingerprint components and referenced sources match
    STALE = "stale"  # some referenced source or environment component changed
    UNKNOWN = "unknown"  # fingerprint partial (caps, editable deps outside repo, ...)
    EXPIRED = "expired"  # retention elapsed; only the tombstone remains


class Reproduction(StrEnum):
    REPRODUCED = "reproduced"  # full failure signature matches the baseline
    PARTIAL_MATCH = "partial_match"  # type + crash location match, message differs
    DIFFERENT_FAILURE = "different_failure"
    NOT_REPRODUCED = "not_reproduced"  # call phase passed
    NOT_APPLICABLE = "not_applicable"  # comparator runs
    UNKNOWN = "unknown"  # worker crashed / timed out before the call phase ended


class ObservationEvent(StrEnum):
    BEFORE_LINE = "before_line"  # locals as they are *before* the line executes
    CALL = "call"  # arguments at function entry
    RETURN = "return"  # normal return; value recorded as "<return>"
    EXCEPTION = "exception"  # an exception was raised in / passed through the frame
    UNWIND = "unwind"  # frame exited because an exception propagated out of it
    EXIT_AMBIGUOUS = "exit_ambiguous"  # generator/coroutine suspend or undeterminable exit


class PlannerKind(StrEnum):
    DETERMINISTIC = "deterministic"
    LOCAL_MODEL = "local-model"


class PatchMode(StrEnum):
    AFFECTED = "affected"
    FULL = "full"


class EffectiveScope(StrEnum):
    AFFECTED = "affected"
    FULL = "full"
    AFFECTED_ESCALATED_TO_FULL = "affected_escalated_to_full"


# --------------------------------------------------------------------------
# Limits and configuration
# --------------------------------------------------------------------------


class ExecutionLimits(_Model):
    """Defaults; tool arguments may lower but never raise the caps."""

    timeout_seconds_default: int = 120
    timeout_seconds_cap: int = 600
    max_rounds_cap: int = 5
    budget_tokens_min: int = 800  # empirical: skeleton + omissions + compaction labels (M5)
    budget_tokens_cap: int = 8000
    expand_budget_tokens_min: int = 200
    # Observation worker
    max_probes_per_action: int = 5
    max_locals_per_probe: int = 8
    max_tests_per_action: int = 2
    max_hits_per_probe: int = 20  # snapshots kept per probe; counting continues
    max_events_per_run: int = 400  # snapshots kept per run; counting continues
    callback_cpu_budget_ms: int = 2000  # cumulative time inside the tracer
    value_max_depth: int = 3
    value_max_items: int = 16
    value_max_str_chars: int = 160
    value_max_bytes_preview: int = 32
    value_max_int_digits: int = 40
    snapshot_max_bytes: int = 4096
    run_output_max_bytes: int = 512 * 1024
    baseline_output_max_bytes: int = 64 * 1024 * 1024
    diagnostic_output_max_bytes: int = 16 * 1024  # stdout/stderr tail kept
    # Storage
    investigation_store_max_bytes: int = 8 * 1024 * 1024
    evidence_retention_hours: int = 24
    # Source
    excerpt_max_lines: int = 60
    excerpt_context_lines: int = 3
    # Fingerprint
    fingerprint_max_files: int = 20000
    fingerprint_max_total_bytes: int = 512 * 1024 * 1024
    # Planner
    planner_max_retries: int = 2
    planner_max_output_tokens: int = 256
    planner_context_tokens: int = 4096
    # Process cleanup
    terminate_grace_seconds: float = 2.0


class FaultlineConfig(_Model):
    repo_root: str  # absolute, resolved at startup
    python: str  # target test interpreter (absolute)
    pytest_args: list[str] = Field(default_factory=list)  # validated; see SECURITY.md
    test_globs: list[str] = Field(
        default_factory=lambda: ["tests/**", "test/**", "**/test_*.py", "**/*_test.py", "**/conftest.py"]
    )
    exclude_globs: list[str] = Field(
        default_factory=lambda: [
            ".git/**", ".venv/**", "venv/**", "**/__pycache__/**", "**/site-packages/**",
            ".pytest_cache/**", "**/*.pyc", ".faultline/**",
        ]
    )
    declared_env: list[str] = Field(default_factory=list)  # names only; values HMAC'd
    extra_inputs: list[str] = Field(default_factory=list)  # data paths outside the walk
    state_dir: str | None = None  # default: platform cache dir, outside the repo
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    model_endpoint: str | None = None  # e.g. http://127.0.0.1:8080 (llama-server)


# --------------------------------------------------------------------------
# Identity and freshness
# --------------------------------------------------------------------------


class SourceIdentity(_Model):
    path: str
    sha256: str
    size: int


class WorkspaceFingerprint(_Model):
    fingerprint_id: str  # sha256 over all components below
    files_digest: str  # over sorted (path, sha256) for every in-scope file (full content hash)
    file_count: int
    config_digest: str  # pyproject/setup.cfg/pytest.ini/tox.ini/conftest.py contents
    interpreter_digest: str  # executable + sys.version + sys.prefix of the target python
    dependencies_digest: str  # installed distributions (name, version, editable location)
    declared_env_digest: str  # HMAC(local key, name=value); values never stored
    editable_outside_repo: list[str] = Field(default_factory=list)  # dists whose source is not hashed
    partial: bool = False  # -> every freshness answer is UNKNOWN; patch checks run full
    partial_reasons: list[str] = Field(default_factory=list)
    captured_at: str  # ISO-8601 UTC


# --------------------------------------------------------------------------
# Failure signatures, coverage, outcomes, ranking
# --------------------------------------------------------------------------


class FailureSignature(_Model):
    """What must match for an observation run to count as reproducing."""

    exception_type: str | None = None  # "module.QualName" of the raised type
    crash_path: str | None = None  # innermost traceback location (repo-relative if inside)
    crash_line: int | None = None
    test_line: int | None = None  # line in the test function where the failure surfaced
    message_digest: str | None = None  # sha256 of the redacted, address-normalized message
    message_excerpt: str | None = None  # redacted, truncated


class TestRecord(_Model):
    __test__ = False

    nodeid: str  # preserved verbatim, including parametrization
    setup: PhaseOutcome
    call: PhaseOutcome
    teardown: PhaseOutcome
    xfail: XfailClass = XfailClass.NONE
    klass: TestClass
    exclusion: ExclusionReason | None = None
    signature: FailureSignature | None = None  # for call-phase failures


class RankedLocation(_Model):
    location_id: str  # e.g. "L7"
    path: str
    line: int
    function_id: str | None = None  # AST function containing the line, if any
    ef: int  # 0/1 under the target-focused policy
    ep: int  # distinct eligible passing tests covering the line (call phase)
    total_failing: int | None = None  # F; omitted in responses (RankingSummary.total_failing)
    score: float  # display only; rounded
    tie_group: str  # e.g. "T1"; members share an exactly equal score


class TieGroup(_Model):
    tie_group: str
    rank: int  # dense rank, 1 = highest
    size: int
    shown: int  # members included in this response
    member_location_ids: list[str]  # only the shown ones
    distinct_count_pairs: list[tuple[int, int]]  # (ef, ep) pairs tied at this score


class RankingSummary(_Model):
    policy: Literal["target_focused_f1"] = "target_focused_f1"
    total_failing: int  # F used in the formula
    total_passing: int  # eligible passing tests
    unrelated_failing: int  # failing tests excluded by the F=1 policy
    unrelated_failing_sample: list[str] = Field(default_factory=list)
    excluded: dict[ExclusionReason, int]
    ranked_line_count: int  # application lines with ef > 0
    unattributed_line_count: int  # import-time / no-context lines, not ranked
    setup_teardown_only_line_count: int
    tie_groups: list[TieGroup]
    locations: list[RankedLocation]


# --------------------------------------------------------------------------
# Source
# --------------------------------------------------------------------------


class LineRange(_Model):
    start: int
    end: int  # inclusive


class SourceExcerpt(_Model):
    excerpt_id: str  # also an evidence id
    source: SourceIdentity
    function_id: str | None = None
    qualname: str | None = None
    region: LineRange  # full AST region of the function (or the excerpt window)
    shown: list[LineRange]  # merged, deduplicated shown ranges
    omitted: list[LineRange]
    text: str  # "NNNN| code" lines for the shown ranges only
    truncated: bool


# --------------------------------------------------------------------------
# Snapshots and observations
# --------------------------------------------------------------------------


class SnapshotValue(_Model):
    """Bounded, primitive-only copy of a runtime value.

    Only exact built-in types are expanded. Subclasses of built-ins and every
    other object are ``opaque``: type name only, read through type
    descriptors, never through repr/str/properties/iteration of user types.
    """

    kind: Literal[
        "none", "bool", "int", "float", "str", "bytes",
        "list", "tuple", "dict", "set", "frozenset",
        "opaque", "redacted", "cycle", "depth_limit", "unavailable",
    ]
    value: Union[bool, int, float, str, None] = None  # non-finite floats as "nan"/"inf"/"-inf"
    type_name: str | None = None  # opaque objects: "module.QualName"
    length: int | None = None  # true length for str/bytes/containers
    items: list[SnapshotValue] | None = None
    entries: list[tuple[SnapshotValue, SnapshotValue]] | None = None
    truncated: bool | None = None  # present (true) only when truncated; omitted otherwise
    reason: str | None = None  # redacted: "name_pattern"|"value_pattern"; unavailable: "unbound"


class ObservationTiming(_Model):
    event_seq: int  # global order of captured events within the run
    hit_ordinal: int  # 1-based count of this event at this probe within the run
    t_ns: int  # monotonic ns since the call phase started


class Observation(_Model):
    evidence_id: str
    run_id: str
    probe_id: str  # location_id or function_id the planner asked for
    path: str
    line: int
    event: ObservationEvent
    timing: ObservationTiming
    frame_qualname: str
    call_depth: int  # frames below the test function (-1 if not found)
    values: dict[str, SnapshotValue]  # requested locals; "<return>" for RETURN
    exception_type: str | None = None  # EXCEPTION / UNWIND


class HitCount(_Model):
    """Hit count for one probe/event. ``exact`` is False when tracing stopped
    early (callback budget, timeout, conflict, crash): ``count`` is then only
    a lower bound and may not be used for unambiguous alignment."""

    count: int
    exact: bool


class ObservationRun(_Model):
    run_id: str
    test_nodeid: str
    role: Literal["target", "comparator", "reproduction_check"]
    reproduction: Reproduction
    signature: FailureSignature | None = None
    call_outcome: PhaseOutcome
    probe_hits: dict[str, HitCount]  # key "<probe_id>:<event>"; absent key = 0 with run exactness
    counts_exact: bool  # False if tracing ended before the call phase ended
    trace_stopped: str | None = None  # "callback_budget" | "trace_conflict" | "timeout" | "worker_crash"
    events_captured: int
    events_dropped: int  # hits counted but not snapshotted (caps)
    truncation: list[str]
    unsupported_detected: list[str]  # "threads_started", "subprocess_spawned", ...
    duration_ms: int
    fingerprint_id: str
    sources: list[SourceIdentity]


class AlignedValue(_Model):
    probe_id: str
    event: ObservationEvent
    hit_ordinal: int
    alignment: Literal["unambiguous", "ordinal", "ambiguous", "incomplete"]
    name: str
    failing: SnapshotValue | None = None
    passing: SnapshotValue | None = None
    relation: Literal["equal", "differs", "incomparable", "missing"]


class Comparison(_Model):
    evidence_id: str
    failing_run_id: str
    passing_run_id: str
    comparator_reason: str  # documented heuristic + counts, e.g. "covers_F2;jaccard=0.82"
    # Non-equal entries only (differs / incomparable / missing), in failing-run order. When a
    # response trims a comparison to fit, entries are priority-ordered instead (first divergence,
    # differences, failing-only values) and the remainder is a "comparison_values" omission.
    aligned: list[AlignedValue]
    equal_count: int = 0  # aligned values that compared equal (omitted; expand the observations)
    incomparable_count: int = 0  # both sides opaque/redacted/unavailable alike (omitted)
    hit_count_differences: dict[str, tuple[HitCount, HitCount]]  # key -> (failing, passing)
    # Index into ``aligned`` (failing-run event order); not a copy.
    # Only "unambiguous"/"ordinal" alignments are eligible.
    # Label: first observed divergence, not evidence of causation.
    first_divergence_index: int | None = None


# --------------------------------------------------------------------------
# Planner actions (closed vocabulary; validated by the engine)
# --------------------------------------------------------------------------

_Id = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
_Local = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
_Rationale = Annotated[str, Field(max_length=300)]


class InspectLocations(_Model):
    action: Literal["inspect_locations"]
    location_ids: list[_Id] = Field(min_length=1, max_length=5)
    locals: list[_Local] = Field(default_factory=list, max_length=8)
    test_ids: list[_Id] = Field(min_length=1, max_length=2)
    rationale: _Rationale = ""


class InspectFunction(_Model):
    action: Literal["inspect_function"]
    function_id: _Id
    test_ids: list[_Id] = Field(min_length=1, max_length=2)
    rationale: _Rationale = ""


class CompareObservations(_Model):
    action: Literal["compare_observations"]
    failing_run_id: _Id
    passing_run_id: _Id
    rationale: _Rationale = ""


class Stop(_Model):
    action: Literal["stop"]
    reason: Literal["sufficient_evidence", "no_useful_action", "evidence_contradictory"]
    rationale: _Rationale = ""


PlannerAction = Annotated[
    Union[InspectLocations, InspectFunction, CompareObservations, Stop],
    Field(discriminator="action"),
]


class PlannerActionEnvelope(_Model):
    """What a planner must return. Used as the model's JSON schema."""

    next: PlannerAction


class PlannerRound(_Model):
    round: int
    planner: PlannerKind
    attempts: int  # 1 + retries
    rejected: list[str]  # validation error codes per rejected attempt
    fallback_used: bool  # deterministic planner chose the executed action
    fallback_reason: str | None = None
    action: PlannerAction | None = None
    rationale_untrusted: str | None = None  # model text; never mixed with evidence
    inference_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


# --------------------------------------------------------------------------
# Tool responses
# --------------------------------------------------------------------------


class Limitation(_Model):
    code: str  # stable machine code, e.g. "threads_detected"
    detail: str


class Omission(_Model):
    kind: str  # "tie_group_members" | "excerpt" | "observation" | ...
    count: int
    evidence_ids: list[str]  # handles for expand_evidence


class ReproducedFailure(_Model):
    test_nodeid: str
    baseline_run_id: str
    signature: FailureSignature
    isolated: Reproduction  # target rerun alone, no probes


class ResponseMetrics(_Model):
    response_bytes: int
    response_tokens_estimate: int
    token_estimate_method: Literal["utf8_bytes_div_3"] = "utf8_bytes_div_3"
    budget_tokens: int
    wall_ms: int
    coverage_run_ms: int | None = None
    observation_ms: int | None = None
    planner_ms: int | None = None
    rounds: int
    planner_retries: int
    planner_fallbacks: int
    compacted: list[str] | None = None  # lossy last-resort shrinking applied to fit the budget
    planner_model: str | None = None  # "<gguf file>@<server build>" when a local model was used


class InvestigateResponse(_Model):
    contract_version: str = CONTRACT_VERSION
    investigation_id: str
    status: InvestigationStatus
    stopping_reason: StoppingReason
    planner_requested: PlannerKind
    fingerprint_id: str
    reproduced: ReproducedFailure | None = None
    ranking: RankingSummary | None = None
    excerpts: list[SourceExcerpt]
    observation_runs: list[ObservationRun]
    observations: list[Observation]
    comparisons: list[Comparison]
    unresolved: list[str]
    planner_rounds: list[PlannerRound]
    limitations: list[Limitation]
    omissions: list[Omission]
    metrics: ResponseMetrics


class ExpandResponse(_Model):
    contract_version: str = CONTRACT_VERSION
    investigation_id: str
    evidence_id: str
    kind: str | None = None
    freshness: Freshness
    stale_paths: list[str]
    stale_components: list[str]  # "interpreter" | "dependencies" | "config" | "declared_env" | ...
    irrecoverably_truncated: bool  # bounded at capture time; more cannot be retrieved
    content: dict | None = None  # whole item, or {"chunk","offset","total_bytes"}; None when expired
    next_cursor: str | None = None
    metrics: ResponseMetrics


class SelectedTest(_Model):
    nodeid: str
    reasons: list[str]  # "previously_non_passing" | "covers_changed:<path>" | "full_suite"


class TestRunOutcome(_Model):
    __test__ = False

    nodeid: str
    outcome: Literal["passed", "failed", "error", "skipped", "xfailed", "xpassed"]


class CheckPatchResponse(_Model):
    contract_version: str = CONTRACT_VERSION
    investigation_id: str
    mode_requested: PatchMode
    effective_scope: EffectiveScope
    escalation_reasons: list[str]
    changed_paths: list[str]
    selected: list[SelectedTest]
    selected_count: int
    outcome_counts: dict[str, int]
    non_passing: list[TestRunOutcome]
    previously_failing_now: dict[str, str]  # nodeid -> outcome
    duration_ms: int
    status: Literal["passed", "failed", "timed_out", "execution_error"]
    full_regression_verified: bool  # only a passing run of the full configured suite
    limitations: list[Limitation]
    omissions: list[Omission]
    metrics: ResponseMetrics


class ValueChange(_Model):
    seq: int
    frame: int
    path: str
    function: str
    after_line: int | None = None
    observed_line: int
    variable: str
    before: SnapshotValue
    after: SnapshotValue


class CapturedFrame(_Model):
    path: str
    line: int
    function: str
    values: dict[str, SnapshotValue]


class CapturedPhase(_Model):
    nodeid: str
    phase: Literal['setup', 'call', 'teardown']
    outcome: Literal['passed', 'failed', 'skipped']
    xfail: str
    frames: list[CapturedFrame]
    signature: FailureSignature | None = None
    report: str | None = None


class CapturePayload(_Model):
    reports: list[CapturedPhase]
    exitstatus: int
    history: list[ValueChange]
    limitations: list[str]


class CaptureResponse(_Model):
    capture_id: str
    status: Literal['failed', 'passed', 'incomplete', 'timed_out', 'workspace_changed']
    reused: bool
    failing_test: str
    fingerprint_id: str
    signature: FailureSignature | None = None
    frames: list[CapturedFrame] = Field(default_factory=list)
    changes: list[ValueChange] = Field(default_factory=list)
    omitted_changes: int = 0
    selection: Literal['focused_variable', 'none_origin_candidates', 'recent_failing_frames'] = 'recent_failing_frames'
    limitations: list[str]
    artifact_dir: str
    response_bytes: int = 0
    tokens_estimate: int = 0
    budget_scope: Literal['json_payload', 'mcp_result'] = 'json_payload'
    token_method: Literal['utf8_bytes_div_3'] = 'utf8_bytes_div_3'


class CapturePage(_Model):
    capture_id: str
    section: str
    variable: str | None = None
    freshness: Literal['unchanged', 'stale', 'unknown']
    text: str
    next_cursor: int | None = None
    total_chars: int
    response_bytes: int = 0
    tokens_estimate: int = 0
    budget_scope: Literal['json_payload', 'mcp_result'] = 'json_payload'
    token_method: Literal['utf8_bytes_div_3'] = 'utf8_bytes_div_3'
