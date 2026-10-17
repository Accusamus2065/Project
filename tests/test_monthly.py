from tests.legacy_fixture import product as legacy_product
import csv
import io
import tempfile
import unittest
from pathlib import Path
from harvest import core, monthly

class MonthlyReports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'month.sqlite'
        core.initialize(self.path);self.db=core.connect(self.path)
        for username,name,role,rate in [('boss','经理','manager',2000),('worker','=SUM(A1)','employee',1760),('idle','未提交员工','employee',1850),('checker','点货员','checker',0)]:
            self.db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)',(username,name,role,rate,'unused'))
        self.boss,self.worker,self.idle,self.checker=self.db.execute('SELECT * FROM users ORDER BY id').fetchall()
        self.db.execute("INSERT INTO products(product,price,start_date) VALUES('三磅香菇',106,'2024-01-01')")
        self.db.commit()
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def act(self,user,action,data):
        with self.db:return core.mutate(self.db,user,action,data)
    def report(self,day,qty=10):
        self.act(self.worker,'report',{'date':day,'piece_hours':6.5,'pieces':[{'product_id':1,'quantity':qty}],'timed':[{'hours':1.5,'memo':'接种'}]})
    def count(self,day,actual,pid=1):
        row=next(r for r in core.inventory(self.db,day) if r['id']==pid)
        self.act(self.checker,'intake_count',{'date':day,'product_id':pid,'actual':actual,'version':row['version'],'signature':row['signature']})
    def test_employee_month_boundaries_and_price_snapshots(self):
        for day in ('2025-12-31','2026-01-01','2026-01-31','2026-02-01'):self.report(day)
        self.act(self.boss,'product',{'id':1,'price':99})
        report=monthly.build(self.db,self.boss,'2026-01','employees')
        row=report['rows'][0]
        self.assertNotIn('登录账号',report['columns'])
        self.assertNotIn('月份',report['columns'])
        self.assertIn('计件工作时长（小时）',report['columns'])
        self.assertIn('计时工作时长（小时）',report['columns'])
        self.assertEqual(row,['=SUM(A1)','74.00','16.00','21.20','52.80','13.00','3.00','4.63',2,'成品 20 盒',2])
        self.assertEqual(report['rows'][1][8],0)
        self.assertEqual(len(report['rows']),2)
        self.assertEqual((report['start'],report['end']),('2026-01-01','2026-01-31'))
        csv_rows=list(csv.reader(io.StringIO(monthly.to_csv(report).decode('utf-8-sig'))))
        self.assertEqual(csv_rows[1][0],"'=SUM(A1)")
        self.assertEqual(csv_rows[1][1:5],['74.00','16.00','21.20','52.80'])
    def test_product_month_differences_do_not_cancel_status(self):
        for day in ('2026-01-01','2026-01-02','2026-01-03'):
            self.report(day)
            self.act(self.boss,'direct_sale',dict(date=day,product_id=1,quantity=0,version=0,memo='无直售'))
        self.count('2026-01-01',8);self.count('2026-01-02',12)
        report=monthly.build(self.db,self.boss,'2026-01','products')
        self.assertNotIn('月份',report['columns'])
        self.assertNotIn('月份',next(csv.reader(io.StringIO(monthly.to_csv(report).decode('utf-8-sig')))))
        row=report['rows'][0]
        self.assertEqual(row,['三磅香菇',20,0,20,'待核对',30,0,2,1,2,0,0,'盒'])
        self.act(self.boss,'direct_sale',{'date':'2026-01-01','product_id':1,'quantity':2,'version':1,'reason':'补登直售','memo':'直售'})
        row=monthly.build(self.db,self.boss,'2026-01','products')['rows'][0]
        self.assertEqual([row[1],row[2],row[3],row[6]],[20,2,22,2])
        self.assertEqual(row[9],1)
        self.act(self.boss,'product_delete',{'id':1,'confirm_name':self.db.execute('SELECT product FROM products WHERE id=?',(1,)).fetchone()[0]})
        self.assertEqual(len(monthly.build(self.db,self.boss,'2026-01','products')['rows']),1)
    def test_no_count_is_blank_not_zero_and_sales_only_included(self):
        self.act(self.boss,'direct_sale',{'date':'2026-01-04','product_id':1,'quantity':10,'version':0,'memo':'直售'})
        row=monthly.build(self.db,self.boss,'2026-01','products')['rows'][0]
        self.assertEqual([row[1],row[2],row[3],row[6]],['',10,'',''])
        self.count('2026-01-04',0)
        row=monthly.build(self.db,self.boss,'2026-01','products')['rows'][0]
        self.assertEqual([row[1],row[2],row[3],row[6]],[0,10,10,10])
    def test_access_month_validation_empty_and_leap_year(self):
        for user in (self.worker,self.checker):
            with self.assertRaises(core.RuleError):monthly.build(self.db,user,'2026-01','employees')
        for month in ('2026-1','2026-13','garbage','9999-12','0000-01'):
            with self.assertRaises(core.RuleError):monthly.build(self.db,self.boss,month,'products')
        with self.assertRaises(core.RuleError):monthly.build(self.db,self.boss,'2026-01','other')
        report=monthly.build(self.db,self.boss,'2024-02','products')
        self.assertEqual(report['end'],'2024-02-29');self.assertEqual(report['rows'],[])

    def test_semi_and_finished_different_workers_across_months(self):
        legacy_product(self.db,{'product':'香菇采摘','price':5,'stage':'semi','unit':'筐','start_date':'2024-01-01'})
        legacy_product(self.db,{'product':'150克香菇','price':.5,'stage':'finished','unit':'盒','start_date':'2024-01-01'})
        self.act(self.worker,'report',{'date':'2026-01-31','piece_hours':5,'pieces':[{'product_id':2,'quantity':10,'stage':'finished','unit':'盒'}],'timed':[]})
        with self.assertRaises(core.RuleError):self.count('2026-01-31',10,pid=2)
        self.act(self.idle,'report',{'date':'2026-02-01','piece_hours':4,'pieces':[{'product_id':3,'quantity':150}],'timed':[]})
        self.count('2026-02-01',150,pid=3)
        jan=monthly.build(self.db,self.boss,'2026-01','employees')
        self.assertEqual(jan['rows'][0][1],'50.00')
        self.assertEqual(jan['rows'][0][9],'半成品 10 筐')
        self.assertEqual(jan['rows'][0][10],0)
        self.assertEqual(monthly.build(self.db,self.boss,'2026-01','products')['rows'],[])
        feb=monthly.build(self.db,self.boss,'2026-02','employees')
        self.assertEqual(feb['rows'][1][1],'75.00')
        goods=monthly.build(self.db,self.boss,'2026-02','products')
        self.assertEqual(len(goods['rows']),1)
        self.assertEqual(goods['rows'][0][:2],['150克香菇',150])
        jan_count=next(r for r in core.inventory(self.db,'2026-01-31') if r['id']==2)
        self.assertEqual((jan_count['actual'],jan_count['status']),(None,'na'))
        state=core.state(self.db,self.checker,'2026-01-31')
        self.assertNotIn(2,[r['id'] for r in state['inventory']])
        with self.assertRaises(core.RuleError):self.act(self.boss,'direct_sale',{'date':'2026-01-31','product_id':2,'quantity':1,'version':0,'memo':'错误的半成品直售'})

    def test_mixed_units_performance_and_stage_guards(self):
        legacy_product(self.db,{'product':'香菇采摘','price':5,'stage':'semi','start_date':'2024-01-01'})
        self.act(self.worker,'report',{'date':'2026-01-01','piece_hours':6,'pieces':[{'product_id':1,'quantity':10},{'product_id':2,'quantity':2}],'timed':[]})
        row=monthly.build(self.db,self.boss,'2026-01','employees')['rows'][0]
        self.assertEqual(row[1],'20.60')
        self.assertEqual(row[9],'成品 10 盒；半成品 2 筐')
        self.assertEqual(row[10],1)
        for payload in ({'id':2,'price':6,'stage':'finished'},{'id':2,'price':6,'unit':'盒'},{'product':'bad','price':5,'stage':'unknown','start_date':'2024-01-01'},{'product':'bad','price':5,'unit':'','start_date':'2024-01-01'}):
            with self.assertRaises(core.RuleError):self.act(self.boss,'product',payload)
        self.act(self.boss,'product',{'id':2,'price':6})
        self.act(self.boss,'product_delete',{'id':2,'confirm_name':self.db.execute('SELECT product FROM products WHERE id=?',(2,)).fetchone()[0]})
        self.act(self.worker,'report',{'date':'2026-01-01','version':1,'reason':'数量修正','piece_hours':6,'pieces':[{'product_id':2,'quantity':3}],'timed':[]})
        row=monthly.build(self.db,self.boss,'2026-01','employees')['rows'][0]
        self.assertEqual((row[1],row[9]),('15.00','半成品 3 筐'))
        self.assertEqual(monthly.build(self.db,self.boss,'2026-01','products')['rows'],[])
