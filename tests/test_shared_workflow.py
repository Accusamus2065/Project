import unittest
from tests import test_core
from harvest import core, monthly

class SharedWorkflowTests(unittest.TestCase):
    setUp = test_core.BusinessRules.setUp
    tearDown = test_core.BusinessRules.tearDown
    run_action = test_core.BusinessRules.run_action
    report = test_core.BusinessRules.report

    def payload(self, name='金针菇', **reuse):
        return dict(name=name,start_date=self.day,steps={key:dict(mode='existing',id=reuse[key]) if key in reuse else dict(mode='new',name=name,unit='筐' if key=='harvest' else '盒',price=5 if key=='harvest' else .2) for key in ('harvest','pack','seal')})

    def create(self, name='金针菇', **reuse):
        result=self.run_action(self.boss,'workflow',self.payload(name,**reuse))
        return dict(self.db.execute('SELECT * FROM product_workflows WHERE id=?',(result['id'],)).fetchone())

    def test_shared_harvest_and_same_stage_only(self):
        a=self.create('3lb香菇'); b=self.create('6lb香菇',harvest=a['harvest_id'])
        self.assertEqual(a['harvest_id'],b['harvest_id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM products WHERE process IS NOT NULL').fetchone()[0],5)
        with self.assertRaises(core.RuleError):self.create('错误',harvest=a['pack_id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM product_workflows').fetchone()[0],2)
        with self.assertRaises(core.RuleError):self.run_action(self.counter,'workflow',self.payload())
        p=self.db.execute('SELECT * FROM products WHERE id=?',(a['harvest_id'],)).fetchone()
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'product_delete',dict(id=p['id'],confirm_name=p['product']))

    def test_shared_pack_aggregate_and_unique_production(self):
        a=self.create('3lb香菇'); b=self.create('6lb香菇',harvest=a['harvest_id'],pack=a['pack_id'])
        self.run_action(self.worker,'report',self.report(pieces=[dict(product_id=a['pack_id'],quantity=100)]))
        self.run_action(self.other,'report',self.report(pieces=[dict(product_id=a['seal_id'],quantity=60),dict(product_id=b['seal_id'],quantity=40)]))
        checks=core.process_checks(self.db,self.day)
        self.assertEqual(len(checks),1);self.assertEqual((checks[0]['packed'],checks[0]['sealed'],checks[0]['status']),(100,100,'passed'))
        c=self.create('共用成品',harvest=a['harvest_id'],seal=a['seal_id'])
        self.assertEqual(core.process_checks(self.db,self.day)[0]['sealed'],100)
        self.assertEqual(len(monthly.build(self.db,self.boss,self.day[:7],'products')['rows']),2)
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'report',self.report(pieces=[dict(product_id=c['seal_id'],quantity=1)]))

    def test_atomic_validation(self):
        before=self.db.execute('SELECT COUNT(*) FROM products').fetchone()[0]
        payload=self.payload();payload['steps']['seal']['unit']='箱'
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'workflow',payload)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM products').fetchone()[0],before)
        a=self.create()
        payload=self.payload('另一个',harvest=a['harvest_id']);payload['steps']['harvest']['name']='篡改'
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'workflow',payload)
        payload=self.payload('另一个',harvest=a['harvest_id']);payload['start_date']=self.yesterday
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'workflow',payload)
