import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from harvest import core, monthly


class FlexibleProducts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'flex.sqlite3'
        core.initialize(self.path)
        self.db = core.connect(self.path)
        self.day = dt.date.today().isoformat()
        for name, role in [('boss','manager'), ('worker','employee'), ('other','employee')]:
            self.db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)', (name,name,role,2000,'unused'))
        self.db.commit()
        self.boss, self.worker, self.other = self.db.execute('SELECT * FROM users').fetchall()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def act(self, who, action, **data):
        with self.db:
            return core.mutate(self.db, who, action, data)

    def product(self, name, stage='finished', unit='盒'):
        self.act(self.boss, 'product', product=name, stage=stage, price='1.25', unit=unit, start_date=self.day)
        return self.db.execute('SELECT id FROM products WHERE product=?',(name,)).fetchone()[0]

    def report(self, who, pieces, **kw):
        return self.act(who,'report',date=self.day,piece_hours=2,timed=[],pieces=[{'product_id':pid,'quantity':q} for pid,q in pieces],**kw)

    def count(self, who, pid, actual, **kw):
        r=next(r for r in core.inventory(self.db,self.day) if r['id']==pid)
        self.act(who,'intake_count',date=self.day,product_id=pid,actual=actual,version=r['version'],signature=r['signature'],**kw)

    def test_single_finished_multiple_workers_and_monthly_no_double_count(self):
        finished=self.product('3lb 香菇'); semi=self.product('采摘黑筐','semi','筐')
        self.report(self.worker,[(finished,10),(semi,5)])
        self.report(self.other,[(finished,6)])
        self.count(self.boss,finished,14)
        self.act(self.boss,'direct_sale',date=self.day,product_id=finished,quantity=2,memo='测试',version=0)
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==finished)
        self.assertEqual((row['status'], row['expected']),('passed',16))
        self.assertIsNone(row['process_check'])
        report=monthly.build(self.db,self.boss,self.day[:7],'products')
        self.assertEqual(len(report['rows']),1)
        self.assertEqual(report['rows'][0][0],'3lb 香菇')
        self.assertEqual(report['rows'][0][3],16)
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['amount'],1875)

    def test_link_mismatch_recount_and_restart(self):
        pack=self.product('150g 平菇小包装','semi'); seal=self.product('150g 平菇封膜')
        self.act(self.boss,'process_link',source_id=pack,target_id=seal,start_date=self.day)
        self.report(self.worker,[(pack,100)]); self.report(self.other,[(seal,99)])
        self.count(self.boss,seal,99)
        self.act(self.boss,'direct_sale',date=self.day,product_id=seal,quantity=0,memo='无',version=0)
        self.assertEqual(core.process_checks(self.db,self.day)[0]['difference'],-1)
        self.report(self.other,[(seal,100)],version=1,reason='测试修正')
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==seal)
        self.assertTrue(row['needs_recount'])
        self.count(self.boss,seal,100,reason='复点')
        before=core.inventory(self.db,self.day)
        core.initialize(self.path);core.initialize(self.path)
        self.assertEqual(core.inventory(self.db,self.day),before)
        self.assertEqual(next(r for r in before if r['id']==seal)['status'],'passed')
        with self.assertRaises(core.RuleError):
            self.act(self.boss,'process_link',source_id=pack,target_id=seal,start_date=self.day)
        with self.assertRaises(core.RuleError):
            self.act(self.boss,'product_delete',id=pack,confirm_name='150g 平菇小包装')
        self.assertEqual(len(core.process_checks(self.db,self.day)),1)

    def test_employee_count_grant_privacy_and_revoke(self):
        pid=self.product('2lb 平菇')
        with self.assertRaises(core.RuleError): self.count(self.worker,pid,10)
        self.act(self.boss,'user',id=self.worker['id'],name='worker',rate=20,can_count='1')
        self.worker=self.db.execute('SELECT * FROM users WHERE id=?',(self.worker['id'],)).fetchone()
        self.report(self.worker,[(pid,10)])
        self.report(self.other,[(pid,2)])
        state=core.state(self.db,self.worker,self.day)
        self.assertTrue(state['user']['can_count'])
        self.assertEqual(len(state['reports']),1)
        self.assertEqual(state['users'],[])
        self.assertEqual(state['audit'],[])
        for secret in ('expected','contributors','price','direct_sold'):
            self.assertNotIn(secret,state['inventory'][0])
        self.count(self.worker,pid,12)
        with self.assertRaises(core.RuleError): self.act(self.worker,'user',id=self.worker['id'],name='worker',rate=20,can_count=1)
        self.act(self.boss,'user',id=self.worker['id'],name='worker',rate=20,can_count='0')
        self.worker=self.db.execute('SELECT * FROM users WHERE id=?',(self.worker['id'],)).fetchone()
        self.assertEqual(core.state(self.db,self.worker,self.day)['inventory'],[])
        with self.assertRaises(core.RuleError): self.count(self.worker,pid,12,reason='撤销后')
        self.assertEqual(self.db.execute('SELECT actual FROM intake_counts').fetchone()[0],12)
        changes=[json.loads(r[0]) for r in self.db.execute("SELECT detail FROM audit WHERE action='user'")]
        self.assertEqual([d['after']['can_count'] for d in changes],[1,0])

    def test_invalid_classification_units_and_migration_permission(self):
        pack=self.product('黑筐','semi','筐');seal=self.product('封膜')
        with self.assertRaises(core.RuleError): self.act(self.boss,'process_link',source_id=pack,target_id=seal,start_date=self.day)
        with self.assertRaises(core.RuleError): self.act(self.boss,'product',product='坏类型',stage='other',unit='盒',price=1,start_date=self.day)
        with self.assertRaises(core.RuleError): self.act(self.boss,'user',id=self.worker['id'],name='worker',rate=20,can_count='yes')
        self.act(self.boss,'user',id=self.worker['id'],name='worker',rate=20,can_count=1)
        core.initialize(self.path)
        self.assertEqual(self.db.execute('SELECT can_count FROM users WHERE id=?',(self.worker['id'],)).fetchone()[0],1)
