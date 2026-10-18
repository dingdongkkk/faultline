"""Safe snapshot serialization and redaction.

The implementation lives in ``_probe/snapshot.py`` because it must run
inside the target interpreter (standard library only); this module
re-exports it for Faultline-side use (e.g. redacting model input).
"""

from ._probe.common import name_is_sensitive, redact_text, type_name
from ._probe.snapshot import Snapshotter

__all__ = ["Snapshotter", "name_is_sensitive", "redact_text", "type_name"]
