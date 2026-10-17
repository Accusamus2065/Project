from tests.legacy_fixture import product as legacy_product
import unittest
from tests import test_core
from harvest import core, monthly

class ProcessRules(unittest.TestCase):
    tearDown=test_core.BusinessRules.tearDown
    run_action=test_core.BusinessRules.run_action
    report=test_core.BusinessRules.report
    count=test_core.BusinessRules.count
    # Reuse fixture helpers, not inherited test cases.
    def setUp(self):
        test_core.BusinessRules.setUp(self)
        legacy_product(self.db,{'product':'小盒分装','stage':'semi','unit':'盒','price':.2,'start_date':self.yesterday})
        legacy_product(self.db,{'product':'采摘','stage':'semi','unit':'筐','price':5,'start_date':self.yesterday})
    def link(self,**kw):
        return {'source_id':3,'target_id':1,'start_date':self.day,**kw}
    def test_process_daily_aggregate_correction_and_separate_intake(self):
        self.run_action(self.boss,'process_link',self.link())
        self.assertEqual(core.process_checks(self.db,self.day)[0]['status'],'pending')
        self.run_action(self.worker,'report',self.report(pieces=[{'product_id':3,'quantity':30}]))
        self.run_action(self.other,'report',self.report(pieces=[{'product_id':3,'quantity':40}]))
        self.run_action(self.boss,'report',self.report(pieces=[{'product_id':3,'quantity':30},{'product_id':1,'quantity':100}]))
        r=core.process_checks(self.db,self.day)[0]
        self.assertEqual((r['packed'],r['sealed'],r['status']),(100,100,'passed'))
        self.assertEqual(len(r['packers']),3)
        self.assertEqual(next(r for r in core.inventory(self.db,self.day) if r['id']==1)['status'],'pending')
        self.run_action(self.counter,'intake_count',self.count(actual=99))
        self.assertEqual(core.process_checks(self.db,self.day)[0]['status'],'passed')
        self.run_action(self.other,'report',self.report(version=1,reason='修正',pieces=[{'product_id':3,'quantity':45}]))
        r=core.process_checks(self.db,self.day)[0]
        self.assertEqual((r['difference'],r['status']),(-5,'mismatch'))
        goods=monthly.build(self.db,self.boss,self.day[:7],'products')
        self.assertEqual(len(goods['rows']),1)
        self.assertEqual(goods['rows'][0][0],'三磅香菇')
        self.assertNotIn('process_checks',core.state(self.db,self.counter,self.day))
        self.assertEqual(core.state(self.db,self.worker,self.day)['process_checks'],[])
    def test_process_validation_and_history(self):
        for actor in (self.worker,self.counter):
            with self.assertRaises(core.RuleError):self.run_action(actor,'process_link',self.link())
        for fields in ({'source_id':4},{'source_id':1},{'target_id':3},{'target_id':999}):
            with self.assertRaises(core.RuleError):self.run_action(self.boss,'process_link',self.link(**fields))
        self.run_action(self.boss,'process_link',self.link())
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'process_link',self.link())
        self.assertEqual(core.process_checks(self.db,self.yesterday),[])
        self.run_action(self.worker,'report',self.report(date=self.yesterday,pieces=[{'product_id':3,'quantity':100}]))
        self.run_action(self.other,'report',self.report(pieces=[{'product_id':1,'quantity':100}]))
        r=core.process_checks(self.db,self.day)[0]
        self.assertEqual((r['packed'],r['sealed'],r['difference']),(0,100,100))
        self.run_action(self.boss,'product_delete',{'id':3,'confirm_name':self.db.execute('SELECT product FROM products WHERE id=?',(3,)).fetchone()[0]})
        self.assertEqual(len(core.process_checks(self.db,self.day)),1)
        core.initialize(self.path)
        self.assertEqual(len(core.process_checks(self.db,self.day)),1)

    def test_one_sealer_per_day_including_corrections_and_other_products(self):
        self.run_action(self.boss,'process_link',self.link(start_date=self.yesterday))
        legacy_product(self.db,{'product':'另一规格分装','stage':'semi','unit':'盒','price':.2,'start_date':self.yesterday})
        self.run_action(self.boss,'process_link',{'source_id':5,'target_id':2,'start_date':self.yesterday})
        self.run_action(self.worker,'report',self.report(pieces=[{'product_id':1,'quantity':100},{'product_id':2,'quantity':20}]))
        with self.assertRaisesRegex(core.RuleError,'同一人'):
            self.run_action(self.other,'report',self.report(pieces=[{'product_id':2,'quantity':10}]))
        self.run_action(self.other,'report',self.report(pieces=[{'product_id':3,'quantity':100}]))
        with self.assertRaisesRegex(core.RuleError,'同一人'):
            self.run_action(self.boss,'report',self.report(user_id=self.other['id'],version=1,reason='补报',pieces=[{'product_id':1,'quantity':10}]))
        # The sole sealer can correct their own quantity; another date can have another sealer.
        self.run_action(self.worker,'report',self.report(version=1,reason='数量修正',pieces=[{'product_id':1,'quantity':90}]))
        self.run_action(self.other,'report',self.report(date=self.yesterday,pieces=[{'product_id':1,'quantity':10}]))
        # Wrong attribution can be corrected by removing the old sealing item before reassignment.
        self.run_action(self.worker,'report',self.report(version=2,reason='登记人修正',pieces=[{'product_id':3,'quantity':10}]))
        self.run_action(self.other,'report',self.report(version=1,reason='登记人修正',pieces=[{'product_id':1,'quantity':90}]))
    def test_link_rejects_existing_multiple_sealers(self):
        self.run_action(self.worker,'report',self.report(pieces=[{'product_id':1,'quantity':30}]))
        self.run_action(self.other,'report',self.report(pieces=[{'product_id':1,'quantity':70}]))
        with self.assertRaisesRegex(core.RuleError,'同一人'):
            self.run_action(self.boss,'process_link',self.link())
        self.assertEqual(self.db.execute('SELECT count(*) FROM process_links').fetchone()[0],0)
