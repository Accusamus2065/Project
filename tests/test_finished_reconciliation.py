import unittest
from tests import test_core
from harvest import core,monthly

class FinishedReconciliation(unittest.TestCase):
    setUp=test_core.BusinessRules.setUp
    tearDown=test_core.BusinessRules.tearDown
    run_action=test_core.BusinessRules.run_action
    report=test_core.BusinessRules.report

    def workflow(self):
        data=dict(name='香菇',start_date=self.yesterday,steps={p:dict(mode='new',name='香菇',unit='筐' if p=='harvest' else '盒',price=1) for p in ('harvest','pack','seal')})
        self.run_action(self.boss,'workflow',data)
        return dict(self.db.execute('SELECT * FROM product_workflows').fetchone())

    def count(self,pid,actual,**extra):
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==pid)
        return self.run_action(self.counter,'intake_count',dict(date=self.day,product_id=pid,actual=actual,version=row['version'],signature=row['signature'],**extra))

    def test_two_equalities_recheck_and_permissions(self):
        w=self.workflow();h,p,s=[w[k+'_id'] for k in ('harvest','pack','seal')]
        self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=p,quantity=100)]))
        self.run_action(self.other,'report',self.report(pieces=[dict(product_id=s,quantity=100)]))
        self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=s,quantity=10,memo='直接售出',version=0))
        self.count(s,90)
        row=lambda: next(r for r in core.inventory(self.db,self.day) if r['id']==s)
        self.assertEqual(row()['status'],'passed');self.assertEqual(row()['expected_intake'],90)
        self.assertEqual(next(r for r in core.state(self.db,self.boss,self.day)['inventory'] if r['id']==s)['product'],'香菇')
        for pid in (h,p):
            with self.assertRaises(core.RuleError):self.count(pid,100)
        checker=core.state(self.db,self.counter,self.day)
        self.assertNotIn(p,[r['id'] for r in checker['inventory']])
        for r in checker['inventory']:
            self.assertNotIn('process_check',r);self.assertNotIn('expected_intake',r)
        self.run_action(self.worker,'report',self.report(version=1,reason='重新确认分包',pieces=[dict(product_id=p,quantity=99)]))
        self.assertEqual(row()['status'],'mismatch')
        self.assertEqual(row()['intake_status'],'stale')
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'mismatch')
        self.assertEqual(monthly.build(self.db,self.boss,self.day[:7],'products')['rows'][0][4],'待核对')
        self.count(s,90,reason='点货数量无误')
        self.assertEqual(row()['status'],'mismatch')
        self.run_action(self.worker,'report',self.report(version=2,reason='补齐漏记',pieces=[dict(product_id=p,quantity=100)]))
        self.assertEqual(row()['status'],'stale')
        self.count(s,90,reason='重新校对通过');self.assertEqual(row()['status'],'passed')
        self.assertEqual(monthly.build(self.db,self.boss,self.day[:7],'products')['rows'][0][0],'香菇')

    def test_picking_is_performance_only(self):
        w=self.workflow()
        self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=w['harvest_id'],quantity=12)]))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'na')
        self.assertEqual(monthly.build(self.db,self.boss,self.day[:7],'employees')['rows'][0][-1],0)

    def test_explicit_recount_and_missing_sale(self):
        w=self.workflow();p,s=w['pack_id'],w['seal_id']
        self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=p,quantity=100)]))
        self.run_action(self.other,'report',self.report(pieces=[dict(product_id=s,quantity=100)]))
        self.count(s,100)
        row=lambda: next(r for r in core.inventory(self.db,self.day) if r['id']==s)
        self.assertEqual(row()['status'],'pending')
        self.assertEqual(row()['missing_records'],['直售登记'])
        self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=s,quantity=0,memo='无直售',version=0))
        self.assertEqual(row()['status'],'passed')
        self.run_action(self.worker,'report',self.report(version=1,reason='修正',pieces=[dict(product_id=p,quantity=99)]))
        self.assertTrue(row()['needs_recount']);self.assertTrue(row()['has_difference'])
        state=core.state(self.db,self.counter,self.day)
        checker_row=next(r for r in state['inventory'] if r['id']==s)
        self.assertEqual(checker_row['status'],'stale')
        self.assertNotIn('has_difference',checker_row)
        payload=dict(date=self.day,product_id=s,version=row()['version'],signature=row()['signature'],confirm_unchanged=True,reason='已复点，实物数量正确')
        with self.assertRaises(core.RuleError):self.run_action(self.worker,'intake_count',payload)
        with self.assertRaises(core.RuleError):self.run_action(self.counter,'intake_count',dict(payload,actual=99))
        self.run_action(self.counter,'intake_count',payload)
        self.assertEqual(row()['actual'],100)
        self.assertFalse(row()['needs_recount']);self.assertTrue(row()['has_difference'])
        self.assertEqual(row()['status'],'mismatch')
        with self.assertRaises(core.RuleError):self.run_action(self.counter,'intake_count',payload)
        fresh=dict(payload,version=row()['version'],signature=row()['signature'])
        with self.assertRaises(core.RuleError):self.run_action(self.counter,'intake_count',fresh)
        self.run_action(self.worker,'report',self.report(version=2,reason='补回漏记',pieces=[dict(product_id=p,quantity=100)]))
        fresh.update(version=row()['version'],signature=row()['signature'])
        self.run_action(self.counter,'intake_count',fresh)
        self.assertEqual(row()['status'],'passed')

    def test_monthly_keeps_pack_only_discrepancy(self):
        w=self.workflow()
        self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=w['pack_id'],quantity=10)]))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'mismatch')
        report=monthly.build(self.db,self.boss,self.day[:7],'products')
        self.assertEqual(len(report['rows']),1)
        row=dict(zip(report['columns'],report['rows'][0]))
        self.assertEqual(row['核对状态'],'待核对')
        self.assertEqual(row['差异天数'],1)
        self.assertEqual(row['实际入库合计（已填）'],'')

    def test_monthly_zero_count_without_employee_report_is_pending(self):
        w=self.workflow();s=w['seal_id']
        self.count(s,0)
        self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=s,quantity=0,memo='无直售',version=0))
        dayrow=next(r for r in core.inventory(self.db,self.day) if r['id']==s)
        self.assertEqual(dayrow['status'],'pending')
        report=monthly.build(self.db,self.boss,self.day[:7],'products')
        self.assertEqual(report['rows'][0][4],'待核对')
