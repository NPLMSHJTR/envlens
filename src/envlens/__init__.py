"""envlens — a static audit for environment-variable contracts.

The public surface is deliberately narrow: the CLI plus :func:`audit`, which
returns a structured :class:`~envlens.model.Report` for tools that want to embed
the analysis without parsing terminal output.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .model import Coverage, Finding, Reference, Report, Severity  # noqa: E402
from .rules import Options, audit  # noqa: E402

__all__ = [
    "Coverage",
    "Finding",
    "Options",
    "Reference",
    "Report",
    "Severity",
    "__version__",
    "audit",
]
