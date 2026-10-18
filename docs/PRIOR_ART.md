# Prior art

Faultline claims **no novelty** for spectrum-based fault localization,
runtime value inspection, debugger-style MCP servers, or their combination.
Its open question is narrower and empirical: does letting a small local model
choose *which* bounded observations to make improve repair outcomes or reduce
main-agent work compared with fixed deterministic rules, with everything else
held constant?

Verification level: entries marked **[abstract]** were checked against the
arXiv abstract/landing page on 2026-10-18 (not the full text); entries marked
**[unverified]** have not been checked against a primary source.

## Spectrum-based fault localization
- Tarantula — Jones & Harrold, ASE 2005. [unverified]
- Ochiai coefficient applied to SBFL — Abreu, Zoeteweij & van Gemund, 2006/2007. [unverified]
- GZoltar (Java SBFL toolset). [unverified]
- **FauxPy** — Rezaalipour & Furia, "FauxPy: A Fault Localization Tool for
  Python", arXiv:2404.18596: a pytest plugin covering seven FL techniques in
  four families, evaluated on 135 BugsInPy bugs; companion empirical study
  arXiv:2305.19834. [abstract] This is the closest Python SBFL tooling to
  Faultline's ranking component.

## LLM agents that use localization
- **AutoFL** — Kang, An & Yoo, arXiv:2308.05487 (later titled "A Quantitative
  and Qualitative Evaluation of LLM-Based Explainable Fault Localization"):
  LLM function calls to navigate a repository from a single failing test,
  compared against Ochiai among others. [abstract]
- **AutoCodeRover** — Zhang, Ruan, Fan & Roychoudhury, arXiv:2404.05427
  (ISSTA 2024): AST-level code search plus *optional* method-level SBFL when
  tests exist, to focus retrieval. [abstract]
- **Agentless** — Xia, Deng, Dunn & Zhang, arXiv:2407.01489 (FSE 2025):
  fixed localize → repair → validate pipeline with hierarchical LLM and
  IR-based localization. [abstract]
- SWE-agent (agent-computer interface for repository work). [unverified]

## Runtime inspection / tracing
- Python `sys.settrace`/`sys.monitoring`, `pdb`, `debugpy`.
- PySnooper, Hunter and similar tracing libraries. [unverified]
- Delta debugging (Zeller) and cause-effect chains; passing vs failing trace
  comparison. [unverified]

## Debugger MCP servers (candidates for evaluation condition B)
A web search on 2026-10-18 found several debugpy/DAP-based MCP servers,
e.g. `kaina3/debug-mcp`, `KashunCheng/dap_mcp`, `debugmcpdev/mcp-debugger`.
Maintenance status, licenses and suitability were **not** verified; condition
B is not implemented.

## How Faultline differs (scope, not novelty)
- Bounded, non-interactive investigation returning a packed evidence bundle
  instead of exposing a stepping debugger session.
- No expression evaluation; exact-type safe snapshots instead.
- Explicit provenance and freshness on every evidence item.
- Deterministic and local-model planners share one engine and vocabulary,
  so their difference can be measured.
