"""Production lot traceability, independent of physical intake reconciliation."""
import json
from . import core


def search(db, user, lot):
    core.manager(user)
    lot = core.canonical_lot(core.text(lot, 'Lot number', 80))
    rows, groups = [], {}
    for report in db.execute('SELECT r.*,u.name,u.username FROM reports r JOIN users u ON u.id=r.user_id ORDER BY r.date DESC,r.id DESC'):
        for piece in json.loads(report['pieces']):
            if piece.get('stage','finished') != 'finished' or core.canonical_lot(piece.get('lot_number', '')) != lot:
                continue
            row = dict(date=report['date'], report_id=report['id'], employee=report['name'],
                       username=report['username'], product_id=piece['product_id'],
                       product=piece['product'], unit=piece['unit'], quantity=piece['quantity'])
            rows.append(row)
            key = (piece['product_id'],piece['unit'])
            group = groups.setdefault(key,dict(product=piece['product'],unit=piece['unit'],quantity=0))
            group['quantity'] += piece['quantity']
    if not rows and not (lot.isascii() and lot.isalnum()):
        raise core.RuleError('批号只能包含连续的英文字母和数字，不能含空格或符号')
    return dict(lot_number=lot, rows=rows, products=list(groups.values()))


def catalog(db, user):
    """Group recorded production quantities by finished product, unit and lot."""
    core.manager(user)
    products = {}
    for report in db.execute('SELECT pieces FROM reports ORDER BY date DESC, id DESC'):
        for piece in json.loads(report['pieces']):
            lot = core.canonical_lot(piece.get('lot_number', ''))
            if not lot or piece.get('stage', 'finished') != 'finished':
                continue
            key = (piece['product_id'], piece['unit'])
            if key not in products:
                products[key] = dict(product=piece['product'], unit=piece['unit'], lots={})
            quantities = products[key]['lots']
            quantities[lot] = quantities.get(lot, 0) + piece['quantity']
    return {'products': [
        dict(product=item['product'], unit=item['unit'], lots=[
            dict(number=number, quantity=quantity) for number, quantity in item['lots'].items()
        ]) for item in products.values()
    ]}
