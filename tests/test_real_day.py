"""A complete shift, using independent temporary databases and real business actions."""
import csv
import io
import unittest
from tests import test_finished_reconciliation
from tests import test_core
from harvest import core, monthly


class RealProductionDay(unittest.TestCase):
    setUp = test_core.BusinessRules.setUp
    tearDown = test_core.BusinessRules.tearDown
    run_action = test_core.BusinessRules.run_action
    report = test_core.BusinessRules.report
    workflow = test_finished_reconciliation.FinishedReconciliation.workflow
    count = test_finished_reconciliation.FinishedReconciliation.count

    def row(self, pid):
        return next(r for r in core.inventory(self.db, self.day) if r['id'] == pid)

    def test_shift_corrections_monthly_and_csv(self):
        w = self.workflow()
        h, p, s = [w[k + '_id'] for k in ('harvest', 'pack', 'seal')]
        # Yesterday's picking is paid, but never added to finished production.
        self.run_action(self.worker, 'report', self.report(date=self.yesterday,
            pieces=[dict(product_id=h, quantity=12)]))
        # Two workers pack; a third person seals everything the same day.
        self.run_action(self.worker, 'report', self.report(pieces=[dict(product_id=p, quantity=60)]))
        self.run_action(self.other, 'report', self.report(pieces=[dict(product_id=p, quantity=40)]))
        self.run_action(self.boss, 'report', self.report(pieces=[dict(product_id=s, quantity=100)]))
        self.run_action(self.boss, 'direct_sale', dict(date=self.day, product_id=s,
            quantity=10, memo='现场十盒未入库', version=0))
        self.count(s,89)
        self.assertEqual(self.row(s)['status'], 'mismatch')
        self.count(s,90,reason='找到遗漏的一盒')
        self.assertEqual(self.row(s)['status'], 'passed')
        # A quantity correction invalidates the physical check. A stale window cannot overwrite it.
        old_count=dict(date=self.day,product_id=s,actual=90,version=self.row(s)['version'],
            signature=self.row(s)['signature'],reason='旧窗口')
        self.run_action(self.other,'report',self.report(version=1,reason='发现少记两盒',
            pieces=[dict(product_id=p,quantity=42)]))
        with self.assertRaises(core.RuleError): self.run_action(self.counter,'intake_count',old_count)
        self.assertTrue(self.row(s)['needs_recount'])
        self.run_action(self.boss,'report',self.report(version=1,reason='封膜也漏记两盒',
            pieces=[dict(product_id=s,quantity=102)]))
        self.count(s,92,reason='重新点货共九十二盒')
        self.assertEqual(self.row(s)['status'],'passed')
        # Updating prices later must not change wages for already submitted work.
        before={r['id']:r['amount'] for r in self.db.execute('SELECT id,amount FROM reports')}
        self.run_action(self.boss,'product',dict(id=p,price=9))
        self.run_action(self.worker,'report',self.report(version=1,reason='只更新备注',
            pieces=[dict(product_id=p,quantity=60)],timed=[dict(hours=1.5,memo='清理设备')]))
        after={r['id']:r['amount'] for r in self.db.execute('SELECT id,amount FROM reports')}
        self.assertEqual(before,after)
        self.assertEqual(self.row(s)['status'],'passed')
        report=monthly.build(self.db,self.boss,self.day[:7],'products')
        self.assertEqual(len(report['rows']),1)
        values=dict(zip(report['columns'],report['rows'][0]))
        self.assertEqual(values['实际入库合计（已填）'],92)
        self.assertEqual(values['未入库直售合计'],10)
        self.assertEqual(values['入库 + 直售（已填）'],102)
        self.assertEqual(values['核对状态'],'核对通过')
        csvrows=list(csv.reader(io.StringIO(monthly.to_csv(report).decode('utf-8-sig'))))
        self.assertEqual(csvrows[0],report['columns'])
        self.assertEqual(csvrows[1],[str(v) for v in report['rows'][0]])
        employee=monthly.build(self.db,self.boss,self.day[:7],'employees')
        self.assertEqual(sum(float(r[1]) for r in employee['rows']),
            sum(r['amount'] for r in self.db.execute('SELECT amount FROM reports WHERE date LIKE ?',
                (self.day[:7]+'%',)))/100)

    def test_all_direct_sale_still_requires_zero_count(self):
        w=self.workflow();p,s=w['pack_id'],w['seal_id']
        self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=p,quantity=100)]))
        self.run_action(self.other,'report',self.report(pieces=[dict(product_id=s,quantity=100)]))
        self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=s,quantity=100,memo='全部直接售出',version=0))
        self.assertEqual(self.row(s)['status'],'pending')
        self.count(s,0)
        self.assertEqual(self.row(s)['status'],'passed')
        values=monthly.build(self.db,self.boss,self.day[:7],'products')['rows'][0]
        self.assertEqual(values[1:4],[0,100,100])
