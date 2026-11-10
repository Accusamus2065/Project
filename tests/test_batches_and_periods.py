import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from harvest import core, monthly, batches


class NewFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'test.sqlite'
        core.initialize(self.path); self.db=core.connect(self.path)
        for name,role,can_count in [('boss','manager',1),('worker','employee',0),('counter','employee',1)]:
            self.db.execute('INSERT INTO users(username,name,role,rate,password,can_count) VALUES(?,?,?,?,?,?)',(name,name,role,2000,'unused',can_count))
        self.boss,self.worker,self.counter=self.db.execute('SELECT * FROM users ORDER BY id').fetchall()
        for name,stage in [('2lb平菇','finished'),('分装','semi')]:
            self.db.execute('INSERT INTO products(product,stage,price,start_date) VALUES(?,?,?,?)',(name,stage,100,'2024-01-01'))
        self.db.commit();self.today=dt.date.today().isoformat()
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def act(self,actor,action,**data):
        with self.db:return core.mutate(self.db,actor,action,data)
    def report(self,date=None,**kw):
        return self.act(self.worker,'report',date=date or self.today,piece_hours=1,pieces=kw.pop('pieces',[dict(product_id=1,quantity=50,lot_number='A'),dict(product_id=1,quantity=60,lot_number='B')]),**kw)
    def count(self,pid,qty,**kw):
        row=next(r for r in core.inventory(self.db,self.today) if r['id']==pid)
        return self.act(self.counter,'intake_count',date=self.today,product_id=pid,actual=qty,version=row['version'],signature=row['signature'],**kw)
    def test_lot_totals_price_history_and_counts_ignore_lot(self):
        self.report()
        row=next(r for r in core.inventory(self.db,self.today) if r['id']==1)
        self.assertEqual(row['expected'],110)
        self.assertEqual(batches.search(self.db,self.boss,'A')['products'][0]['quantity'],50)
        self.count(1,110)
        oldsig=row['signature']
        self.db.execute('UPDATE products SET price=900 WHERE id=1');self.db.commit()
        self.report(version=1,reason='改批号',pieces=[dict(product_id=1,quantity=50,lot_number='C'),dict(product_id=1,quantity=60,lot_number='B')])
        r=core.state(self.db,self.worker,self.today)['reports'][0]
        self.assertEqual(r['amount'],11000)
        self.assertEqual(batches.search(self.db,self.boss,'A')['rows'],[])
        self.assertEqual(next(r for r in core.inventory(self.db,self.today) if r['id']==1)['signature'],oldsig)
        self.assertNotIn('lot_number',core.state(self.db,self.counter,self.today)['inventory'][0])
        with self.assertRaises(core.RuleError):batches.search(self.db,self.worker,'B')
    def test_invalid_lots_and_duplicate(self):
        for pieces in [[dict(product_id=2,quantity=1,lot_number='A')], [dict(product_id=1,quantity=1,lot_number='A')]*2,[dict(product_id=1,quantity=1,lot_number='x'*81)]]:
            with self.assertRaises(core.RuleError):self.report(pieces=pieces)
    def test_optional_semi_count_and_permissions_history(self):
        with self.assertRaises(core.RuleError): self.count(2,10)
        with self.assertRaises(core.RuleError): self.act(self.worker,'counting_setting',id=2,enabled=True,previous=False)
        self.act(self.boss,'counting_setting',id=2,enabled=True,previous=False)
        self.report(pieces=[dict(product_id=2,quantity=10)])
        self.count(2,10)
        row=next(r for r in core.inventory(self.db,self.today) if r['id']==2)
        self.assertEqual(row['status'],'passed');self.assertNotIn('直售登记',row['missing_records'])
        public=next(r for r in core.state(self.db,self.counter,self.today)['inventory'] if r['id']==2)
        self.assertNotIn('expected',public);self.assertNotIn('contributors',public)
        self.act(self.boss,'counting_setting',id=2,enabled=False,previous=True)
        self.assertTrue(next(r for r in core.inventory(self.db,self.today) if r['id']==2)['count_enabled'])
        self.assertFalse(next(r for r in core.inventory(self.db,'2024-01-02') if r['id']==2)['count_enabled'])
        core.initialize(self.path)
        self.assertEqual(self.db.execute('SELECT count(*) FROM counting_settings').fetchone()[0],1)
    def test_cross_month_inclusive_period_and_csv(self):
        for day in ['2025-09-24','2025-09-25','2025-10-25','2025-10-26']:self.report(date=day)
        r=monthly.build(self.db,self.boss,'','employees','2025-09-25','2025-10-25')
        self.assertEqual(r['rows'][0][r['columns'].index('总产值')],'220.00')
        self.assertEqual((r['start'],r['end']),('2025-09-25','2025-10-25'))
        self.assertIn('220.00',monthly.to_csv(r).decode('utf-8-sig'))
        for start,end in [('2025-10-25','2025-09-25'),('', '2025-10-25'),('2025-09-25','9999-01-01')]:
            with self.assertRaises(core.RuleError):monthly.build(self.db,self.boss,'','employees',start,end)
        with self.assertRaises(core.RuleError):monthly.build(self.db,self.worker,'','employees','2025-09-25','2025-10-25')

    def test_same_lot_across_products_days_and_people(self):
        self.db.execute("INSERT INTO products(product,stage,price,start_date) VALUES('香菇','finished',200,'2024-01-01')")
        self.db.commit()
        self.report(date='2025-09-25', pieces=[dict(product_id=1,quantity=50,lot_number='SHARED')])
        self.report(date='2025-09-26', pieces=[dict(product_id=1,quantity=60,lot_number='SHARED'),dict(product_id=3,quantity=10,lot_number='SHARED')])
        self.act(self.counter,'report',date='2025-09-26',piece_hours=1,pieces=[dict(product_id=1,quantity=20,lot_number='SHARED')])
        result=batches.search(self.db,self.boss,'SHARED')
        self.assertEqual(len(result['rows']),4)
        self.assertEqual({p['product']:p['quantity'] for p in result['products']},{'2lb平菇':130,'香菇':10})
        self.assertEqual({r['username'] for r in result['rows']},{'worker','counter'})
        self.assertEqual(batches.search(self.db,self.boss,'shared'),result)

    def test_count_setting_history_and_stale_editor(self):
        self.db.execute("INSERT INTO counting_settings VALUES(2,'2025-09-25',1)")
        self.db.commit()
        self.act(self.boss,'counting_setting',id=2,enabled=False,previous=True)
        self.assertTrue(next(r for r in core.inventory(self.db,'2025-09-26') if r['id']==2)['count_enabled'])
        self.assertFalse(next(r for r in core.inventory(self.db,self.today) if r['id']==2)['count_enabled'])
        with self.assertRaises(core.RuleError):
            self.act(self.boss,'counting_setting',id=2,enabled=True,previous=True)

    def test_case_variants_in_old_and_new_reports(self):
        self.report(date='2025-09-25',pieces=[dict(product_id=1,quantity=50,lot_number='aB01')])
        raw=self.db.execute('SELECT pieces FROM reports').fetchone()[0]
        self.assertEqual(json.loads(raw)[0]['lot_number'],'AB01')
        self.db.execute('UPDATE reports SET pieces=?',(raw.replace('AB01','ab01'),))
        self.report(date='2025-09-26',pieces=[dict(product_id=1,quantity=60,lot_number='Ab01')])
        self.assertEqual(batches.search(self.db,self.boss,'aB01')['products'][0]['quantity'],110)
        self.assertEqual(batches.catalog(self.db,self.boss)['products'][0]['lots'],[dict(number='AB01',quantity=110)])

    def test_new_lot_requires_ascii_letters_and_digits(self):
        for invalid in ('AB 12', 'AB-12', 'AB　12', '  ', 'AB12 ', 'Ａ１２'):
            with self.subTest(invalid=invalid), self.assertRaises(core.RuleError):
                self.report(pieces=[dict(product_id=1,quantity=1,lot_number=invalid)])
        self.report(pieces=[dict(product_id=1,quantity=1,lot_number='ab12')])
        self.assertEqual(batches.search(self.db,self.boss,'ab12')['products'][0]['quantity'],1)
