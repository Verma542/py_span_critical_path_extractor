"""Span Critical Path Extractor.

Public API re-exports. See :mod:`py_span_critical_path_extractor.core` for the
implementation and the README for the interpretation of "critical path".
"""

from .core import (
    Span,
    SpanTreeError,
    critical_path,
    critical_path_duration,
    parse_spans,
)

__all__ = [
    "Span",
    "SpanTreeError",
    "critical_path",
    "critical_path_duration",
    "parse_spans",
]
