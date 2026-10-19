'use strict';
// Translate stored audit snapshots into business terms. Never infer missing old values.
function auditView(record, context) {
    const parse = (value, fallback) => { if (value == null) return fallback; if (typeof value !== 'string') return value; try { return JSON.parse(value) } catch { return fallback } };
    const d = parse(record.detail, {}), action = record.action;
    const userName = id => context.users?.find(u => u.id === Number(id))?.name || `员工 #${id}`;
    const lot = id => context.lots?.find(l => l.id === Number(id));
    const amount = value => value == null ? '未记录' : Number(value / 100).toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const hours = value => value == null ? '未记录' : `${Number((value / 60).toFixed(4))} 小时`;
    const val = value => value == null ? '未记录' : String(value);
    const roles = { manager: '经理', employee: '普通员工', checker: '点货员' };
    let title = action, subject = '', rows = [], note = '';
    const add = (label, before, after) => { if (before !== after) rows.push([label, before, after]) };
    if (action === '提交日报' || action === '修改日报') {
        subject = `${d.user_name || userName(d.user_id)} · ${d.date || '日期未记录'}`;
        const flatten = r => {
            if (!r) return null;
            const result = { '总工时': hours(r.minutes), '计时时薪': amount(r.rate) + ' / 小时', '当天总金额': amount(r.amount) };
            if (r.minutes) result['平均每小时产值'] = amount(r.amount * 60 / r.minutes) + ' / 小时';
            for (const p of parse(r.pieces, [])) {
                const name = (p.product || '产品') + (!p.process && p.stage === 'semi' ? '（半成品 · ' + p.unit + '）' : '');
                result[name + ' / 数量'] = `${p.quantity} ${p.unit || ''}`;
                result[name + ' / 单价'] = amount(p.price) + ' / ' + (p.unit || '件');
            }
            parse(r.timed, []).forEach((t, i) => { result[`计时工作 ${i + 1} / 时长`] = hours(t.minutes); result[`计时工作 ${i + 1} / 备注`] = val(t.memo) });
            return result;
        };
        const before = flatten(d.before), after = flatten(d.after);
        for (const key of new Set([...Object.keys(before || {}), ...Object.keys(after || {})])) add(key, before?.[key] ?? (action === '提交日报' ? '未填写' : before ? '无此项目' : '未记录'), after?.[key] ?? (after ? '已移除' : '未记录'));
    } else if (action === 'user_delete') {
        title = '删除用户'; subject = `${d.before.name}（${d.before.username}）`;
        rows.push(['账号状态', '可登录', '已删除，无法登录']); note = '历史工作记录和核算数据保留，原登录会话已失效。';
    } else if (action === 'workflow') {
        title = '创建产品流程'; subject = d.name;
        rows.push(['启用日期','未创建',d.start_date]);
        for (const p of d.steps || []) rows.push([({harvest:'采摘',pack:'分包',seal:'封膜'})[p.process], '—', `${p.product} · ${amount(p.price)} / ${p.unit}`]);
    } else if (action === 'process_link') {
        title = '关联分装与封膜'; subject = d.source + ' → ' + d.target; rows.push(['关联', '未设置', subject], ['计量单位', '—', val(d.unit)], ['启用日期', '—', val(d.start_date)]);
    } else if (action === 'direct_sale') {
        title = d.before ? '修正未入库直售' : '登记未入库直售'; subject = `${d.product} · ${d.date}`;
        rows.push(['当天直接售出未入库', d.before ? `${d.before.quantity} ${d.unit || '盒'}` : '未登记', `${d.after.quantity} ${d.unit || '盒'}`]);
        add('售货说明', d.before?.memo || '未填写', d.after.memo);
    } else if (action === 'intake_count') {
        title = d.confirmed_unchanged ? '复点确认（数量不变）' : d.before ? '修正入库点货' : '提交入库点货'; subject = `${d.product} · ${d.date}`;
        rows.push([d.stage === 'semi' ? '当天半成品实点' : '当天实际入库', d.before ? `${d.before.actual} ${d.unit || '盒'}` : '未点货', `${d.after.actual} ${d.unit || '盒'}`]);
        rows.push(['核对时员工提交', '—', `${d.expected} ${d.unit || '盒'}`]);
    } else if (['product', 'product_delete'].includes(action)) {
        title = action === 'product_delete' ? '停用产品' : d.before ? '调整产品单价' : '添加产品'; subject = d.after?.product || d.before?.product || '产品';
        if (action === 'product_delete') rows.push(['状态', '启用', '停用（历史记录保留）']);
        else {
            const fields=[['product','产品 / 工序'],['price','计件单价'],['start_date','启用日期'],['unit','计量单位'],...(d.after.process?[['process','工序'],['parent_id','上一道工序']]:[['stage','产品类型']])];
            const format=(obj,key)=>key==='price'?amount(obj?.[key]):key==='process'?({harvest:'采摘',pack:'分包',seal:'封膜'}[obj?.[key]]||'未记录'):key==='parent_id'?(obj?.[key]?context.products?.find(p=>p.id===obj[key])?.product||`项目 #${obj[key]}`:'无'):key==='stage'?(obj?.[key]==null?'未记录':obj[key]==='semi'?'半成品':'成品'):val(obj?.[key]);
            for(const [key,label] of fields)add(label,d.before?format(d.before,key):'未创建',format(d.after,key));
        }
    } else if (action === 'lot_delete') {
        title = '删除 Lot'; subject = d.before?.code || 'Lot'; rows.push(['Lot 状态', '可选', '已删除（历史记录保留）']);
    } else if (action === 'user' || action === 'lot') {
        const current = d.after || d, isNew = d.format === 2 ? d.before === null : !d.id;
        const old = d.before;
        title = action === 'user' ? (isNew ? '创建员工账号' : '修改员工资料') : (isNew ? '添加 Lot' : '调整 Lot 单价');
        subject = action === 'user' ? (current.name || userName(d.id)) : (current.code || lot(d.id)?.code || `Lot #${d.id}`);
        const fields = action === 'user' ? [['name', '姓名'], ['username', '登录账号'], ['role', '角色'], ['rate', '计时时薪']] : [['code', 'Lot number'], ['product', '产品'], ['unit', '计量单位'], ['per_box', '每盒蘑菇数量'], ['price', '计件单价'], ['opening', '起始库存'], ['start_date', '起始库存日期']];
        const format = (obj, key) => obj?.[key] == null ? '未记录' : key === 'rate' || key === 'price' ? amount(Number(obj[key]) * (d.format === 2 ? 1 : 100)) + (key === 'rate' ? ' / 小时' : '') : key === 'role' ? (roles[obj[key]] || obj[key]) : val(obj[key]);
        for (const [key, label] of fields) if (current[key] != null) add(label, isNew ? '未创建' : format(old, key), format(current, key));
        if (d.password_reset) add('登录密码', '已设置（不显示密码）', '已重设，原登录会话已失效');
        if (!isNew && !old) note = '这条旧记录未保存修改前的数据，原值无法还原。';
    } else if (['shipment', 'shipment_void', 'count'].includes(action)) {
        const lid = d.lot_id || d.before?.lot_id, l = lot(lid), unit = d.unit || l?.unit || '件';
        const date = d.date || d.after?.date || d.before?.date || '日期未记录';
        subject = `${d.lot_code || l?.code || 'Lot #' + lid} · ${d.product || l?.product || ''} · ${date}`;
        if (action === 'count') {
            title = '登记库存盘点';
            add('实际盘点数量', d.before ? `${d.before.actual} ${unit}` : d.format === 2 ? '未盘点' : '未记录', `${d.after?.actual ?? d.actual} ${unit}`);
            if (d.expected != null) { rows.push(['盘点时应有库存', '—', `${d.expected} ${unit}`]); const diff = (d.after?.actual ?? d.actual) - d.expected; rows.push(['盘点结果', '—', diff === 0 ? '核对通过' : `差额 ${diff > 0 ? '+' : ''}${diff} ${unit}`]) }
            if (!d.format) note = '这条旧记录未保存上一次盘点值和当时的应有库存。';
        } else if (action === 'shipment') {
            title = '登记出库'; const r = d.after || d; rows.push(['出库数量', '未登记', `${r.quantity} ${unit}`], ['出库说明', '未填写', val(r.memo)]);
        } else {
            title = '撤销出库'; rows.push(['出库数量', `${d.before?.quantity ?? '未记录'} ${unit}`, '已撤销'], ['出库说明', val(d.before?.memo), '已撤销']);
        }
    } else { subject = '历史操作'; note = '该历史操作类型暂不支持逐项对照。' }
    if (!rows.length) rows.push(['记录内容', '无字段变化', '无字段变化']);
    return { actor: d.actor_name || record.name, title, subject, rows, reason: d.reason || '', note };
}
