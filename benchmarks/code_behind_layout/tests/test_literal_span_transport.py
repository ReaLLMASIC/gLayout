"""The new teacher must share the existing slots and preserve old routes."""
import unittest
from scripts.gpt_teacher_transport_gate import upstream_for


class LiteralSpanRouteTests(unittest.TestCase):
    def test_old_routes_preserve_target_and_body_path(self):
        for spans in (False, True):
            for target in (8115, 8116):
                self.assertEqual(upstream_for(target, '/decision', True, spans), (target, '/decision'))
                self.assertEqual(upstream_for(target, '/health', True, spans), (target, '/health'))

    def test_planning_route_is_unchanged(self):
        for spans in (False, True):
            self.assertEqual(upstream_for(8116, '/context16384/decision', True, spans), (8118, '/decision'))
            self.assertEqual(upstream_for(8116, '/context16384/health', True, spans), (8118, '/health'))

    def test_explicit_span_routes_only(self):
        for suffix in ('decision', 'health'):
            self.assertEqual(upstream_for(8116, '/spans/'+suffix, True, True), (8122, '/'+suffix))
            self.assertEqual(upstream_for(8116, '/spans/'+suffix, True, False), (8116, '/spans/'+suffix))
            self.assertEqual(upstream_for(8115, '/spans/'+suffix, True, True), (8115, '/spans/'+suffix))
        self.assertEqual(upstream_for(8116, '/spans/unknown', True, True), (8116, '/spans/unknown'))


if __name__ == '__main__':
    unittest.main()
