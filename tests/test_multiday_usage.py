"""Several shifts with late corrections and product retirement."""
import datetime as dt
import unittest
from tests import test_core, test_finished_reconciliation
from harvest import core, monthly

class MultiDayUsage(unittest.TestCase):
    setUp=test_core.BusinessRules.setUp
    tearDown=test_core.BusinessRules.tearDown
    run_action=test_core.BusinessRules.run_action
    report=test_core.BusinessRules.report
    workflow=test_finished_reconciliation.FinishedReconciliation.workflow
    count=test_finished_reconciliation.FinishedReconciliation.count

    def test_five_days_late_corrections_do_not_change_other_days(self):
        today=dt.date.today()
        dates=[(today-dt.timedelta(days=6-i)).isoformat() for i in range(5)]
        self.yesterday=dates[0];w=self.workflow();p,s=w['pack_id'],w['seal_id']
        for i,day in enumerate(dates):
            self.day=day;qty=100+i*10;sold=10 if i%2 else 0
            self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=p,quantity=qty)]))
            self.run_action(self.other,'report',self.report(pieces=[dict(product_id=s,quantity=qty)]))
            self.run_action(self.boss,'direct_sale',dict(date=day,product_id=s,quantity=sold,memo='当日累计',version=0))
            self.count(s,qty-sold)
            self.assertEqual(next(r for r in core.inventory(self.db,day) if r['id']==s)['status'],'passed')
        # On the fifth day, fix the second day's packing and sealing totals.
        self.day=dates[1]
        for actor,pid in ((self.worker,p),(self.other,s)):
            self.run_action(actor,'report',self.report(version=1,reason='核实漏记两盒',pieces=[dict(product_id=pid,quantity=112)]))
        self.count(s,102,reason='补录复点数量')
        for i,day in enumerate(dates):
            row=next(r for r in core.inventory(self.db,day) if r['id']==s)
            self.assertEqual(row['expected'],112 if i==1 else 100+i*10)
            self.assertEqual(row['status'],'passed')
        report=monthly.build(self.db,self.boss,dates[0][:7],'products')
        expected=sum(112 if i==1 else 100+i*10 for i,d in enumerate(dates) if d[:7]==dates[0][:7])
        self.assertEqual(report['rows'][0][3],expected)
        self.assertEqual(report['rows'][0][4],'核对通过')

    def test_retired_product_keeps_unfinished_previous_day_visible(self):
        w=self.workflow();p,s=w['pack_id'],w['seal_id']
        self.run_action(self.worker,'report',self.report(date=self.yesterday,pieces=[dict(product_id=p,quantity=20)]))
        product=self.db.execute('SELECT product FROM products WHERE id=?',(s,)).fetchone()[0]
        self.run_action(self.boss,'product_delete',dict(id=s,confirm_name=product))
        # Retirement today must not hide yesterday's unsealed work from manager/monthly review.
        rows=core.state(self.db,self.boss,self.yesterday)['inventory']
        self.assertIn(s,[r['id'] for r in rows])
        self.assertEqual(next(r for r in rows if r['id']==s)['status'],'mismatch')
        report=monthly.build(self.db,self.boss,self.yesterday[:7],'products')
        self.assertEqual(len(report['rows']),1)
        self.assertEqual(report['rows'][0][4],'待核对')

    def test_month_boundary_days_off_and_price_changes(self):
        today=dt.date.today();boundary=today.replace(day=1)
        if today.day<3: boundary=(boundary-dt.timedelta(days=1)).replace(day=1)
        first=boundary-dt.timedelta(days=2)
        self.yesterday=first.isoformat();w=self.workflow();p,s=w['pack_id'],w['seal_id']
        expected={}
        for offset in range(4):
            self.day=(first+dt.timedelta(days=offset)).isoformat()
            if offset==1: continue  # No production: no artificial attendance or stock count.
            if offset==2:
                self.run_action(self.boss,'product',dict(id=p,price=2))
                self.run_action(self.boss,'user',dict(id=self.worker['id'],name='worker',rate=20))
            self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=p,quantity=20)]))
            self.run_action(self.other,'report',self.report(pieces=[dict(product_id=s,quantity=20)]))
            self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=s,quantity=0,memo='无直售',version=0))
            self.count(s,20)
            expected[self.day[:7]]=expected.get(self.day[:7],0)+20
        for month,qty in expected.items():
            report=monthly.build(self.db,self.boss,month,'products')
            self.assertEqual(report['rows'][0][3],qty)
            self.assertEqual(report['rows'][0][4],'核对通过')
            wages=monthly.build(self.db,self.boss,month,'employees')
            row=next(r for r in wages['rows'] if r[0]=='worker')
            self.assertEqual(row[wages['columns'].index('提交天数')],qty//20)
        first_report=self.db.execute('SELECT amount FROM reports WHERE user_id=? AND date=?',
            (self.worker['id'],first.isoformat())).fetchone()[0]
        self.day=first.isoformat()
        self.run_action(self.worker,'report',self.report(version=1,reason='月底修正备注',
            pieces=[dict(product_id=p,quantity=20)],timed=[dict(hours=1.5,memo='补充说明')]))
        self.assertEqual(self.db.execute('SELECT amount FROM reports WHERE user_id=? AND date=?',
            (self.worker['id'],self.day)).fetchone()[0],first_report)
        off=(first+dt.timedelta(days=1)).isoformat()
        self.assertEqual(core.state(self.db,self.worker,off)['reports'],[])
