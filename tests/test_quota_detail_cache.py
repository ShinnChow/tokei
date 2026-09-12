import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_codex_limits import USAGE


class QuotaDetailCacheTests(unittest.TestCase):
    def test_recent_snapshot_avoids_collection_and_preserves_quota_fields(self):
        payload = {tool: {} for tool, _ in USAGE._QUOTA_TOOLS}
        payload['codex'] = {'pw': 42, 'rw': 2000000000, 'q_updated': 1900000000}
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, '.tokei', 'last_usage.json')
            path.parent.mkdir()
            path.write_text(json.dumps(payload))
            with mock.patch.object(USAGE, 'HOME', home), mock.patch.object(USAGE, 'compute') as collect:
                self.assertEqual(USAGE._quota_detail_payload(), payload)
                collect.assert_not_called()

    def test_missing_stale_future_corrupt_and_invalid_snapshots_collect(self):
        valid = json.dumps({tool: {} for tool, _ in USAGE._QUOTA_TOOLS})
        cases = [(None, 0), (valid, -61), (valid, 120), ('{', 0), ('[]', 0), ('{}', 0)]
        for content, offset in cases:
            with self.subTest(content=content, offset=offset), tempfile.TemporaryDirectory() as home:
                path = Path(home, '.tokei', 'last_usage.json')
                path.parent.mkdir()
                if content is not None:
                    path.write_text(content)
                    stamp = time.time() + offset
                    os.utime(path, (stamp, stamp))
                with mock.patch.object(USAGE, 'HOME', home), mock.patch.object(USAGE, 'compute', return_value={'fresh': True}) as collect:
                    self.assertEqual(USAGE._quota_detail_payload(), {'fresh': True})
                    collect.assert_called_once_with()

    def test_shared_cache_preserves_deduplication_and_codex_token_units(self):
        ts = "2026-07-10T00:00:00+00:00"
        cache = {
            'claude': {'session': {'events': [
                {'mid': 'm', 'timestamp': ts, 'in': 100, 'out': 10, 'cr': 20},
                {'mid': 'm', 'timestamp': ts, 'in': 100, 'out': 10, 'cr': 20},
            ]}},
            'codex': {
                'canonical': {'canonical': True, 'event_count': 2, 'drop_count': 1},
                'duplicate': {'canonical': False, 'event_count': 2},
            },
        }
        # idx6 includes cached input; idx7 must not be added a second time.
        row = [ts, '2026-07-10', 100, 80, 5, 0, 100, 80, 5]
        with mock.patch.object(USAGE, '_load_scan_cache', return_value=cache) as load, \
             mock.patch.object(USAGE, '_iter_codex_cached_events', return_value=[row]) as rows:
            expected_claude = USAGE._quota_claude_events()
            expected_codex = USAGE._quota_codex_events([(1, 2000000000)])
            load.reset_mock()
            rows.reset_mock()
            self.assertEqual(USAGE._quota_claude_events(cache), expected_claude)
            self.assertEqual(USAGE._quota_codex_events([(1, 2000000000)], cache), expected_codex)
            self.assertEqual([e[2] for e in expected_claude], [130])
            self.assertEqual([e[2] for e in expected_codex], [105])
            rows.assert_called_once_with('canonical', start_index=1)
            load.assert_not_called()

    def test_detail_loads_event_cache_once_for_both_providers(self):
        now = int(time.time())
        cache = {'claude': {}, 'codex': {}}
        anchors = {tool: [{'reset': now + 3600, 'max_used': 20}] for tool in ('claude', 'codex')}
        with mock.patch.object(USAGE, '_quota_detail_payload', return_value={}), \
             mock.patch.object(USAGE, '_quota_device_ledgers', return_value=([], [])), \
             mock.patch.object(USAGE, '_quota_cycle_specs', return_value=(['claude', 'codex'], ['grok'], anchors)), \
             mock.patch.object(USAGE, '_load_scan_cache', return_value=cache) as load:
            result = USAGE.build_quota_detail()
            self.assertEqual(len(result['cycles']), 2)
            self.assertEqual({c['tool'] for c in result['cycles']}, {'claude', 'codex'})
            load.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
