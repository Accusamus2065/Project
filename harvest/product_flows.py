"""Ordered, named product steps. Existing work items remain the unit of reporting."""
import json
import datetime as dt
from . import core


def initialize(db):
    columns = {r['name'] for r in db.execute('PRAGMA table_info(products)')}
    for name, definition in [('step_name', 'TEXT'), ('step_order', 'INTEGER')]:
        if name not in columns:
            db.execute(f'ALTER TABLE products ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS product_flows(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, start_date TEXT NOT NULL,
        steps TEXT NOT NULL, check_source INTEGER REFERENCES products(id),
        version INTEGER NOT NULL DEFAULT 1)''')
    db.execute('''CREATE TABLE IF NOT EXISTS imported_flows(kind TEXT NOT NULL, old_id INTEGER NOT NULL,
        PRIMARY KEY(kind,old_id));''')
    columns={r['name'] for r in db.execute('PRAGMA table_info(product_flows)')}
    if 'check_start' not in columns:
        db.execute('ALTER TABLE product_flows ADD COLUMN check_start TEXT')
    db.execute('CREATE TABLE IF NOT EXISTS historical_flow_checks(source INTEGER NOT NULL REFERENCES products(id), target INTEGER NOT NULL REFERENCES products(id), start_date TEXT NOT NULL, end_date TEXT NOT NULL)')
    sync_legacy(db)


def sync_legacy(db):
    """Import once without altering old reports or the legacy reconciliation rules."""
    def add(kind, key, name, start, ids, check=None):
        if db.execute('SELECT 1 FROM imported_flows WHERE kind=? AND old_id=?', (kind,key)).fetchone():
            return
        db.execute('INSERT INTO product_flows(name,start_date,steps,check_source) VALUES(?,?,?,?)',
                   (name,start,json.dumps(ids),check))
        db.execute('INSERT INTO imported_flows VALUES(?,?)',(kind,key))
        for pos, pid in enumerate(ids, 1):
            p = db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
            label = p['product'].rsplit('·',1)[1] if '·' in p['product'] else {'harvest':'采摘','pack':'分包','seal':'封膜'}.get(p['process'], '完成')
            db.execute('UPDATE products SET step_order=COALESCE(step_order,?),step_name=COALESCE(step_name,?) WHERE id=?',(pos,label,pid))
    for w in db.execute('SELECT * FROM product_workflows').fetchall():
        add('workflow',w['id'],w['name'],w['start_date'],[w['harvest_id'],w['pack_id'],w['seal_id']],w['pack_id'])
    covered = {pid for f in db.execute('SELECT steps FROM product_flows') for pid in json.loads(f[0])}
    handled={r[0] for r in db.execute("SELECT old_id FROM imported_flows WHERE kind='edited_product'")}
    for p in db.execute("SELECT * FROM products WHERE process='seal' AND family_name IS NOT NULL").fetchall():
        if p['id'] in covered or p['id'] in handled:
            continue
        ids=[p['id']]; current=p
        while current['parent_id'] and current['parent_id'] not in ids:
            current=db.execute('SELECT * FROM products WHERE id=?',(current['parent_id'],)).fetchone()
            if not current: break
            ids.insert(0,current['id'])
        if len(ids)<=3:
            add('chain',p['id'],p['family_name'],p['start_date'],ids,ids[-2] if len(ids)>1 else None)
            covered.update(ids)
    for l in db.execute('SELECT * FROM process_links').fetchall():
        if l['target_id'] not in covered and l['target_id'] not in handled:
            p=db.execute('SELECT * FROM products WHERE id=?',(l['target_id'],)).fetchone()
            add('link',l['id'],core.finished_name(dict(p)),l['start_date'],[l['source_id'],l['target_id']],l['source_id'])
            covered.update([l['source_id'],l['target_id']])
    for p in db.execute('SELECT * FROM products').fetchall():
        if p['id'] not in covered and p['id'] not in handled and not p['deleted']:
            add('product',p['id'],p['family_name'] or p['product'],p['start_date'],[p['id']])


def listing(db):
    return [{**dict(f),'steps':json.loads(f['steps'])} for f in db.execute('SELECT * FROM product_flows ORDER BY name,id')]


def used(db, pid):
    return bool(db.execute('SELECT 1 FROM intake_counts WHERE product_id=? UNION SELECT 1 FROM direct_sales WHERE product_id=?',(pid,pid)).fetchone()) or any(
        any(p['product_id']==pid for p in json.loads(r[0])) for r in db.execute('SELECT pieces FROM reports'))


def save(db,user,data):
    core.manager(user)
    name=core.text(data.get('name'),'成品名称',80)
    start=core.date(data.get('start_date'))
    steps=data.get('steps')
    if not isinstance(steps,list) or not 1<=len(steps)<=3:
        raise core.RuleError('请选择 1–3 道工序')
    old=db.execute('SELECT * FROM product_flows WHERE id=?',(data.get('id'),)).fetchone() if data.get('id') else None
    if data.get('id') and not old: raise core.RuleError('产品流程不存在')
    if old and data.get('version')!=old['version']: raise core.RuleError('产品已被修改，请刷新后再编辑')
    old_ids=json.loads(old['steps']) if old else []
    if old and start!=old['start_date'] and any(used(db,pid) for pid in old_ids):
        raise core.RuleError('已有工作记录的产品不能修改启用日期')
    before=dict(old) if old else None
    if before:
        before['steps']=[dict(db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()) for pid in old_ids]
    db.execute('SAVEPOINT product_flow')
    try:
        chosen=[]
        for pos,value in enumerate(steps,1):
            if not isinstance(value,dict): raise core.RuleError('工序设置无效')
            stage='finished' if pos==len(steps) else 'semi'
            mode=value.get('mode')
            p=db.execute('SELECT * FROM products WHERE id=?',(value.get('id'),)).fetchone() if value.get('id') else None
            if mode=='existing':
                if not p or p['deleted'] or p['step_order']!=pos or p['stage']!=stage:
                    raise core.RuleError('只能引用相同序号、相同成品/半成品类型且启用中的工序')
                if p['start_date']>start: raise core.RuleError('启用日期不能早于引用工序')
                chosen.append(p['id']); continue
            if mode not in ('new','edit') or (mode=='edit' and (not p or p['id'] not in old_ids or p['deleted'])):
                raise core.RuleError('工序设置无效，请刷新后重试')
            label=core.text(value.get('name'),'工序名称',40)
            unit=core.text(value.get('unit'),'单位',12)
            price=core.number(value.get('price'),'计件单价',100)
            full=name+'·'+label
            duplicate=db.execute('SELECT id FROM products WHERE product=? AND unit=?',(full,unit)).fetchone()
            if duplicate and (mode!='edit' or duplicate['id']!=p['id']):
                raise core.RuleError(full+'已存在，请引用已有工序或使用不同名称')
            if mode=='edit':
                structural=p['unit']!=unit or p['stage']!=stage or p['step_order']!=pos
                shared=any(p['id'] in json.loads(f['steps']) for f in db.execute('SELECT steps FROM product_flows WHERE id!=?',(old['id'],)))
                if shared and (structural or p['product']!=full or p['price']!=price or p['start_date']!=start):
                    raise core.RuleError('此工序被其他产品共用；请保留引用，或选择新建工序，避免改变其他产品')
                if structural and used(db,p['id']):
                    raise core.RuleError('此工序已有生产记录，不能改变单位、顺序或成品类型；请选择新建工序并使用不同名称，历史记录会保留')
                db.execute('UPDATE products SET product=?,unit=?,stage=?,price=?,family_name=?,step_name=?,step_order=?,start_date=? WHERE id=?',
                    (full,unit,stage,price,name,label,pos,start,p['id']))
                chosen.append(p['id'])
            else:
                chosen.append(db.execute('INSERT INTO products(product,unit,stage,price,start_date,family_name,step_name,step_order) VALUES(?,?,?,?,?,?,?,?)',
                    (full,unit,stage,price,start,name,label,pos)).lastrowid)
        if len(set(chosen))!=len(chosen): raise core.RuleError('同一流程不能重复引用同一道工序')
        source_pos=data.get('check_source')
        source=None
        if source_pos is not None:
            source_pos=core.number(source_pos,'核对工序',minimum=1,maximum=len(chosen)-1)
            source=chosen[source_pos-1]
            units=[db.execute('SELECT unit FROM products WHERE id=?',(pid,)).fetchone()[0] for pid in (source,chosen[-1])]
            if units[0]!=units[1]: raise core.RuleError('自动数量核对的两道工序必须使用相同单位')
        if old:
            db.executemany("INSERT OR IGNORE INTO imported_flows VALUES('edited_product',?)",[(pid,) for pid in old_ids])
            old_source=old['check_source']
            changed_check=old_source!=source or old_ids[-1]!=chosen[-1]
            check_start=old['check_start'] or old['start_date']
            if changed_check:
                today=dt.date.today().isoformat()
                yesterday=(dt.date.today()-dt.timedelta(days=1)).isoformat()
                if old_source and check_start<=yesterday:
                    db.execute('INSERT INTO historical_flow_checks VALUES(?,?,?,?)',(old_source,old_ids[-1],check_start,yesterday))
                check_start=today
            # Remove legacy implicit checks for this flow. The new optional setting owns them.
            db.execute('DELETE FROM product_workflows WHERE harvest_id IN (SELECT value FROM json_each(?)) AND pack_id IN (SELECT value FROM json_each(?)) AND seal_id IN (SELECT value FROM json_each(?))',(json.dumps(old_ids),)*3)
            for a,b in zip(old_ids,old_ids[1:]):
                db.execute('DELETE FROM process_links WHERE source_id=? AND target_id=?',(a,b))
            db.execute('UPDATE product_flows SET name=?,start_date=?,steps=?,check_source=?,check_start=?,version=version+1 WHERE id=?',(name,start,json.dumps(chosen),source,check_start,old['id']))
            fid=old['id']
            for pid in set(old_ids)-set(chosen):
                if not any(pid in json.loads(f[0]) for f in db.execute('SELECT steps FROM product_flows WHERE id!=?',(fid,))):
                    db.execute('UPDATE products SET deleted=1 WHERE id=?',(pid,))
        else:
            fid=db.execute('INSERT INTO product_flows(name,start_date,steps,check_source) VALUES(?,?,?,?)',(name,start,json.dumps(chosen),source)).lastrowid
        core.audit(db,user['id'],'product_flow',{'before':before,'after':{'id':fid,'name':name,'steps':[dict(db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()) for pid in chosen],'check_source':source,'start_date':start}})
        db.execute('RELEASE product_flow')
        return {'ok':True,'id':fid}
    except Exception:
        db.execute('ROLLBACK TO product_flow');db.execute('RELEASE product_flow');raise


def edges(db,day):
    current=[(f['check_source'],json.loads(f['steps'])[-1]) for f in db.execute('SELECT * FROM product_flows WHERE check_source IS NOT NULL AND start_date<=? AND COALESCE(check_start,start_date)<=?',(day,day))]
    return current+[tuple(r) for r in db.execute('SELECT source,target FROM historical_flow_checks WHERE start_date<=? AND end_date>=?',(day,day))]
