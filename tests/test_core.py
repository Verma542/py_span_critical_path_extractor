import unittest

from py_span_critical_path_extractor import (
    Span,
    SpanTreeError,
    critical_path,
    critical_path_duration,
    parse_spans,
)


def s(span_id, parent_id, start, end, name=""):
    return Span(
        span_id=span_id,
        parent_id=parent_id,
        start=start,
        end=end,
        name=name,
    )


class TestCriticalPath(unittest.TestCase):
    def test_single_root_span(self):
        spans = [s("root", None, 0, 100)]
        self.assertEqual(critical_path_duration(spans), 100)
        self.assertEqual([sp.span_id for sp in critical_path(spans)], ["root"])

    def test_sequential_children_sum(self):
        spans = [
            s("root", None, 0, 100),
            s("a", "root", 0, 40),
            s("b", "root", 40, 100),
        ]
        # Children cover the whole parent, so self time is 0 and the longest
        # chain is root -> b (duration 60).
        self.assertEqual(critical_path_duration(spans), 60)
        self.assertEqual(
            [sp.span_id for sp in critical_path(spans)], ["root", "b"]
        )

    def test_concurrent_children_counted_once(self):
        spans = [
            s("root", None, 0, 100),
            s("a", "root", 0, 100),
            s("b", "root", 0, 100),
        ]
        # Both children run for the whole parent; the latency is 100, not 200.
        self.assertEqual(critical_path_duration(spans), 100)

    def test_partial_overlap(self):
        spans = [
            s("root", None, 0, 100),
            s("a", "root", 0, 60),
            s("b", "root", 40, 100),
        ]
        # Union of children covers [0, 100], so self time is 0 and the longest
        # child is 60.
        self.assertEqual(critical_path_duration(spans), 60)

    def test_self_time_when_children_do_not_cover_parent(self):
        spans = [
            s("root", None, 0, 100),
            s("a", "root", 10, 30),
        ]
        # Parent self time = 100 - 20 = 80; child adds 20.
        self.assertEqual(critical_path_duration(spans), 100)

    def test_deep_chain(self):
        spans = [
            s("root", None, 0, 100),
            s("a", "root", 0, 80),
            s("b", "a", 0, 50),
            s("c", "b", 0, 20),
        ]
        self.assertEqual(critical_path_duration(spans), 100)
        self.assertEqual(
            [sp.span_id for sp in critical_path(spans)],
            ["root", "a", "b", "c"],
        )

    def test_picks_longer_branch(self):
        spans = [
            s("root", None, 0, 100),
            s("short", "root", 0, 10),
            s("long", "root", 0, 90),
        ]
        self.assertEqual(
            [sp.span_id for sp in critical_path(spans)], ["root", "long"]
        )

    def test_tie_is_deterministic(self):
        spans = [
            s("root", None, 0, 100),
            s("first", "root", 0, 50),
            s("second", "root", 0, 50),
        ]
        # Equal-length branches; the first supplied wins.
        self.assertEqual(
            [sp.span_id for sp in critical_path(spans)], ["root", "first"]
        )

    def test_child_clipped_to_parent(self):
        spans = [
            s("root", None, 0, 100),
            s("over", "root", -50, 150),
        ]
        # The child extends beyond the parent; only the overlap counts.
        self.assertEqual(critical_path_duration(spans), 100)

    def test_zero_duration_spans(self):
        spans = [
            s("root", None, 5, 5),
            s("child", "root", 5, 5),
        ]
        self.assertEqual(critical_path_duration(spans), 0)

    def test_empty_input_raises(self):
        with self.assertRaises(SpanTreeError):
            critical_path([])

    def test_multiple_roots_raise(self):
        spans = [
            s("a", None, 0, 10),
            s("b", None, 0, 10),
        ]
        with self.assertRaises(SpanTreeError):
            critical_path(spans)

    def test_missing_parent_raises(self):
        spans = [s("a", "ghost", 0, 10)]
        with self.assertRaises(SpanTreeError):
            critical_path(spans)

    def test_duplicate_id_raises(self):
        spans = [
            s("root", None, 0, 10),
            s("root", "root", 0, 5),
        ]
        with self.assertRaises(SpanTreeError):
            critical_path(spans)

    def test_negative_duration_raises(self):
        spans = [s("root", None, 10, 0)]
        with self.assertRaises(SpanTreeError):
            critical_path(spans)

    def test_parse_spans(self):
        rows = [
            {"span_id": "root", "start": 0, "end": 100},
            {
                "span_id": "a",
                "parent_id": "root",
                "start": 0,
                "end": 50,
                "name": "work",
            },
        ]
        spans = parse_spans(rows)
        self.assertEqual(len(spans), 2)
        self.assertIsNone(spans[0].parent_id)
        self.assertEqual(spans[1].parent_id, "root")
        self.assertEqual(spans[1].name, "work")
        self.assertEqual(critical_path_duration(spans), 100)

    def test_parse_spans_missing_field(self):
        with self.assertRaises(SpanTreeError):
            parse_spans([{"span_id": "root", "start": 0}])


if __name__ == "__main__":
    unittest.main()
