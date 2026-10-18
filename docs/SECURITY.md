## Source search addition (2026-10-18)

search_code parses bounded Python source without importing or executing it.
It skips symlinks and configured excluded paths. Static links and source text
are untrusted retrieval data, never measured runtime evidence. The current
implementation scans on every request; scan deadline is cooperative and
parsing an individual capped file is not interrupted. There is no persistent
search cache. Search does not launch a model or send code to a remote service;
the calling coding client receives excerpts and controls its own data handling.
The previous statement that prompt injection can “at worst waste a round”
is too strong: untrusted excerpts can influence the host agent. Engine action
validation limits Faultline actions, not the host agent's interpretation.

# Security model

Faultline runs the target repository's own test code. **Treat it like
running `pytest` yourself**: only use it on repositories you would execute.

## What isolation exists
- Test execution happens in child processes in a new session/process group,
  with wall-clock deadlines, output caps, and `SIGTERM`→`SIGKILL` + reap of
  the whole group on timeout or cancellation.
- **This is not a sandbox.** Child processes have the user's filesystem,
  network and credentials. macOS does not enforce `RLIMIT_AS`; memory is
  not hard-limited.
- Grandchildren that leave the process group (double-fork, `setsid`) can
  escape cleanup; spawning is detected where possible and reported.

## Untrusted inputs
- Repository content, test output and runtime values are untrusted data.
  They are never interpreted as instructions by the engine.
- The local model only selects from a closed action vocabulary that
  references engine-minted IDs; no paths, commands, Python or expressions.
  Every action is schema-validated and semantically validated before use.
  Prompt injection can at worst waste an observation round.
- Model rationale is stored separately (`rationale_untrusted`) and never
  merged with measured evidence.

## Snapshot safety
- Only exact built-in types are expanded; no `repr`/`str`/properties/custom
  iteration/deepcopy on application objects. Objects become opaque type
  names. Values are copied into primitives inside the trace callback.

## Secrets
- Redaction (name and value patterns) is applied in the worker before data
  is written, and again before any text is sent to the model. It is
  best-effort pattern matching and will miss secrets with unusual names or
  shapes.
- Environment variable *values* are never stored; declared variables are
  fingerprinted with an HMAC under a local random key.
- Evidence is stored outside the repository under the user's cache
  directory with 24 h retention.
- Everything stays local: the model runs via llama.cpp on localhost. No
  telemetry.

## Configuration
- `pytest_args` is validated: options that change execution semantics
  (`-n`, `--dist`, `--reruns`, `--cov*`, `-p` other than `no:*`, `--pdb`,
  `--trace`, `-x`, `--maxfail`, `--lf`, `--ff`, `--sw`, `--runxfail`) are
  rejected. `PYTEST_ADDOPTS`/`PYTEST_PLUGINS` are removed from child
  environments so they cannot reintroduce them.
- All paths are resolved with `realpath` and must stay inside the repo root;
  symlinks escaping it are rejected.
- The MCP server binds only stdio.

## Reporting
Until a public repository exists, report issues to the maintainer directly.
