import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from harvest import core

class BusinessRules(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db'
        core.initialize(self.path);self.db=core.connect(self.path)
        self.day=dt.date.today().isoformat();self.yesterday=(dt.date.today()-dt.timedelta(days=1)).isoformat()
        for name,role,rate in [('boss','manager',2000),('worker','employee',1760),('other','employee',1850),('counter','checker',0)]:
            self.db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)',(name,name,role,rate,'unused'))
        self.db.execute('INSERT INTO products(product,price,start_date) VALUES(?,?,?)',('三磅香菇',106,self.yesterday))
        self.db.execute('INSERT INTO products(product,price,start_date) VALUES(?,?,?)',('两磅平菇',100,self.yesterday))
        self.db.commit();self.boss,self.worker,self.other,self.counter=self.db.execute('SELECT * FROM users ORDER BY id').fetchall()
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def run_action(self,actor,action,data):
        with self.db:return core.mutate(self.db,actor,action,data)
    def report(self,**kw):
        return {'date':self.day,'piece_hours':6.5,'pieces':[{'product_id':1,'quantity':94}],'timed':[{'hours':1.5,'memo':'接种'}],**kw}
    def count(self,pid=1,actual=94,**kw):
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==pid)
        return {'date':self.day,'product_id':pid,'actual':actual,'version':row['version'],'signature':row['signature'],**kw}
    def test_deleted_employee_history_preserved(self):
        self.run_action(self.worker,'report',self.report())
        original=core.state(self.db,self.boss,self.day)['reports'][0]
        from harvest.monthly import build
        monthly_before=build(self.db,self.boss,self.day[:7],'employees')
        self.run_action(self.boss,'user_delete',{'id':self.worker['id'],'confirm_name':'worker'})
        after=core.state(self.db,self.boss,self.day)
        self.assertEqual(after['reports'][0],original)
        self.assertEqual(build(self.db,self.boss,self.day[:7],'employees'),monthly_before)
        self.assertEqual(next(u for u in after['users'] if u['id']==self.worker['id'])['deleted'],1)
        # Historical joins must still resolve the employee, and corrections remain possible.
        self.run_action(self.boss,'report',self.report(user_id=self.worker['id'],version=original['version'],reason='核实历史记录'))
        with self.assertRaises(core.RuleError):
            self.run_action(self.boss,'report',self.report(user_id=self.worker['id'],date=self.yesterday))
        self.db.commit()
        core.initialize(self.path)
        self.assertEqual(self.db.execute('SELECT deleted FROM users WHERE id=?',(self.worker['id'],)).fetchone()[0],1)

    def test_calculation_and_persistence(self):
        self.run_action(self.worker,'report',self.report())
        r=core.state(self.db,self.worker,self.day)['reports'][0]
        self.assertEqual((r['amount'],r['minutes']),(12604,480))
        with core.connect(self.path) as db:self.assertEqual(db.execute('SELECT amount FROM reports').fetchone()[0],12604)
    def test_daily_intake_not_cumulative_and_multiple_workers(self):
        self.run_action(self.worker,'report',self.report(date=self.yesterday))
        self.run_action(self.worker,'report',self.report())
        self.run_action(self.other,'report',self.report(pieces=[{'product_id':1,'quantity':6}]))
        row=core.inventory(self.db,self.day)[0]
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==1)
        self.assertEqual(row['expected'],100)
        self.assertEqual(len(row['contributors']),2)
        self.assertNotIn('previous',row);self.assertNotIn('outgoing',row)
    def test_independent_count_match_mismatch_and_zero(self):
        self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=1,quantity=0,memo='无直售',version=0))
        self.run_action(self.worker,'report',self.report())
        self.run_action(self.counter,'intake_count',self.count(actual=92))
        r=next(r for r in core.inventory(self.db,self.day) if r['id']==1)
        self.assertEqual((r['difference'],r['status']),(-2,'mismatch'))
        self.run_action(self.counter,'intake_count',self.count(actual=94,reason='重新清点'))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'passed')
        self.run_action(self.counter,'intake_count',self.count(pid=2,actual=0))
        self.assertEqual(next(r for r in core.inventory(self.db,self.day) if r['id']==2)['status'],'pending')
    def test_count_before_reports_and_stale_recheck(self):
        self.run_action(self.counter,'intake_count',self.count(actual=94))
        self.run_action(self.worker,'report',self.report())
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'stale')
        self.run_action(self.counter,'intake_count',self.count(actual=94,reason='确认今日入库'))
        self.run_action(self.worker,'report',self.report(version=1,reason='修正数量',pieces=[{'product_id':1,'quantity':96}]))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'stale')
    def test_memo_edit_does_not_invalidate_count(self):
        self.run_action(self.boss,'direct_sale',dict(date=self.day,product_id=1,quantity=0,memo='无直售',version=0))
        self.run_action(self.worker,'report',self.report());self.run_action(self.counter,'intake_count',self.count())
        self.run_action(self.worker,'report',self.report(version=1,reason='修正备注',timed=[{'hours':1.5,'memo':'清洁'}]))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'passed')
    def test_checker_permissions_and_private_data(self):
        self.run_action(self.worker,'report',self.report())
        for action,data in [('report',self.report()),('user',{}),('product',{}),('product_delete',{'id':1,'confirm_name':self.db.execute('SELECT product FROM products WHERE id=?',(1,)).fetchone()[0]}),('shipment',{})]:
            with self.assertRaises(core.RuleError):self.run_action(self.counter,action,data)
        with self.assertRaises(core.RuleError):self.run_action(self.worker,'intake_count',self.count())
        s=core.state(self.db,self.counter,self.day)
        for key in ('reports','users','products','audit'):self.assertEqual(s[key],[])
        for row in s['inventory']:
            for key in ('expected','contributors','price','difference'):self.assertNotIn(key,row)
        self.assertNotIn('rate',s['user'])
    def test_removed_endpoints_reject_managers(self):
        for action in ('shipment','shipment_void','count','lot','lot_delete'):
            with self.assertRaises(core.RuleError):self.run_action(self.boss,action,{})
    def test_count_concurrent_edits_and_report_race(self):
        stale=self.count();self.run_action(self.worker,'report',self.report())
        with self.assertRaises(core.RuleError):self.run_action(self.counter,'intake_count',stale)
        payload=self.count();self.run_action(self.counter,'intake_count',payload)
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'intake_count',payload)
        with self.assertRaises(core.RuleError):self.run_action(self.counter,'intake_count',self.count())
    def test_prices_snapshots_and_employee_edit_audit(self):
        self.run_action(self.worker,'report',self.report())
        self.run_action(self.boss,'product',{'id':1,'price':9})
        self.run_action(self.boss,'user',{'id':2,'name':'worker','rate':99})
        self.run_action(self.worker,'report',self.report(version=1,reason='修正数量',pieces=[{'product_id':1,'quantity':100,'snapshot_id':'spoof'}]))
        r=core.state(self.db,self.worker,self.day)['reports'][0]
        self.assertEqual((r['rate'],r['amount'],r['version']),(1760,13240,2))
        log=json.loads(self.db.execute("SELECT detail FROM audit WHERE action='修改日报'").fetchone()[0])
        self.assertEqual(log['before']['amount'],12604);self.assertEqual(log['after']['amount'],13240)
    def test_cross_user_and_version_permissions(self):
        self.run_action(self.worker,'report',self.report())
        for actor,payload in [(self.other,self.report(user_id=2,version=1,reason='修改')),(self.worker,self.report(version=0,reason='旧窗口'))]:
            with self.assertRaises(core.RuleError):self.run_action(actor,'report',payload)
        self.assertEqual(core.state(self.db,self.other,self.day)['reports'],[])
    def test_invalid_inputs_atomic(self):
        for change in [{'piece_hours':-1},{'piece_hours':24},{'piece_hours':'NaN'},{'pieces':[{'product_id':1,'quantity':.5}]},{'pieces':[{'product_id':1,'quantity':1},{'product_id':1,'quantity':2,'snapshot_id':'fake'}]},{'pieces':[],'timed':[]},{'date':(dt.date.today()+dt.timedelta(days=1)).isoformat()}]:
            with self.assertRaises(core.RuleError):self.run_action(self.worker,'report',self.report(**change))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],0)
        for val in (-1,.5,'NaN',10000001):
            with self.assertRaises(core.RuleError):self.run_action(self.counter,'intake_count',self.count(actual=val))
    def test_product_start_date_and_stop_preserve_history(self):
        self.run_action(self.boss,'product',{'product':'新品','process':'harvest','price':1.2,'start_date':self.day})
        self.run_action(self.worker,'report',self.report(pieces=[{'product_id':3,'quantity':1}]))
        with self.assertRaises(core.RuleError):self.run_action(self.other,'report',self.report(date=self.yesterday,pieces=[{'product_id':3,'quantity':1}]))
        self.run_action(self.boss,'product_delete',{'id':3,'confirm_name':self.db.execute('SELECT product FROM products WHERE id=?',(3,)).fetchone()[0]})
        self.run_action(self.worker,'report',self.report(version=1,reason='修改',pieces=[{'product_id':3,'quantity':2}]))
        with self.assertRaises(core.RuleError):self.run_action(self.other,'report',self.report(pieces=[{'product_id':3,'quantity':1}]))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['pieces'][0]['price'],120)
    def test_timing_only_and_rounding(self):
        self.run_action(self.worker,'report',self.report(piece_hours=0,pieces=[],timed=[{'hours':.05,'memo':'A'},{'hours':.05,'memo':'B'}]))
        r=core.state(self.db,self.worker,self.day)['reports'][0]
        self.assertEqual((r['amount'],r['minutes'],r['status']),(176,6,'na'))
        self.assertEqual(core.money(101,30),51)
    def test_count_audit_and_password_redaction(self):
        self.run_action(self.counter,'intake_count',self.count(actual=10))
        self.run_action(self.counter,'intake_count',self.count(actual=12,reason='重数'))
        log=json.loads(self.db.execute('SELECT detail FROM audit ORDER BY id DESC').fetchone()[0])
        self.assertEqual((log['before']['actual'],log['after']['actual'],log['actor_name']),(10,12,'counter'))
        self.run_action(self.boss,'user',{'id':2,'name':'worker','rate':17.6,'password':'NewPassword123!'})
        log=self.db.execute('SELECT detail FROM audit ORDER BY id DESC').fetchone()[0]
        self.assertNotIn('NewPassword123!',log)
    def test_direct_sale_reconciles_without_changing_intake_or_pay(self):
        self.run_action(self.worker,'report',self.report())
        self.run_action(self.counter,'intake_count',self.count(actual=84))
        payload={'date':self.day,'product_id':1,'quantity':10,'memo':'经理直接售出，未入库','version':0}
        self.run_action(self.boss,'direct_sale',payload)
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==1)
        self.assertEqual((row['actual'],row['direct_sold'],row['reconciled'],row['difference'],row['status']),(84,10,94,0,'passed'))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['amount'],12604)
        self.assertEqual(next(r for r in core.inventory(self.db,self.yesterday) if r['id']==1)['direct_sold'],0)
        self.run_action(self.boss,'direct_sale',{**payload,'version':1,'quantity':9,'reason':'少记一盒'})
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==1)
        self.assertEqual((row['difference'],row['status']),(-1,'mismatch'))
        log=json.loads(self.db.execute('SELECT detail FROM audit ORDER BY id DESC').fetchone()[0])
        self.assertEqual((log['before']['quantity'],log['after']['quantity'],log['actor_name']),(10,9,'boss'))
        for r in core.state(self.db,self.counter,self.day)['inventory']:
            for key in ('direct_sold','sales_memo','sales_recorder','reconciled'):self.assertNotIn(key,r)

    def test_direct_sale_permissions_validation_and_concurrency(self):
        payload={'date':self.day,'product_id':1,'quantity':10,'memo':'现场售出','version':0}
        for actor in (self.worker,self.counter):
            with self.assertRaises(core.RuleError):self.run_action(actor,'direct_sale',payload)
        for change in ({'quantity':-1},{'quantity':.5},{'quantity':'NaN'},{'memo':''},{'product_id':999},{'date':(dt.date.today()+dt.timedelta(days=1)).isoformat()}):
            with self.assertRaises(core.RuleError):self.run_action(self.boss,'direct_sale',{**payload,**change})
        self.run_action(self.boss,'direct_sale',payload)
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'direct_sale',payload)
        with self.assertRaises(core.RuleError):self.run_action(self.boss,'direct_sale',{**payload,'version':1})
        self.run_action(self.boss,'direct_sale',{**payload,'version':1,'quantity':0,'reason':'录错日期，清零'})
        row=next(r for r in core.inventory(self.db,self.day) if r['id']==1)
        self.assertEqual((row['direct_sold'],row['status']),(0,'pending'))
        self.run_action(self.boss,'product_delete',{'id':1,'confirm_name':self.db.execute('SELECT product FROM products WHERE id=?',(1,)).fetchone()[0]})
        self.assertTrue(any(r['id']==1 for r in core.inventory(self.db,self.day)))

    def test_direct_sales_do_not_clear_stale_report_or_missing_count(self):
        payload={'date':self.day,'product_id':1,'quantity':94,'memo':'全部直售','version':0}
        self.run_action(self.worker,'report',self.report())
        self.run_action(self.boss,'direct_sale',payload)
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'pending')
        self.run_action(self.counter,'intake_count',self.count(actual=0))
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'passed')
        self.run_action(self.worker,'report',self.report(version=1,reason='修正数量',pieces=[{'product_id':1,'quantity':95}]))
        self.run_action(self.boss,'direct_sale',{**payload,'quantity':95,'version':1,'reason':'补记一盒'})
        self.assertEqual(core.state(self.db,self.worker,self.day)['reports'][0]['status'],'stale')

    def test_password_hash(self):
        h=core.password_hash('Testing1234!');self.assertTrue(core.password_ok('Testing1234!',h));self.assertFalse(core.password_ok('Incorrect00!',h))

