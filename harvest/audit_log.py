"""Read-only, manager-only historical audit browsing."""
import datetime as dt
from . import core


def browse(db, user, query):
    core.manager(user)
    page = core.number(query.get('page', '1'), '页码', minimum=1, maximum=10000000)
    anchor = core.number(query.get('anchor', db.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]), '查询范围')
    clauses, params = ['a.id<=?'], [anchor]
    bounds = {}
    for key, op in (('start', '>='), ('end', '<')):
        if query.get(key):
            try:
                value = dt.datetime.fromisoformat(query[key])
                if value.tzinfo is None: raise ValueError()
                value = value.astimezone(dt.timezone.utc)
            except (ValueError, TypeError, OverflowError):
                raise core.RuleError('操作日期无效')
            bounds[key] = value
            clauses.append('a.at'+op+'?'); params.append(value.isoformat())
    if len(bounds)==2 and bounds['start'] >= bounds['end']:
        raise core.RuleError('开始日期不能晚于结束日期')
    if query.get('actor'):
        clauses.append('a.actor=?');params.append(core.number(query['actor'],'操作人',minimum=1))
    if query.get('action'):
        clauses.append('a.action=?');params.append(core.text(query['action'],'操作类型',80))
    where = ' AND '.join(clauses)
    total = db.execute('SELECT COUNT(*) FROM audit a WHERE '+where, params).fetchone()[0]
    pages = max(1, (total+49)//50);page=min(page,pages)
    rows = [dict(r) for r in db.execute(
        'SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.actor WHERE '+where+
        ' ORDER BY a.id DESC LIMIT 50 OFFSET ?', (*params,(page-1)*50))]
    return dict(rows=rows,total=total,page=page,pages=pages,page_size=50,anchor=anchor,
        actors=[dict(r) for r in db.execute('SELECT DISTINCT u.id,u.name,u.username FROM users u JOIN audit a ON a.actor=u.id ORDER BY u.name,u.id')],
        actions=[r[0] for r in db.execute('SELECT DISTINCT action FROM audit ORDER BY action')])
