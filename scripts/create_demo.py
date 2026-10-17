"""Create a fresh demo database; refuses to overwrite any existing database."""
import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harvest import core

path=Path(sys.argv[1] if len(sys.argv)>1 else 'data/fresh-demo.sqlite3')
if path.exists():
    raise SystemExit('Target exists; choose a new demo filename.')
core.initialize(path)
today=dt.date.today(); start=today.replace(day=1).isoformat()
with core.connect(path) as db:
    hashed=core.password_hash('Harvest2026!')
    for username,name,role,rate in [('manager','陈经理','manager',2000),('employee','林晓','employee',1760),('employee2','王明','employee',1850),('checker','李点货','checker',0)]:
        db.execute('INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)',(username,name,role,rate,hashed))
    boss,worker,sealer,checker=db.execute('SELECT * FROM users ORDER BY id').fetchall()
    def create(name,harvest=None):
        steps={k:dict(mode='new',name=name,unit='筐' if k=='harvest' else '盒',price=5 if k=='harvest' else .65 if k=='pack' else .35) for k in ('harvest','pack','seal')}
        if harvest:steps['harvest']=dict(mode='existing',id=harvest)
        result=core.mutate(db,boss,'workflow',dict(name=name,start_date=start,steps=steps))
        return dict(db.execute('SELECT * FROM product_workflows WHERE id=?',(result['id'],)).fetchone())
    a=create('3lb 香菇');b=create('6lb 香菇',a['harvest_id']);c=create('150g 金针菇')
    for days_ago in (2,1,0):
        day=(today-dt.timedelta(days=days_ago)).isoformat()
        if day<start:continue
        packed=[(a['pack_id'],100-days_ago*10),(b['pack_id'],40),(c['pack_id'],80)]
        harvested=[(a['harvest_id'],20),(c['harvest_id'],12)]
        sealed=[(a['seal_id'],100-days_ago*10),(b['seal_id'],40),(c['seal_id'],80 if days_ago else 78)]
        for who,items in [(worker,harvested+packed),(sealer,sealed)]:
            core.mutate(db,who,'report',dict(date=day,piece_hours=6.5,timed=[dict(hours=1.5,memo='整理工作台、清洁设备')],pieces=[dict(product_id=pid,quantity=n) for pid,n in items]))
        for r in core.inventory(db,day):
            if r['stage'] != 'finished':continue
            if days_ago==0 and r['id']==c['harvest_id']:continue
            direct=10 if r['id']==a['seal_id'] else 0
            if r['stage']=='finished':
                core.mutate(db,boss,'direct_sale',dict(date=day,product_id=r['id'],quantity=direct,memo='演示：当天生产未入库直售' if direct else '无直售',version=0))
            actual=r['expected']-direct-(2 if days_ago==0 and r['id']==c['pack_id'] else 0)
            core.mutate(db,checker,'intake_count',dict(date=day,product_id=r['id'],actual=actual,signature=r['signature'],version=r['version']))
print(path)
