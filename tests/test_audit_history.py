import unittest
from tests import test_core
from harvest import core, audit_log

class AuditHistory(unittest.TestCase):
    setUp=test_core.BusinessRules.setUp
    tearDown=test_core.BusinessRules.tearDown

    def seed(self):
        for i in range(125):
            self.db.execute('INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)',
                ('2026-10-01T00:30:00+00:00' if i<50 else '2026-10-01T14:00:00+00:00',
                 self.worker['id'] if i%2 else self.boss['id'],'提交日报' if i%3 else '修改日报','{}'))
        self.db.commit()

    def test_pagination_keeps_history_and_stable_pages(self):
        self.seed();first=audit_log.browse(self.db,self.boss,{})
        self.assertEqual((first['total'],len(first['rows']),first['pages']),(125,50,3))
        core.audit(self.db,self.boss['id'],'user',{})
        second=audit_log.browse(self.db,self.boss,dict(page='2',anchor=first['anchor']))
        third=audit_log.browse(self.db,self.boss,dict(page='3',anchor=first['anchor']))
        ids=[r['id'] for result in (first,second,third) for r in result['rows']]
        self.assertEqual(len(set(ids)),125);self.assertEqual(ids[-1],1)
        self.assertEqual(audit_log.browse(self.db,self.boss,{})['total'],126)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],126)

    def test_filters_local_date_boundaries_and_access(self):
        self.seed()
        # Toronto Sept 30 includes early UTC Oct 1; end boundary is exclusive.
        result=audit_log.browse(self.db,self.boss,dict(start='2026-09-30T04:00:00Z',end='2026-10-01T04:00:00Z'))
        self.assertEqual(result['total'],50)
        result=audit_log.browse(self.db,self.boss,dict(actor=str(self.worker['id']),action='修改日报'))
        self.assertTrue(result['rows'])
        self.assertTrue(all(r['actor']==self.worker['id'] and r['action']=='修改日报' for r in result['rows']))
        self.assertEqual(audit_log.browse(self.db,self.boss,dict(action='不存在'))['rows'],[])
        for actor in (self.worker,self.counter):
            with self.assertRaises(core.RuleError):audit_log.browse(self.db,actor,{})
        for query in ({'page':'-1'},{'page':'1.5'},{'start':'bad'}, {'start':'2026-10-01T00:00:00'},
            {'start':'2026-10-02T00:00:00Z','end':'2026-10-01T00:00:00Z'}):
            with self.assertRaises(core.RuleError):audit_log.browse(self.db,self.boss,query)

    def test_toronto_calendar_dates_and_dst(self):
        self.seed()
        self.assertEqual(audit_log.browse(self.db,self.boss,dict(start='2026-09-30',end='2026-09-30'))['total'],50)
        self.db.execute('DELETE FROM audit')
        for stamp in ['2026-11-01T03:59:59+00:00','2026-11-01T04:00:00+00:00',
                      '2026-11-02T04:59:59+00:00','2026-11-02T05:00:00+00:00']:
            self.db.execute('INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)',
                            (stamp,self.boss['id'],'test','{}'))
        rows=audit_log.browse(self.db,self.boss,dict(start='2026-11-01',end='2026-11-01'))['rows']
        self.assertEqual(len(rows),2)
        with self.assertRaises(core.RuleError):
            audit_log.browse(self.db,self.boss,dict(start='2026-11-02',end='2026-11-01'))
