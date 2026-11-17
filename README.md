# py_span_critical_path_extractor

Given a completed trace as a flat list of spans, this library returns the
longest sequential chain of work that accounts for the trace's latency,
ignoring work that ran concurrently.

```python
from py_span_critical_path_extractor import Span, critical_path, critical_path_duration

spans = [
    Span(span_id="root", parent_id=None, start=0, end=100),
    Span(span_id="db",   parent_id="root", start=0, end=40),
    Span(span_id="http", parent_id="root", start=40, end=100),
    Span(span_id="retry", parent_id="http", start=60, end=90),
]

print([s.span_id for s in critical_path(spans)])
# ['root', 'http', 'retry']
print(critical_path_duration(spans))
# 100
```

## Why this exists

A trace tree is not a sum: siblings frequently overlap, so adding up every
span's duration double-counts wall-clock latency. What you usually want is the
single chain of spans whose non-overlapping portions explain the trace's
duration, so you can point at one branch and say "this is what made the request
slow".

The trade-off is that this library only counts *ancestor-linked* work. A child
span that does not overlap its parent is clipped to the parent's interval, and
sibling spans that overlap are merged into a union before being subtracted from
the parent's duration. That is a deliberate simplification: it produces one
answer for one trace, but it will not tell you about work that escaped its
parent's interval (a clock-skew artefact) or about latency contributed by
siblings that happen to run in parallel.

## The awkward edge

Spans in real traces sometimes extend past their parent, usually because of
clock skew between hosts. This library clips children to the parent interval
rather than trusting the raw timestamps, so a child that starts before its
parent or ends after it contributes only its overlap. If you need the raw
numbers, read them from the `Span` objects directly.

## API

- `Span(span_id, parent_id, start, end, name="")` — a single span. `parent_id`
is `None` for the root. `duration` is a property.
- `critical_path(spans)` — returns the critical path as a list of `Span` from
root to leaf.
- `critical_path_duration(spans)` — returns the total latency attributed to
that path.
- `parse_spans(rows)` — converts a list of mappings (e.g. parsed JSON) into
`Span` objects. Required keys are `span_id`, `start`, `end`; `parent_id` and
`name` are optional.
- `SpanTreeError` — raised for malformed input: empty input, multiple roots,
missing parents, duplicate ids, or a span ending before it starts.

Times are integers in a unit of your choosing (microseconds, milliseconds,
nanoseconds). Keep the unit consistent across a trace; the library does no
conversion.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