class Migration(unittest.TestCase):
    def test_legacy_migration_is_idempotent_and_preserves_money_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.db'
            # The retained legacy schema starts with the old role constraint.
            db=sqlite3.connect(path);db.executescript(Path('harvest/schema.sql').read_text().replace("stage TEXT NOT NULL DEFAULT 'finished' CHECK(stage IN ('finished','semi')), ",''))
            db.execute("INSERT INTO users VALUES(1,'worker','员工','employee',1760,'hash')")
            db.execute("INSERT INTO lots VALUES(1,'LOT-A','三磅香菇','盒',106,120,'2026-01-01')")
            db.execute("INSERT INTO lots VALUES(2,'LOT-B','三磅香菇','盒',150,200,'2026-01-01')")
            pieces=[{'lot_id':1,'code':'LOT-A','product':'三磅香菇','unit':'盒','price':106,'quantity':2},{'lot_id':2,'code':'LOT-B','product':'三磅香菇','unit':'盒','price':150,'quantity':3}]
            db.execute('INSERT INTO reports VALUES(1,1,?,60,1760,?,?,662,1)',('2026-01-01','[]',json.dumps(pieces)))
            db.execute("INSERT INTO shipments(lot_id,date,quantity,memo,actor) VALUES(1,'2026-01-01',100,'旧出库',1)")
            db.execute("INSERT INTO sessions VALUES('token',1,'csrf',9999999999)")
            db.commit();db.close()
            core.initialize(path);core.initialize(path)
            with core.connect(path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM products').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT stage FROM products').fetchone()[0],'finished')
                self.assertEqual(db.execute('SELECT amount FROM reports').fetchone()[0],662)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],1)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
                row=core.inventory(db,'2026-01-01')[0];self.assertEqual(row['expected'],5);self.assertEqual(row['actual'],None)
                actor=db.execute('SELECT * FROM users').fetchone();r=core.state(db,actor,'2026-01-01')['reports'][0]
                core.save_report(db,actor,{'date':'2026-01-01','piece_hours':1,'version':1,'reason':'确认','pieces':r['pieces'],'timed':[]})
                self.assertEqual(db.execute('SELECT amount FROM reports').fetchone()[0],662)
                db.execute("INSERT INTO users(id,username,name,role,rate,password) VALUES(2,'checker','点货员','checker',0,'hash')")

if __name__=='__main__':unittest.main()
