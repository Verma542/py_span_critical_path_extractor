"""Core logic for extracting the critical path from a span tree.

A span is a unit of work with a start time, an end time, and a parent. The
critical path is the longest chain of *ancestor-linked* spans whose intervals
together account for the latency of a trace.

Interpretation decision (see README): a parent span's duration is the wall
clock from its start to its end. Its children may run concurrently with each
other. The portion of a parent's latency that is *not* covered by any child is
the parent's own "self time". The critical path is the maximal total of
(self time + critical path of the child that maximises the chain) walking
down from the root. In other words, at each level we pick exactly one child
branch, and we never count overlapping sibling work twice.

All times are integers (microseconds, milliseconds, nanoseconds -- the unit is
irrelevant as long as it is consistent). Floats are accepted but discouraged;
see README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class SpanTreeError(ValueError):
    """Raised when the input spans do not form a valid tree.

    This is a distinct subclass of :class:`ValueError` so callers can catch
    malformed traces without swallowing unrelated argument errors.
    """


@dataclass
class Span:
    """A single span in a trace.

    Attributes:
        span_id: Unique identifier for this span. Must be unique across the
            whole trace.
        parent_id: Identifier of the parent span, or ``None`` for the root.
        start: Start time, in whatever integer unit the caller uses.
        end: End time. Must be ``>= start``.
        name: Optional human-readable label, used only for reporting.
    """

    span_id: str
    parent_id: Optional[str]
    start: int
    end: int
    name: str = ""

    @property
    def duration(self) -> int:
        """Wall-clock duration of the span."""
        return self.end - self.start


@dataclass
class _Node:
    """Internal tree node used during traversal.

    Kept separate from :class:`Span` so that the public dataclass stays a
    plain value object and the traversal can attach a mutable child list
    without surprising anyone who reuses a ``Span`` instance.
    """

    span: Span
    children: List["_Node"] = field(default_factory=list)


def _build_tree(spans: Sequence[Span]) -> _Node:
    """Build a tree from a flat sequence of spans and return its root.

    Raises:
        SpanTreeError: If there is no single root, if a parent id is missing,
            if span ids are duplicated, or if a span's end precedes its start.
    """
    if not spans:
        raise SpanTreeError("cannot build a span tree from an empty sequence")

    by_id: Dict[str, _Node] = {}
    for span in spans:
        if span.span_id in by_id:
            raise SpanTreeError(f"duplicate span id: {span.span_id!r}")
        if span.end < span.start:
            raise SpanTreeError(
                f"span {span.span_id!r} ends ({span.end}) before it starts "
                f"({span.start})"
            )
        by_id[span.span_id] = _Node(span=span)

    roots: List[_Node] = []
    for span in spans:
        node = by_id[span.span_id]
        if span.parent_id is None:
            roots.append(node)
            continue
        parent = by_id.get(span.parent_id)
        if parent is None:
            raise SpanTreeError(
                f"span {span.span_id!r} references unknown parent "
                f"{span.parent_id!r}"
            )
        parent.children.append(node)

    if len(roots) != 1:
        raise SpanTreeError(
            f"expected exactly one root span, found {len(roots)}"
        )

    _check_acyclic(roots[0], by_id)
    return roots[0]


def _check_acyclic(root: _Node, by_id: Dict[str, _Node]) -> None:
    """Detect parent cycles.

    A cycle can only be reached from the root if every node in it has a
    parent, so an unreachable cycle is impossible here: a node with no
    parent is a root and there is exactly one root. Still, a self-parenting
    span would show up as a child of itself before the root check, so we
    walk the tree iteratively and guard against revisits.
    """
    seen = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            raise SpanTreeError(
                f"span tree contains a cycle at {node.span.span_id!r}"
            )
        seen.add(id(node))
        stack.extend(node.children)


def _clipped_interval(child: Span, parent: Span) -> Optional[Tuple[int, int]]:
    """Return the child's interval clipped to the parent, or ``None``.

    A child that does not overlap its parent contributes no latency to the
    parent's wall clock, so it is dropped entirely.
    """
    start = max(child.start, parent.start)
    end = min(child.end, parent.end)
    if end > start:
        return (start, end)
    return None


def _self_time(node: _Node) -> int:
    """Return the part of a span's duration not covered by its children.

    Children are merged into a union of intervals so that overlapping
    siblings are counted once. This is the whole point of the library: two
    concurrent children that start and end at the same time represent one
    unit of latency, not two.
    """
    intervals: List[Tuple[int, int]] = []
    for child in node.children:
        clipped = _clipped_interval(child.span, node.span)
        if clipped is not None:
            intervals.append(clipped)
    if not intervals:
        return node.span.duration

    intervals.sort()
    covered = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start > cur_end:
            covered += cur_end - cur_start
            cur_start, cur_end = start, end
        elif end > cur_end:
            cur_end = end
    covered += cur_end - cur_start

    return max(0, node.span.duration - covered)


def _critical_path(node: _Node) -> Tuple[int, List[Span]]:
    """Return (total, path) for the subtree rooted at ``node``.

    The path starts at ``node`` and descends through the child whose own
    critical path is longest. Ties are broken by the order children were
    supplied, which keeps the result deterministic.
    """
    best_child_total = 0
    best_child_path: List[Span] = []
    for child in node.children:
        clipped = _clipped_interval(child.span, node.span)
        if clipped is None:
            continue
        total, path = _critical_path(child)
        total = min(total, clipped[1] - clipped[0])
        if total > best_child_total:
            best_child_total = total
            best_child_path = path

    total = _self_time(node) + best_child_total
    return total, [node.span] + best_child_path


def parse_spans(rows: Iterable[dict]) -> List[Span]:
    """Convert an iterable of mappings into :class:`Span` objects.

    Each mapping must contain ``span_id``, ``start`` and ``end``; ``parent_id``
    and ``name`` are optional. This is a convenience for callers that read
    traces from JSON. Extra keys are ignored so a richer trace format can be
    fed in without preprocessing.
    """
    result: List[Span] = []
    for row in rows:
        try:
            span_id = row["span_id"]
            start = row["start"]
            end = row["end"]
        except KeyError as exc:
            raise SpanTreeError(f"missing required field: {exc.args[0]!r}") from exc
        result.append(
            Span(
                span_id=str(span_id),
                parent_id=(
                    None if row.get("parent_id") is None else str(row["parent_id"])
                ),
                start=int(start),
                end=int(end),
                name=str(row.get("name", "")),
            )
        )
    return result


def critical_path(spans: Sequence[Span]) -> List[Span]:
    """Return the critical path as a list of spans from root to leaf.

    Raises:
        SpanTreeError: If ``spans`` is empty or does not form a single tree.
    """
    root = _build_tree(list(spans))
    _, path = _critical_path(root)
    return path


def critical_path_duration(spans: Sequence[Span]) -> int:
    """Return the total latency attributed to the critical path.

    This is the sum of self-times along the chosen chain, i.e. the latency
    that would remain if every span not on the path were removed.
    """
    root = _build_tree(list(spans))
    total, _ = _critical_path(root)
    return total
