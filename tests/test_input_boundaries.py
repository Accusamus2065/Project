"""Regression coverage for malformed and extreme user-entered numeric values."""
import unittest
from harvest import core
from tests import test_core


class InputBoundaries(unittest.TestCase):
    setUp = test_core.BusinessRules.setUp
    tearDown = test_core.BusinessRules.tearDown
    run_action = test_core.BusinessRules.run_action
    report = test_core.BusinessRules.report

    def test_extreme_numbers_rejected_without_rounding(self):
        for value in ('1e9999999', '1e-9999999', '1.00000000000000000000000000001',
                      'NaN', '-Infinity', None, True, {}, []):
            with self.subTest(value=value), self.assertRaises(core.RuleError):
                core.number(value, '数量')
        self.assertEqual(core.number('10000000', '数量'), 10000000)
        self.assertEqual(core.number('1.05', '单价', 100), 105)
        self.assertEqual(core.number('0.05', '小时', 60), 3)
        self.assertEqual(core.number('0', '数量'), 0)

    def test_rejected_report_inputs_do_not_write_partial_records(self):
        changes = [
            {'pieces': [None]}, {'timed': [None]}, {'pieces': {}},
            {'piece_hours': '1e9999999'}, {'piece_hours': '1e-9999999'},
            {'pieces': [{'product_id': 1, 'quantity': '1e9999999'}]},
            {'pieces': [{'product_id': 1, 'quantity': '1.00000000000000000000000000001'}]},
            {'timed': [{'hours': -1, 'memo': '清洁'}]},
            {'timed': [{'hours': 1, 'memo': '   '}]},
            {'date': ''}, {'date': '2026-02-30'},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(core.RuleError):
                self.run_action(self.worker, 'report', self.report(**change))
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 0)
        self.run_action(self.worker, 'report', self.report())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 1)

    def test_timed_only_and_exact_daily_hour_limit(self):
        self.run_action(self.worker, 'report', self.report(piece_hours=0, pieces=[], timed=[{'hours': 24, 'memo': '计时工作'}]))
        row = core.state(self.db, self.worker, self.day)['reports'][0]
        self.assertEqual((row['minutes'], row['amount']), (1440, 1760 * 24))
        with self.assertRaises(core.RuleError):
            self.run_action(self.worker, 'report', self.report(version=1, reason='超时', piece_hours=.05, pieces=[], timed=[{'hours': 24, 'memo': '计时工作'}]))
        self.assertEqual(core.state(self.db, self.worker, self.day)['reports'][0]['version'], 1)
