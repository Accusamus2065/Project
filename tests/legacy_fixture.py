"""Build pre-workflow data to verify backward compatibility without using new creation API."""
def product(db, data):
    db.execute('INSERT INTO products(product,stage,unit,price,start_date) VALUES(?,?,?,?,?)',
        (data['product'],data.get('stage','finished'),data.get('unit','筐' if data.get('stage')=='semi' else '盒'),round(data['price']*100),data['start_date']))

    db.commit()
