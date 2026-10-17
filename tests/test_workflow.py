import unittest
from tests import test_core
from harvest import core, monthly

class WorkflowTests(unittest.TestCase):
    setUp=test_core.BusinessRules.setUp
    tearDown=test_core.BusinessRules.tearDown
    run_action=test_core.BusinessRules.run_action
    report=test_core.BusinessRules.report
    def create(self,process,**kw):
        self.run_action(self.boss,'product',dict(product='金针菇',process=process,price=.5,start_date=self.day,**kw))
        return self.db.execute('SELECT * FROM products ORDER BY id DESC').fetchone()
    def test_full_chain_and_monthly(self):
        a=self.create('harvest');b=self.create('pack',parent_id=a['id']);c=self.create('seal',parent_id=b['id'])
        self.assertEqual([a['product'],b['product'],c['product']],['金针菇·采摘','金针菇·分包','金针菇·封膜'])
        self.assertEqual([a['stage'],b['stage'],c['stage']],['semi','semi','finished'])
        self.assertEqual(c['parent_id'],b['id'])
        link=self.db.execute('SELECT * FROM process_links').fetchone()
        self.assertEqual((link['source_id'],link['target_id']),(b['id'],c['id']))
        audit=self.db.execute('SELECT detail FROM audit ORDER BY id DESC').fetchone()[0]
        self.assertIn('金针菇·封膜',audit)
        self.run_action(self.worker,'report',self.report(pieces=[{'product_id':b['id'],'quantity':100}]))
        self.run_action(self.other,'report',self.report(pieces=[{'product_id':c['id'],'quantity':100}]))
        self.assertEqual(core.process_checks(self.db,self.day)[0]['status'],'passed')
        self.assertEqual(len(monthly.build(self.db,self.boss,self.day[:7],'products')['rows']),1)
        self.assertEqual(monthly.build(self.db,self.boss,self.day[:7],'products')['rows'][0][0],'金针菇')
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'report',self.report(pieces=[{'product_id':c['id'],'quantity':1}]))
        for product in [a,b]:
            with self.assertRaises(core.RuleError):self.run_action(self.boss,'product_delete',{'id':product['id'],'confirm_name':product['product']})
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'product_delete',{'id':c['id'],'confirm_name':'wrong'})
        for product in [c,b,a]:self.run_action(self.boss,'product_delete',{'id':product['id'],'confirm_name':product['product']})
        self.assertEqual(len(core.process_checks(self.db,self.day)),1)
        self.run_action(self.other,'report',self.report(version=1,reason='修正',pieces=[{'product_id':c['id'],'quantity':99}]))
        self.assertEqual(core.process_checks(self.db,self.day)[0]['difference'],-1)
    def test_require_valid_parent_and_invariants(self):
        for proc in ('pack','seal','unknown',None):
            with self.assertRaises(core.RuleError):self.create(proc)
        a=self.create('harvest')
        with self.assertRaises(core.RuleError):self.create('seal',parent_id=a['id'])
        b=self.create('pack',parent_id=a['id'])
        with self.assertRaises(core.RuleError):self.create('pack',parent_id=a['id'])
        with self.assertRaises(core.RuleError):self.create('seal',parent_id=b['id'],unit='箱')
        with self.assertRaises(core.RuleError):self.create('seal',parent_id=b['id'],stage='semi')
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'product',{'id':b['id'],'price':1,'parent_id':1})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM products').fetchone()[0],4)
    def test_migration_preserves_legacy_and_is_idempotent(self):
        from tests.legacy_fixture import product
        product(self.db,dict(product='旧分包',stage='semi',unit='盒',price=1,start_date=self.yesterday))
        self.run_action(self.boss,'process_link',{'source_id':3,'target_id':1,'start_date':self.day})
        core.initialize(self.path);core.initialize(self.path)
        source=self.db.execute('SELECT * FROM products WHERE id=3').fetchone()
        target=self.db.execute('SELECT * FROM products WHERE id=1').fetchone()
        self.assertEqual((source['process'],target['process'],target['parent_id']),('pack','seal',3))
        self.assertIsNone(source['family_name'])
        self.assertEqual(target['price'],106)
