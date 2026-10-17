import datetime as dt
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from harvest import core
from harvest.server import Handler

class HTTPWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        path=Path(cls.temp.name)/'http.db';core.initialize(path)
        hashed=core.password_hash('TestPassword123!')
        with core.connect(path) as db:
            for name,role in [('boss','manager'),('worker','employee'),('counter','checker')]:
                db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)',(name,name,role,1760,hashed))
            db.execute('INSERT INTO products(product,price,start_date) VALUES(?,?,?)',('三磅香菇',106,dt.date.today().isoformat()))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.database=path;cls.server.demo=False;cls.server.secure=False;cls.server.origin=None
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def request(self,path,data=None,cookie='',csrf='',origin=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Cookie':cookie,'X-CSRF-Token':csrf}
        if data is not None:headers['Content-Type']='application/json'
        if origin:headers['Origin']=origin
        conn.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers)
        response=conn.getresponse();body=response.read();status=response.status;headers=dict(response.getheaders());conn.close()
        return status,body,headers
    def login(self,name):
        status,_,headers=self.request('/api/login',{'username':name,'password':'TestPassword123!'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        status,body,_=self.request('/api/state',cookie=cookie)
        self.assertEqual(status,200)
        return cookie,json.loads(body)['csrf']
    def test_unauthenticated_and_origin(self):
        for asset in ('/nebo-logo.webp','/nebo-icon.png','/audit.js'):
            self.assertEqual(self.request(asset)[0],200)
        self.assertEqual(self.request('/api/state')[0],401)
        self.assertEqual(self.request('/api/login',{'username':'boss','password':'TestPassword123!'},origin='https://evil.example')[0],403)
    def test_complete_employee_manager_workflow(self):
        cookie,csrf=self.login('worker')
        report={'date':dt.date.today().isoformat(),'hours':8,'pieces':[{'product_id':1,'quantity':94}],'timed':[{'hours':1.5,'memo':'=SUM(A1)'}]}
        self.assertEqual(self.request('/api/report',report,cookie)[0],403)
        self.assertEqual(self.request('/api/report',report,cookie,csrf)[0],200)
        self.assertEqual(self.request('/api/report',report,cookie,csrf)[0],400)
        self.assertEqual(self.request('/api/export',cookie=cookie)[0],400)
        self.assertEqual(self.request('/api/product',{'id':1,'price':0},cookie,csrf)[0],400)
        _,body,_=self.request('/api/state',cookie=cookie)
        data=json.loads(body);self.assertEqual(data['reports'][0]['amount'],12604);self.assertEqual(data['users'],[])
        boss,boss_csrf=self.login('boss')
        day=dt.date.today().isoformat()
        counter,counter_csrf=self.login('counter')
        _,body,_=self.request('/api/state',cookie=counter)
        count_state=json.loads(body);row=count_state['inventory'][0]
        self.assertEqual(count_state['reports'],[])
        self.assertNotIn('expected',row)
        self.assertNotIn('rate',count_state['user'])
        self.assertEqual(self.request('/api/export',cookie=counter)[0],400)
        self.assertEqual(self.request('/api/report',report,counter,counter_csrf)[0],400)
        self.assertEqual(self.request('/api/intake_count',{'date':day,'product_id':1,'actual':94,'version':row['version'],'signature':row['signature']},counter,counter_csrf)[0],200)
        self.assertEqual(self.request('/api/shipment',{'date':day,'lot_id':1,'quantity':1},boss,boss_csrf)[0],400)
        _,body,_=self.request('/api/state',cookie=cookie)
        self.assertEqual(json.loads(body)['reports'][0]['status'],'pending') # Direct sale is not yet registered.
        sale={'date':day,'product_id':1,'quantity':1,'memo':'未入库直售','version':0}
        self.assertEqual(self.request('/api/direct_sale',sale,boss)[0],403)
        self.assertEqual(self.request('/api/direct_sale',sale,counter,counter_csrf)[0],400)
        self.assertEqual(self.request('/api/direct_sale',sale,cookie,csrf)[0],400)
        self.assertEqual(self.request('/api/direct_sale',sale,boss,boss_csrf)[0],200)
        _,body,_=self.request('/api/state',cookie=boss)
        self.assertEqual(json.loads(body)['inventory'][0]['difference'],1)
        status,body,_=self.request('/api/export',cookie=boss)
        self.assertEqual(status,200);self.assertNotIn('Lot',body.decode());self.assertIn("'=SUM(A1)",body.decode('utf-8-sig'));self.assertIn('126.04',body.decode())
        self.assertEqual(self.request('/api/logout',{},cookie,csrf)[0],200)
        self.assertEqual(self.request('/api/state',cookie=cookie)[0],401)
    def test_monthly_preview_and_csv_permissions(self):
        month=dt.date.today().strftime('%Y-%m')
        query='?month='+month+'&kind=employees'
        self.assertEqual(self.request('/api/monthly'+query)[0],401)
        for name in ('worker','counter'):
            cookie,_=self.login(name)
            for route in ('/api/monthly','/api/monthly-export'):
                self.assertEqual(self.request(route+query,cookie=cookie)[0],400)
        cookie,_=self.login('boss')
        status,body,_=self.request('/api/monthly'+query,cookie=cookie)
        self.assertEqual(status,200);report=json.loads(body)
        from harvest.monthly import to_csv
        status,body,_=self.request('/api/monthly-export'+query,cookie=cookie)
        self.assertEqual(status,200);self.assertEqual(body,to_csv(report))
        self.assertEqual(self.request('/api/monthly?month=2026-99&kind=products',cookie=cookie)[0],400)

    def test_login_throttle(self):
        for _ in range(10):self.assertEqual(self.request('/api/login',{'username':'missing','password':'wrongPassword'})[0],401)
        self.assertEqual(self.request('/api/login',{'username':'missing','password':'wrongPassword'})[0],429)

    def test_audit_history_manager_only(self):
        self.assertEqual(self.request('/api/audit')[0],401)
        for name in ('worker','counter'):
            cookie,_=self.login(name)
            self.assertEqual(self.request('/api/audit',cookie=cookie)[0],400)
        cookie,_=self.login('boss')
        status,body,_=self.request('/api/audit?page=1',cookie=cookie)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['page_size'],50)
        self.assertEqual(self.request('/api/audit?page=bad',cookie=cookie)[0],400)

if __name__=='__main__':unittest.main()
