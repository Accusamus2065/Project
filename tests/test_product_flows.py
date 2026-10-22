import datetime as dt
import json
import unittest
from tests import test_flexible_products
from harvest import core, product_flows, monthly


class ProductFlowTests(unittest.TestCase):
    setUp=test_flexible_products.FlexibleProducts.setUp
    tearDown=test_flexible_products.FlexibleProducts.tearDown
    act=test_flexible_products.FlexibleProducts.act
    report=test_flexible_products.FlexibleProducts.report

    def create(self,name,labels,check=None,steps=None,start=None,**kw):
        data=dict(name=name,start_date=start or self.day,steps=steps or [dict(mode='new',name=label,unit='盒',price='0.5') for label in labels],check_source=check,**kw)
        result=self.act(self.boss,'product_flow',**data)
        return next(f for f in product_flows.listing(self.db) if f['id']==result['id'])

    def editing(self,flow):
        return [dict(mode='edit',id=pid,name=p['step_name'],unit=p['unit'],price=p['price']/100) for pid in flow['steps'] for p in [self.db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()]]

    def test_audit_preserves_old_step_price_and_name(self):
        flow=self.create('旧产品',['包装'])
        steps=self.editing(flow)
        steps[0].update(name='采摘包装',price=2)
        self.create('新产品',[],steps=steps,id=flow['id'],version=flow['version'])
        detail=json.loads(self.db.execute("SELECT detail FROM audit WHERE action='product_flow' ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(detail['before']['steps'][0]['product'],'旧产品·包装')
        self.assertEqual(detail['before']['steps'][0]['price'],50)
        self.assertEqual(detail['after']['steps'][0]['product'],'新产品·采摘包装')
        self.assertEqual(detail['after']['steps'][0]['price'],200)

    def test_one_two_three_steps_and_custom_names(self):
        for name,labels in [('150g香菇',['采摘','分装','封膜']),('180g平菇',['采摘分装','封膜']),('3lbmini',['采摘','剪根后']),('2lb平菇',['采摘包装'])]:
            f=self.create(name,labels)
            rows=[dict(self.db.execute('SELECT * FROM products WHERE id=?',(i,)).fetchone()) for i in f['steps']]
            self.assertEqual([p['product'] for p in rows],[name+'·'+s for s in labels])
            self.assertEqual([p['stage'] for p in rows],['semi']*(len(labels)-1)+['finished'])
            self.assertEqual([p['step_order'] for p in rows],list(range(1,len(labels)+1)))
        self.assertEqual(core.process_checks(self.db,self.day),[])

    def test_optional_check_shared_work_and_monthly(self):
        a=self.create('180g平菇',['采摘分装','封膜'],check=1)
        b=self.create('200g平菇',[],check=1,steps=[dict(mode='existing',id=a['steps'][0]),dict(mode='new',name='封膜',unit='盒',price=1)])
        self.report(self.worker,[(a['steps'][0],100),(a['steps'][1],40),(b['steps'][1],60)])
        c=core.process_checks(self.db,self.day)
        self.assertEqual(len(c),1)
        self.assertEqual((c[0]['packed'],c[0]['sealed'],c[0]['difference']),(100,100,0))
        self.assertEqual(len(core.state(self.db,self.boss,self.day)['inventory']),2)
        m=monthly.build(self.db,self.boss,self.day[:7],'employees')
        self.assertIn('采摘分装',str(m['rows']))
        production=monthly.build(self.db,self.boss,self.day[:7],'products')
        self.assertEqual(sum(r[production['columns'].index('员工报数合计')] for r in production['rows']),100)

    def test_validation_atomicity_and_permissions(self):
        a=self.create('测试',['第一','第二','第三'])
        count=self.db.execute('SELECT COUNT(*) FROM products').fetchone()[0]
        for steps,check in [([dict(mode='existing',id=a['steps'][1]),dict(mode='new',name='末道',unit='盒',price=1)],None),
            ([dict(mode='new',name='前道',unit='筐',price=1),dict(mode='new',name='末道',unit='盒',price=1)],1),
            ([dict(mode='existing',id=a['steps'][0])],None)]:
            with self.assertRaises(core.RuleError): self.create('失败',[],steps=steps,check=check)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM products').fetchone()[0],count)
        with self.assertRaises(core.RuleError):self.act(self.worker,'product_flow',name='非法',steps=[],start_date=self.day)

    def test_edit_preserves_report_snapshot_and_optimistic_version(self):
        f=self.create('mini',['采摘','剪根后'])
        self.report(self.worker,[(f['steps'][0],20),(f['steps'][1],10)])
        before=self.db.execute('SELECT pieces,amount FROM reports').fetchone()
        steps=self.editing(f);steps[0]['name']='采收';steps[0]['price']=2
        edited=self.create('3lbmini',[],steps=steps,id=f['id'],version=f['version'])
        self.assertEqual(tuple(self.db.execute('SELECT pieces,amount FROM reports').fetchone()),tuple(before))
        self.assertEqual(edited['steps'],f['steps'])
        self.assertEqual(json.loads(before['pieces'])[0]['step_order'],1)
        with self.assertRaises(core.RuleError):self.create('旧页面',[],steps=steps,id=f['id'],version=f['version'])
        steps=self.editing(edited);steps[0]['unit']='筐'
        with self.assertRaises(core.RuleError):self.create('3lbmini',[],steps=steps,id=f['id'],version=edited['version'])

    def test_change_step_count_before_use_and_check_toggle_history(self):
        yesterday=(dt.date.today()-dt.timedelta(days=1)).isoformat()
        f=self.create('小包装',['采摘','分装','封膜'],check=2,start=yesterday)
        edited=self.create(f['name'],[],steps=self.editing(f),id=f['id'],version=f['version'],start=yesterday)
        self.assertEqual(core.process_checks(self.db,self.day),[])
        self.assertEqual(len(core.process_checks(self.db,yesterday)),1)
        steps=self.editing(edited)[:2]
        edited=self.create(f['name'],[],steps=steps,id=f['id'],version=edited['version'],start=yesterday)
        self.assertEqual(len(edited['steps']),2)
        self.assertEqual(self.db.execute('SELECT stage FROM products WHERE id=?',(edited['steps'][-1],)).fetchone()[0],'finished')
        self.assertEqual(self.db.execute('SELECT deleted FROM products WHERE id=?',(f['steps'][-1],)).fetchone()[0],1)

    def test_shared_step_cannot_be_silently_changed(self):
        f=self.create('180',['采摘','封膜'])
        self.create('200',[],steps=[dict(mode='existing',id=f['steps'][0]),dict(mode='new',name='封膜',price=1,unit='盒')])
        steps=self.editing(f);steps[0]['price']=3
        with self.assertRaisesRegex(core.RuleError,'共用'):self.create(f['name'],[],steps=steps,id=f['id'],version=f['version'])

    def test_shared_step_start_date_is_protected(self):
        f=self.create('180',['采摘','封膜'])
        self.create('200',[],steps=[dict(mode='existing',id=f['steps'][0]),dict(mode='new',name='封膜',price=1,unit='盒')])
        yesterday=(dt.date.today()-dt.timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(core.RuleError,'共用'):
            self.create(f['name'],[],steps=self.editing(f),id=f['id'],version=f['version'],start=yesterday)

    def test_restart_is_idempotent_and_does_not_revive_checks(self):
        f=self.create('香菇',['采摘','分装','封膜'],check=2)
        f=self.create(f['name'],[],steps=self.editing(f),id=f['id'],version=f['version'])
        before=product_flows.listing(self.db)
        self.db.commit();core.initialize(self.path);core.initialize(self.path)
        self.assertEqual(product_flows.listing(self.db),before)
        self.assertEqual(core.process_checks(self.db,self.day),[])

    def test_legacy_flow_edit_cannot_reappear_after_restart(self):
        old=self.act(self.boss,'workflow',name='旧流程',start_date=self.day,steps={k:dict(mode='new',name='旧流程',unit='盒',price=1) for k in ('harvest','pack','seal')})
        self.db.commit();core.initialize(self.path)
        f=next(f for f in product_flows.listing(self.db) if f['name']=='旧流程')
        # Replace the final legacy sealing step with a newly named finished step.
        steps=self.editing(f)[:2]+[dict(mode='new',name='装箱完成',unit='盒',price=1)]
        self.create(f['name'],[],steps=steps,id=f['id'],version=f['version'])
        before=product_flows.listing(self.db)
        self.db.commit();core.initialize(self.path);core.initialize(self.path)
        self.assertEqual(product_flows.listing(self.db),before)
        self.assertEqual(core.process_checks(self.db,self.day),[])
