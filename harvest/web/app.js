'use strict';
const app = document.querySelector('#app'), modal = document.querySelector('#modal');
let state, page = 'entry', draft = null;
const dayDrafts = new Map();
let dateRequest = 0;
const localDate = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` };
let day = localDate();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cash = n => new Intl.NumberFormat('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n / 100);
function businessTime(value) {
 return new Date(value).toLocaleString('zh-CN', {timeZone:'America/Toronto', hour12:false});
}
function storageSize(value) {
 if (value == null) return '待检查';
 if (value < 1000) return value + ' B';
 if (value < 1000000) return (value / 1000).toFixed(1) + ' KB';
 return (value / 1000000).toFixed(1) + ' MB';
}
const statusNames = { passed: '核对通过', pending: '待点货', mismatch: '数量有差异', stale: '需重新核对', na: '无需核对', recorded: '已提交' };
const badge = s => `<span class="badge ${esc(s)}">${statusNames[s] || esc(s)}</span>`;
function notify(message) { const n = document.querySelector('#notice'); n.textContent = message; n.classList.add('show'); clearTimeout(notify.timer); notify.timer = setTimeout(() => n.classList.remove('show'), 4500) }
async function api(path, data) { const requestSession = state?.csrf; const res = await fetch('/api/' + path, { method: data ? 'POST' : 'GET', headers: data ? { 'Content-Type': 'application/json', 'X-CSRF-Token': state?.csrf || '' } : {}, body: data ? JSON.stringify(data) : undefined }).catch(() => { throw new Error('网络连接失败，请检查网络后重试') }); const value = await res.json().catch(() => { throw new Error('服务器返回异常，请刷新后重试') }); if (!res.ok) { if (res.status === 401 && path !== 'login' && state?.csrf === requestSession) { state = null; draft = null; dayDrafts.clear(); dateRequest++; modal.close(); login() } throw new Error(value.error || '请求失败') } return value }
async function refresh(resetPage = false) {
 const requestedDay = day, request = ++dateRequest, userId = state?.user.id;
 const nextState = await api('state?date=' + requestedDay);
 if (request !== dateRequest || day !== requestedDay || state?.user.id !== userId) return;
 state = nextState;
 if (resetPage) { page = state.user.role === 'manager' ? 'overview' : state.user.role === 'checker' ? 'inventory' : 'entry'; draft = null; dayDrafts.clear() }
 render();
}
async function refreshAfterSave(message) { try { await refresh(); notify(message) } catch (err) { render(); notify(message + '，但页面刷新失败：' + err.message) } }
function login() { app.innerHTML = `<div class="login"><aside class="login-aside"><div class="brand"><img src="/nebo-logo.webp" alt="NEBO Mushrooms"></div><h1>员工生产工作台</h1><p>每天的产量、工时与入库，<br>在这里清晰记录。</p><div class="login-rule">生产记录 &nbsp; / &nbsp; 工时管理 &nbsp; / &nbsp; 入库核对</div></aside><main class="login-main"><form class="login-box" id="login-form"><div class="eyebrow">员工登录</div><h1>欢迎回来</h1><p class="muted">登录账号，开始今天的工作。</p><label>账号<input name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><div class="error" id="login-error" role="alert"></div><button class="primary">登录工作台 →</button><footer class="login-credits"><span>© ${new Date().getFullYear()} <a href="https://nebomushrooms.com/" target="_blank" rel="noopener noreferrer">NEBO Mushrooms</a> 版权所有</span><span>由 <a href="https://www.linkedin.com/in/accusamus/" target="_blank" rel="noopener noreferrer">Yibin</a> 制作</span></footer></form></main></div>`; document.querySelector('#login-form').onsubmit = async e => { e.preventDefault(); const b = e.target.querySelector('button'); b.disabled = true; try { await api('login', Object.fromEntries(new FormData(e.target))); await refresh(true) } catch (err) { const error = document.querySelector('#login-error'); if (error) error.textContent = err.message; else notify(err.message) } finally { b.disabled = false } } }
const navItems = [['entry', '＋', '工作录入'], ['overview', '▦', '每日总览'], ['inventory', '▤', '入库核对'], ['lots', '▧', '产品与单价'], ['users', '♙', '员工管理'], ['exports', '↓', '月度导出'], ['backups', '▣', '备份状态'], ['audit', '≡', '操作记录']];
function navIcon(id) {
    const paths = { entry: '<path d="M12 5v14M5 12h14"/>', overview: '<path d="M4 19V5M4 19h16M9 15v-4M14 15V7M19 15v-7"/>', inventory: '<path d="m3 7 9-4 9 4v10l-9 4-9-4Z M3 7l9 4 9-4M12 11v10"/>', lots: '<path d="M3 11V4h7l11 11-7 7Z"/><circle cx="7.5" cy="8" r="1"/>', users: '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v2"/>', exports: '<path d="M12 3v15m-6-6 6 6 6-6M5 21h14"/>', backups: '<path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>', audit: '<path d="M7 3h10v4H7zM7 5H4v16h16V5h-3M8 12h8M8 16h6"/>' };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[id]}</svg>`;
}
function render() {
    if (!state) return login(); const manager = state.user.role === 'manager', checker = state.user.role === 'checker', employeePages = state.user.can_count ? ['entry', 'overview', 'inventory'] : ['entry', 'overview']; if (checker) page = 'inventory'; else if (!manager && !employeePages.includes(page)) page = 'entry'; app.innerHTML = `<div class="app"><aside class="sidebar"><div class="brand"><img src="/nebo-logo.webp" alt="NEBO Mushrooms"><div>NEBO<small>MUSHROOMS</small></div></div><div class="navlabel">工作空间</div><nav class="nav">${navItems.filter(([id]) => manager || (checker ? id === 'inventory' : employeePages.includes(id))).map(([id, icon, label]) => `<button data-page="${id}" class="${page === id ? 'active' : ''}"><span class="nav-icon" aria-hidden="true">${navIcon(id)}</span>${id === 'entry' && draft?.version ? '修改工作记录' : !manager && id === 'overview' ? '我的记录' : label}</button>`).join('')}</nav><div class="sidebar-bottom"><div class="identity"><span class="avatar" role="img" aria-label="${esc(state.user.name)}" title="${esc(state.user.name)}">${esc(Array.from(state.user.name.trim())[0]?.toLocaleUpperCase() || '用')}</span><div><strong>${esc(state.user.name)}</strong><small>${manager ? '经理' : checker ? '点货员' : '员工'} · 已登录</small><small class="identity-account">账号：${esc(state.user.username)}</small></div></div></div></aside><div class="workspace"><header class="topbar"><span>生产管理 &nbsp; / &nbsp; ${esc(page === 'entry' && draft?.version ? '修改工作记录' : navItems.find(n => n[0] === page)?.[2])}</span><div class="toolbar"><button class="quiet" id="logout">退出登录</button></div></header><main class="content" id="content"></main></div></div>`;
    document.querySelectorAll('[data-page]').forEach(b => b.onclick = () => { captureDraft(); page = b.dataset.page; render() }); document.querySelector('#logout').onclick = async () => { try { await api('logout', {}); state = null; draft = null; dayDrafts.clear(); dateRequest++; login() } catch (e) { notify(e.message) } };
    ({ entry: entry, overview: overview, inventory: inventory, lots: lots, users: users, exports: monthlyExports, backups: backups, audit: audit })[page]();
    bindDate();
}
function bindDate() {
 const input = document.querySelector('#work-date');
 if (input) input.onchange = async () => {
  if (!input.value || !input.reportValidity()) { input.value = day; input.setCustomValidity(''); notify('请选择有效的工作日期，不能晚于今天'); return }
  const nextDay = input.value;
  if (nextDay === day) return;
  captureDraft();
  if (draft) dayDrafts.set(day, draft);
  const request = ++dateRequest, userId = state.user.id;
  input.disabled = true;
  try { const nextState = await api('state?date=' + encodeURIComponent(nextDay)); if (request !== dateRequest || state?.user.id !== userId) return; day = nextDay; draft = dayDrafts.get(day) || null; state = nextState; render() }
  catch (e) { input.value = day; input.disabled = false; notify(e.message) }
 };
}
function heading(title, subtitle, action = '') { return `<div class="heading"><div><div class="eyebrow">${state.user.role === 'manager' ? 'NEBO / 经理工作台' : state.user.role === 'checker' ? 'NEBO / 当天点货' : 'NEBO / 我的工作'}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="date-control">${['users', 'lots', 'audit', 'exports', 'backups'].includes(page) ? '' : `<input aria-label="工作日期" id="work-date" type="date" value="${day}" max="${localDate()}">`}${action}</div></div>` }
const content = html => { document.querySelector('#content').innerHTML = html; queueMicrotask(enhanceLotPickers); };
const processNames={harvest:'采摘',pack:'分包',seal:'封膜'};
const stageName=p=>p.step_name||processNames[p.process]||(p.stage==='semi'?'半成品':'成品');
const productLabel=p=>`${p.product}（${p.unit}）`;
const stageBadge=p=>'';
const lotOptions = (id, unique = false) => `<option value="">选择产品</option>` + sortedReportPieces(state.products).filter(l => l.start_date <= day && (!l.deleted || (unique && draft?.version && draft.prices?.[l.id] != null)) && (!unique || Number(id) === l.id || !draft.pieces.some(p => Number(p.product_id) === l.id))).map(l => `<option value="${l.id}" ${Number(id) === l.id ? 'selected' : ''}>${esc(productLabel(l))}</option>`).join('');
// Keep the native select as the form value; render an anchored, keyboard-accessible picker.
let closeLotPicker = null;
let lotPickerSequence = 0;
function enhanceLotPickers() {
    document.querySelectorAll('select').forEach(select => {
        if (select._syncPicker) { select._syncPicker(); return; }
        const isPiece = !!select.closest('.piece-data');
        const fieldLabel = select.getAttribute('aria-label') || select.closest('label')?.childNodes[0]?.textContent?.trim() || '请选择';
        const wrapper = document.createElement('span'); wrapper.className = isPiece ? 'lot-picker' : 'lot-picker standard-picker';
        select.before(wrapper); wrapper.append(select); select.classList.add('picker-native'); select.tabIndex = -1; select.setAttribute('aria-hidden','true');
        const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'lot-trigger';
        trigger.setAttribute('role', 'combobox'); trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.setAttribute('aria-label', fieldLabel);
        const label = document.createElement('span'); label.className = 'lot-trigger-label'; trigger.append(label);
        const arrow = document.createElement('span'); arrow.className = 'lot-chevron'; arrow.setAttribute('aria-hidden', 'true'); trigger.append(arrow);
        const list = document.createElement('div'); list.className = 'lot-menu'; list.id = 'lot-menu-' + (++lotPickerSequence);
        list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', fieldLabel); list.hidden = true;
        trigger.setAttribute('aria-controls', list.id); wrapper.append(trigger, list);
        let choices=[], options=[], active=-1, open=false, search='', searchAt=0, optionHTML='';
        function sync() {
            wrapper.hidden=select.hidden; trigger.disabled=select.disabled;
            trigger.setAttribute('aria-required',String(select.required));
            label.textContent=select.selectedOptions[0]?.textContent || '请选择';
            trigger.classList.toggle('placeholder',select.required && !select.value);
            const signature=String(select.required)+select.innerHTML;
            if(optionHTML!==signature || !options.length) {
                optionHTML=signature; list.replaceChildren();
                choices=[...select.options].filter(o=>!o.disabled && (!select.required || o.value));
                options=choices.map((choice,index)=>{
                    const item=document.createElement('div');item.className='lot-option';item.id=list.id+'-'+index;
                    item.setAttribute('role','option');item.textContent=choice.textContent;
                    item.onpointerdown=e=>e.preventDefault();item.onclick=()=>choose(index);list.append(item);return item;
                });
                if(!options.length){const empty=document.createElement('div');empty.className='lot-empty';empty.textContent='暂无可选项目';list.append(empty)}
            }
            options.forEach((o,i)=>o.setAttribute('aria-selected',String(choices[i].value===select.value)));
            if(select.hidden||select.disabled)close();
        }
        select._syncPicker=sync;
        function highlight(index) { active = index; options.forEach((o, i) => o.classList.toggle('active', i === active)); if (options[active]) { trigger.setAttribute('aria-activedescendant', options[active].id); options[active].scrollIntoView({ block: 'nearest' }) } }
        function close() { open = false; list.hidden = true; trigger.setAttribute('aria-expanded', 'false'); trigger.removeAttribute('aria-activedescendant'); if (closeLotPicker === close) closeLotPicker = null }
        function show() { sync(); if (open || select.disabled || select.hidden) return; closeLotPicker?.(); open = true; list.hidden = false; trigger.setAttribute('aria-expanded', 'true'); closeLotPicker = close; highlight(Math.max(0, choices.findIndex(o => o.value === select.value))) }
        function choose(index) {
            if(!choices[index])return;
            select.value=choices[index].value;select.setCustomValidity('');trigger.removeAttribute('aria-invalid');sync();close();trigger.focus();
            select.dispatchEvent(new Event('change',{bubbles:true}));
            if(isPiece){const rowIndex=[...document.querySelectorAll('.piece-data select')].indexOf(select);entry();document.querySelectorAll('.piece-data .lot-trigger')[rowIndex]?.focus()}
            else enhanceLotPickers();
        }
        trigger.onclick = () => open ? close() : show();
        trigger.onkeydown = e => {
            if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); close(); return }
            if (e.key === 'Tab') { close(); return }
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
                e.preventDefault(); if (!open) { show(); if (e.key === 'Home') highlight(0); if (e.key === 'End') highlight(options.length - 1) }
                else highlight(e.key === 'Home' ? 0 : e.key === 'End' ? options.length - 1 : Math.max(0, Math.min(options.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)))); return;
            }
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (open) choose(active); else show(); return }
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); const now = Date.now(); search = (now - searchAt > 700 ? '' : search) + e.key.toLowerCase(); searchAt = now; show(); const i = choices.findIndex(o => o.textContent.toLowerCase().startsWith(search)); if (i >= 0) highlight(i) }
        };
        wrapper.addEventListener('focusout', e => { if (!wrapper.contains(e.relatedTarget)) close() });
        select.addEventListener('invalid', e => { e.preventDefault(); trigger.setAttribute('aria-invalid', 'true'); trigger.focus(); show(); notify('请选择'+fieldLabel) });
        sync();
    });
}
document.addEventListener('pointerdown', e => { if (!e.target.closest('.lot-picker')) closeLotPicker?.() });
function newDraft() { return { user_id: state.user.id, hours: '', pieces: [], timed: [] } }
function captureDraft() { const form = document.querySelector('#entry-form'); if (!form) return; draft = { ...draft, hours: form.elements.hours.value, pieces: [...form.querySelectorAll('.piece-data')].map((row, i) => ({ product_id: Number(row.querySelector('select').value) || '', snapshot_id: draft.pieces[i]?.product_id === Number(row.querySelector('select').value) ? draft.pieces[i]?.snapshot_id : undefined, quantity: row.querySelector('input').value })), timed: [...form.querySelectorAll('.time-data')].map(row => ({ hours: row.querySelector('input[type="number"]').value, memo: row.querySelector('input[type="text"]').value })), reason: form.elements.reason?.value || '' } }
function entry() {
    const existing = state.reports.find(r => r.user_id === state.user.id); if (!draft && existing) { content(heading('今天的记录已提交', '金额按提交时的单价计算。你可以在工作记录中修正填写内容。') + reportCard(existing) + `<button id="see-reports" class="primary">查看工作记录</button>`); document.querySelector('#see-reports').onclick = () => { page = 'overview'; render() }; return } draft = draft || newDraft(); const employee = state.users.find(u => u.id === draft.user_id) || state.user; const rate = draft.rate ?? employee.rate;
    content(heading(draft.version ? '修改工作记录' : '记录今天的工作', `${esc(employee.name)} · 当天总工时包含计件工作和计时工作。`) + `<div class="grid"><form id="entry-form"><section class="card"><div class="card-head"><div><h2><span class="step">01</span>计件工作</h2><p>选择工作项目，填写完成数量。</p></div><small>按产品单价计算</small></div>${draft.pieces.length ? '<div class="piece-row row-head"><span>产品 / 规格</span><span>数量</span><span class="amount">金额</span><span></span></div>' : ''}${draft.pieces.map((p, i) => { const l = state.products.find(l => l.id === Number(p.product_id)); return `<div class="piece-row piece-data"><span class="mobile-piece-title">计件项目 ${i + 1}</span><div><select aria-label="第 ${i + 1} 项产品" required>${lotOptions(p.product_id, true)}</select><small class="lot-rate">${l ? `${cash(draft.snapshotPrices?.[p.snapshot_id] ?? draft.prices?.[l.id] ?? l.price)} / ${esc(l.unit)}` : '请选择产品'}</small></div><label class="piece-quantity"><span class="mobile-field-label">数量</span><input aria-label="第 ${i + 1} 项数量" inputmode="numeric" type="number" min="1" max="10000000" step="1" value="${esc(p.quantity)}" required></label><span class="amount line-amount">0.00</span><button class="remove" type="button" data-remove-piece="${i}" aria-label="移除计件项">×</button></div>` }).join('')}<button class="add" type="button" id="add-piece" aria-label="添加计件工作">＋ 添加</button></section><section class="card"><div class="card-head"><div><h2><span class="step">02</span>计时工作</h2><p>没有计时工作可跳过。</p></div><small>${cash(rate)} / 小时</small></div>${draft.timed.map((t, i) => `<div class="time-row time-data"><label>小时数<input type="number" inputmode="decimal" min="0.05" max="24" step="0.05" value="${esc(t.hours)}" required></label><label><span id="time-label-${i}">工作备注</span><input aria-labelledby="time-label-${i}" type="text" maxlength="500" placeholder="例如：接种、上包。" value="${esc(t.memo)}" required></label><button class="remove" type="button" data-remove-time="${i}" aria-label="移除计时项">×</button></div>`).join('')}<button class="add" type="button" id="add-time" aria-label="添加计时工作">＋ 添加</button></section><section class="card"><h2><span class="step">03</span>当天总工时</h2><div class="hours-equation"><label>计件工时（小时）<input name="hours" type="number" inputmode="decimal" min="0" max="24" step="0.05"  value="${esc(draft.hours)}"></label><span class="hours-plus" aria-hidden="true">＋</span><div class="hours-auto"><span>计时工时（自动汇总）</span><output id="timed-hours" aria-live="polite">0 小时</output></div></div><div class="hours-result">当天总工时 <output id="total-hours" aria-live="polite">0 小时</output></div><div class="hint">只填写计件工作的时长，上方计时工作自动相加。仅做计时工作时可留空。</div>${draft.version ? `<label class="full">修改原因<input name="reason" maxlength="500" value="${esc(draft.reason)}" required placeholder="填写原因"></label>` : ''}<div id="entry-error" class="error" role="alert"></div></section></form><aside class="card summary" id="entry-summary" tabindex="-1"><div class="summary-label">当天工作产值</div><div class="big-money" id="sum-total">0.00</div><dl><div><dt>计件金额</dt><dd id="sum-pieces">0.00</dd></div><div><dt>计时金额</dt><dd id="sum-time">0.00</dd></div><div><dt>总工时</dt><dd id="sum-hours">—</dd></div></dl><hr><div class="summary-label">平均每小时产值</div><div class="efficiency"><strong id="sum-efficiency">—</strong><small>/ 小时</small></div><div class="summary-result" id="sum-reference"></div><div class="summary-actions"><button class="primary" type="submit" form="entry-form">${draft.version ? '保存修正' : '提交今日记录'} →</button>${draft.version ? '<button class="summary-secondary" type="button" id="cancel-edit">取消修改</button>' : ''}</div><p class="summary-note">${draft.version ? '原有产品和计时工作保留提交时价格。' : '提交后保存当时单价。入库核对结果可在工作记录中查看。'}</p></aside><div class="mobile-submitbar"><div><small>当天产值 / 总工时</small><strong id="mobile-total">0.00 <span> / —</span></strong></div><button type="button" class="primary" id="review-summary">核对并提交</button></div></div>`);
    document.querySelector('#add-piece').onclick = () => { captureDraft(); draft.pieces.push({ product_id: '', quantity: '' }); entry(); document.querySelector('.piece-data:last-of-type .lot-trigger')?.focus() }; document.querySelector('#add-time').onclick = () => { captureDraft(); draft.timed.push({ hours: '', memo: '' }); entry(); document.querySelector('.time-data:last-of-type input')?.focus() }; document.querySelectorAll('[data-remove-piece]').forEach(b => b.onclick = () => { captureDraft(); draft.pieces.splice(+b.dataset.removePiece, 1); entry() }); document.querySelectorAll('[data-remove-time]').forEach(b => b.onclick = () => { captureDraft(); draft.timed.splice(+b.dataset.removeTime, 1); entry() }); document.querySelector('#cancel-edit')?.addEventListener('click', () => { dayDrafts.delete(day); draft = null; page = 'overview'; render() });
    const form = document.querySelector('#entry-form'); form.oninput = form.onchange = () => { document.querySelector('#entry-error').textContent = ''; calculate() }; form.onsubmit = saveWorkRecord; document.querySelector('#review-summary').onclick = reviewWorkRecord; enhanceLotPickers(); calculate(); bindDate();
}

function reviewWorkRecord() {
 const form = document.querySelector('#entry-form');
 if (!form.reportValidity()) return;
 captureDraft();
 if (!draft.pieces.length && !draft.timed.length) { notify('请先添加计件或计时工作'); return; }
 const lines = draft.pieces.map(p => `<li>${esc(state.products.find(x=>x.id===+p.product_id)?.product)}<strong>${esc(p.quantity)} ${esc(state.products.find(x=>x.id===+p.product_id)?.unit)}</strong></li>`).join('');
 showModal('确认工作记录', `<p class="muted">${esc(day)} · ${esc((state.users.find(u=>u.id===draft.user_id)||state.user).name)}</p><ul class="submit-review">${lines}${draft.timed.map(t=>`<li>${esc(t.memo)}<strong>${esc(t.hours)} 小时</strong></li>`).join('')}</ul><div class="review-totals"><div><small>总工时</small><strong>${esc(document.querySelector('#sum-hours').textContent)}</strong></div><div><small>总产值</small><strong>${esc(document.querySelector('#sum-total').textContent)}</strong></div></div><div class="form-actions"><button id="review-back">继续修改</button><button class="primary" id="review-confirm">确认提交</button></div>`);
 document.querySelector('#review-back').onclick=()=>modal.close();
 document.querySelector('#review-confirm').onclick=()=>{modal.close();form.requestSubmit()};
}
async function saveWorkRecord(e) {
 e.preventDefault();
 const form = e.currentTarget;
 if (form.dataset.saving) return;
 captureDraft();
 const savedDay = day, userId = state.user.id, submitted = { ...draft };
 const button = document.querySelector('button[form="entry-form"]');
 form.dataset.saving = 'true'; button.disabled = true;
 try {
  await api('report', { ...submitted, piece_hours: submitted.hours || 0, date: savedDay });
  if (state?.user.id !== userId) return;
  dayDrafts.delete(savedDay);
  if (day !== savedDay || (draft && draft.user_id !== submitted.user_id)) {
   notify(savedDay + ' 的工作记录已保存'); return;
  }
  draft = null; page = 'overview'; await refreshAfterSave('工作记录已保存');
 } catch (err) {
  const error = form.isConnected ? form.querySelector('#entry-error') : null;
  if (error) { error.textContent = err.message; error.scrollIntoView({ block: 'center', behavior: 'smooth' }) }
  else notify(err.message);
 } finally { delete form.dataset.saving; button.disabled = false; }
}

function validInputNumber(input) { return input && input.value !== '' && input.validity.valid && Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : 0 }
function calculate() { captureDraft(); let pieces = 0; document.querySelectorAll('.piece-data').forEach((row, i) => { const p = draft.pieces[i], lot = state.products.find(l => l.id === +p.product_id), price = lot ? (draft.snapshotPrices?.[p.snapshot_id] ?? draft.prices?.[lot.id] ?? lot.price) : 0; const amount = price * validInputNumber(row.querySelector('input[type=number]')); pieces += amount; row.querySelector('.line-amount').textContent = cash(amount); row.querySelector('.lot-rate').textContent = lot ? `${cash(price)} / ${lot.unit}` : '请选择产品' }); const user = state.users.find(u => u.id === draft.user_id) || state.user, rate = draft.rate ?? user.rate; const timedMinutes = [...document.querySelectorAll('.time-data input[type=number]')].reduce((a, input) => a + Math.round(validInputNumber(input) * 60), 0); const time = Math.round(timedMinutes * rate / 60); const total = pieces + time, hours = (Math.round(validInputNumber(document.querySelector('#entry-form [name=hours]')) * 60) + timedMinutes) / 60; document.querySelector('#timed-hours').textContent = `${Number((timedMinutes / 60).toFixed(2))} 小时`; document.querySelector('#total-hours').textContent = `${Number(hours.toFixed(2))} 小时`; document.querySelector('#sum-total').textContent = cash(total); document.querySelector('#sum-pieces').textContent = cash(pieces); document.querySelector('#sum-time').textContent = cash(time); document.querySelector('#sum-hours').textContent = hours ? `${Number(hours.toFixed(2))} 小时` : '—'; document.querySelector('#sum-efficiency').textContent = hours ? cash(total / hours) : '—'; document.querySelector('#mobile-total').innerHTML = `${cash(total)} <span>/ ${Number(hours.toFixed(2))} 小时</span>`; document.querySelector('#sum-reference').textContent = hours ? `个人计时时薪参考：${cash(rate)} / 小时` : '' }
function compareProducts(a, b) {
    const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });
    const order = { harvest: 0, pack: 1, seal: 2 };
    const key = p => {
        const suffix = p.product.match(/·(采摘|分包|分装|封膜|封装)$/);
        const base = p.family_name || (p.step_name ? p.product.slice(0, -(p.step_name.length + 1)) : p.product.replace(/·(?:采摘|分包|分装|封膜|封装)$/, '')).trim();
        // Keep different package sizes of the same mushroom next to one another.
        const mushroom = base.replace(/^\d+(?:\.\d+)?\s*(?:kg|g|lbs?|oz|公斤|千克|克|磅)\s*/i, '').trim();
        return { base, mushroom, stage: p.step_order != null ? p.step_order - 1 : order[p.process] ?? ({采摘:0,分包:1,分装:1,封膜:2,封装:2}[suffix?.[1]] ?? 3) };
    };
    const x = key(a), y = key(b);
        return collator.compare(x.mushroom, y.mushroom)
            || collator.compare(x.base, y.base) || x.stage - y.stage;
}
function sortedReportPieces(pieces) { return [...pieces].sort(compareProducts) }
function reportCard(r) { return `<div class="card"><div class="card-head"><h2>${esc(r.name)} · ${esc(r.date)}</h2>${badge(r.status)}</div><div class="detail-list">${sortedReportPieces(r.pieces).map(p => `<div>${esc(p.product)} ${stageBadge(p)} &nbsp; ${p.quantity} ${esc(p.unit)} × ${cash(p.price)} = <strong>${cash(p.quantity * p.price)}</strong></div>`).join('')}${r.timed.map(t => `<div>${esc(t.memo)} &nbsp; ${t.minutes / 60} 小时 × ${cash(r.rate)}</div>`).join('')}<hr>总工时 ${r.minutes / 60} 小时 · 总金额 <strong>${cash(r.amount)}</strong> · 每小时产值 <strong>${cash(r.amount * 60 / r.minutes)}</strong></div></div>` }
function editReport(r) { draft = { user_id: r.user_id, hours: (r.minutes - r.timed.reduce((sum, t) => sum + t.minutes, 0)) / 60, rate: r.rate, version: r.version, snapshotPrices: Object.fromEntries(r.pieces.map(p => [p.snapshot_id, p.price])), prices: Object.fromEntries(r.pieces.map(p => [p.product_id, p.price])), pieces: r.pieces.map(p => ({ ...p })), timed: r.timed.map(t => ({ hours: t.minutes / 60, memo: t.memo })), reason: '' }; page = 'entry'; render() }
function backups() {
 content(heading('备份状态', '查看异地备份结果、执行安排与容量保护状态。') + backupPanel());
 const backupRefresh = document.querySelector('#backup-refresh'); if (backupRefresh) backupRefresh.onclick = async () => { backupRefresh.disabled = true; try { await refresh() } catch (err) { notify(err.message) } finally { backupRefresh.disabled = false } }; 
}
function backupPanel() {
 if (state.user.role !== 'manager') return '';
 const b = state.backup || {status: 'unavailable', message: '服务器尚未提供备份状态。若刚更新代码，请先重启本地服务，再点击刷新状态。此时无法确认备份是否启用或成功。'};
 const names = {unavailable: '状态暂不可用', ok: '备份已验证', pending: '等待首次备份', running: '正在备份', blocked: '已暂停上传', failed: '备份失败', stale: '需要检查', disabled: '未启用'};
 const date = value => value ? businessTime(value * 1000) : '暂无成功记录';
 const bytes = storageSize;
 return `<section class="backup-panel backup-${esc(b.status)}" aria-label="异地备份状态"><div class="backup-top"><div><h2>异地备份 <span class="backup-status">${esc(names[b.status] || '状态未知')}</span></h2></div><button class="quiet" id="backup-refresh">刷新状态</button></div><p>${esc(b.message)}</p><div class="backup-facts"><div><small>最近成功 · 多伦多时间</small><strong>${esc(date(b.last_success))}</strong></div><div><small>备份安排</small><strong>每天一次 · 保留 7 天</strong></div><div><small>桶内占用 / 保护上限</small><strong>${bytes(b.bucket_bytes)} / 4 GB</strong></div></div><details><summary>查看备份保护说明</summary><p>首次启动尝试备份，之后每天凌晨 3 点后检查执行。上传后回读校验；失败不会停止工作台。保留期限由 R2 的 daily/ 生命周期规则控制。</p><p>单份压缩备份最多 200 MB，本月上传 ${bytes(b.month_bytes)} / 2 GB。达到容量限制会暂停上传；月度额度下月恢复。这里是程序保护上限，并非云服务的费用硬上限。</p></details></section>`;
}
function overview() { const rows = state.reports, total = rows.reduce((a, r) => a + r.amount, 0), minutes = rows.reduce((a, r) => a + r.minutes, 0), manager = state.user.role === 'manager'; content(heading(manager ? '每日生产总览' : '我的工作记录', '查看当天产量、工时和入库核对进度。', '') + `<div class="stats"><div class="stat"><small>已提交记录</small><strong>${rows.length} <small>份</small></strong><small>${manager ? '按员工每天一份统计' : '当前日期'}</small></div><div class="stat"><small>工作总金额</small><strong>${cash(total)}</strong><small>计件 + 计时</small></div><div class="stat"><small>总工时</small><strong>${minutes / 60}</strong><small>小时</small></div><div class="stat"><small>平均每小时产值</small><strong>${minutes ? cash(total * 60 / minutes) : '—'}</strong><small>总金额 ÷ 总工时</small></div></div><section class="card ${manager ? '' : 'employee-history'}"><div class="card-head"><h2>${manager ? '员工工作记录' : '我的工作记录'}</h2><small>${day} · ${rows.length} 份记录</small></div>${!manager ? `<div class="mobile-report-cards">${rows.map(r => reportCard(r) + `<button data-edit="${r.id}" class="record-edit">修正工作记录</button>`).join('')}</div>` : ''}${rows.length ? `<div class="table-wrap"><table><thead><tr><th>员工</th><th>计件数量</th><th>总工时</th><th>总金额</th><th>每小时产值</th><th>入库核对</th><th></th></tr></thead><tbody>${rows.map(r => `<tr><td><strong>${esc(r.name)}</strong><small>${r.pieces.length} 种产品 · ${r.timed.length} 项计时</small></td><td>${esc(r.pieces.map(p => `${p.quantity} ${p.unit}`).join(' + ') || '—')}</td><td>${r.minutes / 60} 小时</td><td>${cash(r.amount)}</td><td><strong>${cash(r.amount * 60 / r.minutes)}</strong></td><td>${badge(r.status)}</td><td><button data-detail="${r.id}" class="quiet">明细</button><button data-edit="${r.id}" class="quiet">修正</button></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">这一天还没有工作记录。<br>在「工作录入」中提交第一份记录。</div>'}</section>`); document.querySelectorAll('[data-detail]').forEach(b => b.onclick = () => showModal('工作明细', reportCard(rows.find(r => r.id === +b.dataset.detail)))); document.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => { const r = rows.find(r => r.id === +b.dataset.edit); editReport(r) }) }
function showModal(title, html) { modal.classList.remove('workflow-builder'); modal.innerHTML = `<div class="modal-title"><h2>${title}</h2><button class="quiet" id="close-modal" aria-label="关闭">×</button></div>${html}`; document.querySelector('#close-modal').onclick = () => modal.close(); modal.showModal(); queueMicrotask(enhanceLotPickers) }
function formModal(title, fields, action, extra = {}) {
    showModal(title, `<form id="modal-form"><div class="form-grid">${fields}</div><div class="error" id="modal-error" role="alert"></div><div class="form-actions"><button class="primary" type="submit">保存</button></div></form>`);
    const form = document.querySelector('#modal-form'), error = form.querySelector('#modal-error');
    let saving = false;
    form.onsubmit = async e => {
        e.preventDefault();
        const button = form.querySelector('[type=submit]');
        if (saving || button.disabled) return;
        saving = true; button.disabled = true;
        try { await api(action, { ...Object.fromEntries(new FormData(form)), ...extra }) }
        catch (err) {
            if (form.isConnected && modal.open) error.textContent = err.message;
            else notify(err.message);
            saving = false; button.disabled = false; return;
        }
        if (form.isConnected) modal.close();
        try { await refresh(); notify('已保存') }
        catch (err) { notify('已保存，但页面刷新失败：' + err.message) }
    };
}
const field = (label, name, value = '', type = 'text', attrs = '', help = '') => `<label><span id="label-${name}">${label}</span><input aria-labelledby="label-${name}" name="${name}" type="${type}" value="${esc(value)}" ${attrs} ${help ? `aria-describedby="hint-${name}"` : ''} required>${help ? `<small class="field-help" id="hint-${name}">${esc(help)}</small>` : ''}</label>`;
function processPanel() {
    const checks = state.process_checks || [];
    if (!checks.length) return '';
    return `<details class="card process-summary"><summary>当天工序数量核对 <span>${checks.filter(r=>r.status==='passed').length} 组匹配 · ${checks.filter(r=>r.status==='mismatch').length} 组有差异</span></summary><p class="muted">所选前置工序与成品工序的当天合计应一致；共用工序按关联组汇总，每个工序只计算一次。差额 = 成品工序 − 前置工序，收工后应为 0。实际数量仍需独立点货。</p><div class="process-checks">${checks.map(r => `<article class="process-check"><div class="card-head"><div><h3>${esc(r.source)} → ${esc(r.target)}</h3><small>${day} · ${esc(r.unit)}</small></div><span class="badge ${r.status}">${r.status === 'pending' ? '尚无报数' : r.status === 'passed' ? '工序匹配' : '工序不匹配'}</span></div><p>前置工序 <strong>${r.packed}</strong> · 成品工序 <strong>${r.sealed}</strong> · 差额 <strong>${r.difference > 0 ? '+' : ''}${r.difference}</strong> ${esc(r.unit)}</p><details><summary>查看两道工序的员工明细</summary><p>前置工序：${r.packers.map(c => `${esc(c.name)} ${c.quantity} ${esc(r.unit)}`).join(' + ') || '尚无报数'}</p><p>成品工序：${r.sealers.map(c => `${esc(c.name)} ${c.quantity} ${esc(r.unit)}`).join(' + ') || '尚无报数'}</p></details></article>`).join('')}</div></details>`;
}
function intakeBadges(r) {
    const labels = [];
    if (r.has_difference) labels.push(badge('mismatch'));
    if (r.needs_recount) labels.push('<span class="badge stale">待复核</span>');
    if (r.missing_records?.length) labels.push(`<span class="badge pending">待提交：${esc(r.missing_records.join('、'))}</span>`);
    return labels.join(' ') || badge(r.status);
}
function openCount(r) {
    formModal((r.actual === null ? '填写点货' : '修改点货数量') + ' · ' + esc(r.product),
        `<p class="hint full">${day} · 只填当天累计实际入库数量，不填晚上剩余库存，不包含未入库直售。没有入库请填 0。</p>`
        + field('当天实际入库数量（' + esc(r.unit) + '）', 'actual', r.actual ?? '', 'number', 'min="0" max="10000000" step="1" inputmode="numeric"')
        + (r.actual !== null ? field('修改原因', 'reason', '', 'text', 'maxlength="500" placeholder="填写原因"', '请先核实实物，再说明数量调整的原因。') : ''),
        'intake_count', { date: day, product_id: r.id, version: r.version, signature: r.signature });
}
function confirmCount(r) {
    formModal('确认复点 · ' + esc(r.product), `<p class="hint full">请先重新清点或核实实物。此次确认当天实际入库仍为 <strong>${r.actual} ${esc(r.unit)}</strong>。这会记录复核人和时间；若数字仍不一致，数量差异会继续显示。</p>`
        + field('复核说明', 'reason', '', 'text', 'maxlength="500" placeholder="填写说明"', '例如：已重新清点，原数量正确。'),
        'intake_count', { date: day, product_id: r.id, version: r.version, signature: r.signature, confirm_unchanged: true });
    document.querySelector('#modal-form [type=submit]').textContent = '已复点，数量不变';
}
function openSale(r) {
    formModal((r.sales_recorded ? '修改直售' : '登记直售') + ' · ' + esc(r.product),
        `<p class="hint full">${day} · 只登记当天生产、直接售出且从未入库的成品。填写当天累计数量，不是本次新增数量。没有直售也请登记 0。${r.sales_recorded ? '保存后将替换原记录，请说明修改原因。' : '首次登记不需要修改原因。'}</p>`
        + field('当天未入库直售（' + esc(r.unit) + '）', 'quantity', r.sales_recorded ? r.direct_sold : '', 'number', 'min="0" max="10000000" step="1" inputmode="numeric"')
        + field('售货说明', 'memo', r.sales_memo, 'text', 'maxlength="500" placeholder="填写说明"', '例如：售货人、时间、单据号；无直售填“无”。')
        + (r.sales_recorded ? field('修改原因', 'reason', '', 'text', 'maxlength="500" placeholder="填写原因"', '例如：新增直售 10 盒，累计改为 20 盒。') : ''),
        'direct_sale', { date: day, product_id: r.id, version: r.sales_version });
}
function reconciliationSummary(r) {
 const issues=[];
 if(r.process_check?.difference) issues.push(`关联工序数量相差 ${Math.abs(r.process_check.difference)} ${r.unit}，请核实员工记录。`);
 if(r.actual!==null && r.sales_recorded && r.difference) issues.push(`实际入库比应入库${r.difference>0?'多':'少'} ${Math.abs(r.difference)} ${r.unit}，请核实点货和直售。`);
 if(r.needs_recount) issues.push('员工报数已变化，请点货员复点后确认。');
 if(r.missing_records?.length) issues.push('待补充：'+r.missing_records.join('、')+'。');
 return `<div class="reconcile-overview ${r.status==='passed'?'is-passed':''}"><strong>${r.status==='passed'?'数量已核对一致':'需要处理'}</strong>${issues.length?`<ul>${issues.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:'<p>生产报数和生产去向已匹配。</p>'}<small>修改后自动核对；复点确认需要先核实实物。</small></div>`;
}
function intakeDetails(r) {
    const check = r.process_check;
    const people = list => list.map(c => `<div class="recheck-person"><span>${esc(c.name)} · ${c.quantity} ${esc(r.unit)}</span><button data-recheck-report="${c.report_id}">修改工作记录</button></div>`).join('') || '<p class="muted">尚未提交，请员工填写工作记录。</p>';
    const recordMeta = (person, value) => {
        const stamp = value ? new Date(value) : null;
        const dateText = stamp ? stamp.toLocaleDateString('zh-CN') : '—';
        const timeText = stamp ? stamp.toLocaleTimeString('zh-CN', { hour12:false }) : '';
        return `<dl class="record-meta"><div><dt>操作人</dt><dd>${esc(person || '—')}</dd></div><div><dt>更新时间</dt><dd class="record-timestamp"><span>${esc(dateText)}</span><span>${esc(timeText)}</span></dd></div></dl>`;
    };
    const recordQuantity = (quantity, empty) => quantity === null ? `<p class="record-empty">${empty}</p>` : `<p class="record-quantity"><strong>${quantity}</strong><span>${esc(r.unit)}</span></p>`;
    showModal('核对详情 · ' + esc(r.product), `<div class="intake-statuses">${intakeBadges(r)}</div>
        ${reconciliationSummary(r)}
        <section class="reconcile-section"><h3>① 工序核对</h3>${check ? `<p>前置工序 ${check.packed} ${check.difference === 0 ? '=' : '≠'} 成品工序 ${check.sealed} ${esc(r.unit)}${check.difference ? ` · 相差 ${Math.abs(check.difference)} ${esc(r.unit)}` : check.packers.length && check.sealers.length ? ' · 数量一致' : ' · 工序记录尚未齐全'}</p>${check.target_ids.length > 1 || check.source_ids.length > 1 ? '<p class="muted">共用工序按关联组汇总，每道工序只计算一次。</p>' : ''}<h4>前置工序记录</h4>${people(check.packers)}<h4>成品工序记录</h4>${people(check.sealers)}` : `<p class="muted">此成品未设置自动工序数量核对，直接核对生产报数与入库。</p><h4>成品生产记录</h4>${people(r.contributors)}`}</section>
        <section class="reconcile-section"><h3>② 入库核对</h3>${!r.contributors.length ? '<p class="muted">成品生产记录尚未提交，暂不能确定应入库数量。</p>' : r.sales_recorded ? `<p>成品报数 ${r.expected} − 直售 ${r.direct_sold} = 应入库 ${r.expected_intake} ${esc(r.unit)}；实际入库 ${r.actual ?? '未填写'}${r.actual === null ? '' : ' ' + esc(r.unit)}。</p>${r.actual !== null ? `<p class="${r.difference ? 'reconcile-warning' : 'muted'}">${r.difference ? `实际入库${r.difference > 0 ? '多' : '少'} ${Math.abs(r.difference)} ${esc(r.unit)}` : '入库数量一致'}</p>` : ''}` : '<p class="muted">直售尚未登记，暂不能确定应入库数量。无直售请登记 0。</p>'}
        <div class="reconcile-record"><h4>直售记录</h4>${recordQuantity(r.sales_recorded ? r.direct_sold : null, '尚未登记')}${r.sales_recorded ? recordMeta(r.sales_recorder, r.sales_updated_at) + `<div class="record-memo"><span>售货说明</span><p>${esc(r.sales_memo || '—')}</p></div>` : ''}<div class="reconcile-actions"><button id="detail-sale">${r.sales_recorded ? '修改直售' : '登记直售'}</button></div></div>
        <div class="reconcile-record"><h4>点货记录</h4>${recordQuantity(r.actual, '尚未提交')}${r.actual !== null ? recordMeta(r.counter, r.updated_at) : ''}${r.needs_recount ? '<p class="record-alert">待复核：员工报数已变更，请重新核实点货数量。</p>' : ''}<div class="reconcile-actions"><button id="detail-count">${r.actual === null ? '填写点货' : '修改点货数量'}</button>${r.needs_recount ? '<button class="primary" id="detail-confirm">已复点，数量不变</button>' : ''}</div></div></section>`);
    document.querySelector('#detail-count').onclick = () => openCount(r);
    document.querySelector('#detail-sale').onclick = () => openSale(r);
    document.querySelector('#detail-confirm')?.addEventListener('click', () => confirmCount(r));
    document.querySelectorAll('[data-recheck-report]').forEach(button => button.onclick = () => {
        const report = state.reports.find(x => x.id === +button.dataset.recheckReport);
        if (report) { modal.close(); editReport(report) } else notify('记录已变化，请刷新页面');
    });
}
function inventory() {
    const manager = state.user.role === 'manager';
    const priority = r => r.has_difference ? 0 : r.needs_recount || r.status === 'stale' ? 1 : r.status === 'passed' ? 3 : 2;
    const rows = [...state.inventory].sort((a,b)=>priority(a)-priority(b)||compareProducts(a,b));
    content(heading(manager ? '当天入库核对' : '当天入库点货', manager ? '成品报数 − 未入库直售 = 实际入库；已关联的工序另按当天数量核对。' : '只清点当天累计实际入库的成品，不包含未入库直售，不填冷库剩余库存。')
        + (manager ? `<div class="stats"><div class="stat"><small>产品数</small><strong>${rows.length}</strong></div><div class="stat"><small>核对通过</small><strong>${rows.filter(r => r.status === 'passed').length}</strong></div><div class="stat"><small>存在差异</small><strong>${rows.filter(r => r.has_difference).length}</strong></div><div class="stat"><small>待提交 / 待复核</small><strong>${rows.filter(r => r.needs_recount || r.missing_records.length).length}</strong></div></div>` : '')
        + `<div class="intake-list intake-rows ${manager ? 'manager-intake' : 'checker-intake'}">${rows.map(r => `<section class="card intake-row"><div class="intake-identity"><small>成品 / ${esc(r.unit)}</small><h2>${esc(r.product)}</h2><div class="intake-statuses">${manager ? intakeBadges(r) : badge(r.status)}</div></div><div class="intake-metrics ${manager && !r.process_check ? 'without-process-check' : ''}">${manager ? `${r.process_check ? `<div><small>${r.process_check.target_ids.length > 1 ? '关联组报数' : '前置工序报数'}</small><strong>${r.process_check.packed}</strong></div>` : ''}<div><small>${r.process_check || r.process==='seal' ? '成品工序报数' : '成品报数'}</small><strong>${r.expected}</strong></div>` : ''}<div><small>实际入库</small><strong>${r.actual ?? '—'}</strong></div>${manager ? `<div><small>未入库直售</small><strong>${r.sales_recorded ? r.direct_sold : '未登记'}</strong></div><div><small>入库差额</small><strong class="${r.difference ? 'difference' : ''}">${r.actual === null || !r.sales_recorded ? '—' : r.difference > 0 ? '+' + r.difference : r.difference}</strong></div>` : ''}</div><div class="intake-actions">${manager ? `<button data-sale="${r.id}">${r.sales_recorded ? '修改直售' : '登记直售'}</button><button class="primary" data-contributors="${r.id}">核对详情</button>` : `<button class="primary" data-count="${r.id}">${r.actual === null ? '填写点货' : '修改点货数量'}</button>${r.status === 'stale' ? `<button data-confirm="${r.id}">已复点，数量不变</button>` : ''}`}</div><div class="intake-foot">${r.counter ? `${esc(r.counter)} · ${esc(businessTime(r.updated_at))}` : '尚未提交点货记录'}${(manager ? r.needs_recount : r.status === 'stale') ? ' · 员工报数已变更，请重新核实实物' : ''}</div></section>`).join('') || '<div class="card empty">当天没有可点货的成品。</div>'}</div>`);
    const list = document.querySelector('.intake-list');
    const passed = rows.filter(r=>r.status==='passed');
    if (passed.length) {
        const group = document.createElement('details'); group.className='passed-group';
        const summary = document.createElement('summary'); summary.textContent=`已完成 ${passed.length} 项 · 展开查看`; group.append(summary);
        const cards = [...list.children];
        rows.forEach((r,i)=>{if(r.status==='passed')group.append(cards[i])});
        list.append(group);
    }
    document.querySelectorAll('[data-count]').forEach(b => b.onclick = () => openCount(rows.find(r => r.id === +b.dataset.count)));
    document.querySelectorAll('[data-sale]').forEach(b => b.onclick = () => openSale(rows.find(r => r.id === +b.dataset.sale)));
    document.querySelectorAll('[data-contributors]').forEach(b => b.onclick = () => intakeDetails(rows.find(r => r.id === +b.dataset.contributors)));
    document.querySelectorAll('[data-confirm]').forEach(b => b.onclick = () => confirmCount(rows.find(r => r.id === +b.dataset.confirm)));
}
function lots() {
 const all=sortedReportPieces(state.products),active=all.filter(p=>!p.deleted),inactive=all.filter(p=>p.deleted);
 const flows=state.product_flows||[], covered=new Set(flows.flatMap(f=>f.steps));
 const stepCard=p=>`<article class="workflow-step product-step ${p.stage==='finished'?'is-finished':''}"><div class="product-step-top"><span class="step-number">${String(p.step_order||1).padStart(2,'0')}</span><span class="step-status">${p.stage==='finished'?'成品':'半成品'}${p.deleted?' · 已停用':''}</span></div><h3 title="${esc(p.product)}">${esc(p.step_name||p.product)}</h3><small class="step-fullname">${esc(p.product)}</small><div class="step-price"><strong>${cash(p.price)}</strong><span>/ ${esc(p.unit)}</span></div>${!p.deleted?`<button class="quiet danger step-disable" data-product-delete="${p.id}">停用工序</button>`:''}</article>`;
 const flowHTML=flows.filter(f=>f.steps.some(id=>active.some(p=>p.id===id))).map(f=>`<section class="card product-flow-card"><div class="card-head"><div><h2>${esc(f.name)}</h2><small>${f.steps.length} 道工序 · ${f.check_source?'已开启自动数量核对':'未开启自动数量核对'}</small></div><button data-flow-edit="${f.id}">编辑产品</button></div><div class="workflow-steps">${f.steps.map(id=>all.find(p=>p.id===id)).filter(Boolean).map(stepCard).join('')}</div>${f.check_source?`<div class="flow-reconcile"><span class="reconcile-icon">✓</span><div><strong>自动数量核对</strong><span>${esc(all.find(p=>p.id===f.check_source)?.step_name||all.find(p=>p.id===f.check_source)?.product)} <b>→</b> ${esc(all.find(p=>p.id===f.steps.at(-1))?.step_name||all.find(p=>p.id===f.steps.at(-1))?.product)}</span></div><span class="reconcile-ratio">当天数量 · 1:1</span></div>`:''}</section>`).join('');
 content(heading('产品与计件单价','按实际生产顺序设置 1–3 道工序；最后一道为成品，前面的工序为半成品。','<button class="primary" id="add-product">＋ 添加产品</button>')+flowHTML+
 active.filter(p=>!covered.has(p.id)).map(p=>`<section class="card"><div class="card-head"><h2>${esc(p.product)}</h2><button data-legacy-edit="${p.id}">编辑产品</button></div>${stepCard(p)}</section>`).join('')+
 (!active.length?'<section class="card empty">添加产品，设置工序名称、单位和单价。</section>':'')+
 `<details class="card archived-products"><summary>已停用项目（${inactive.length}）</summary><div class="workflow-steps">${inactive.map(stepCard).join('')||'<p class="muted">暂无已停用项目。</p>'}</div></details>`);
 document.querySelector('#add-product').onclick=()=>workflowBuilder(active);
 document.querySelectorAll('[data-flow-edit]').forEach(b=>b.onclick=()=>workflowBuilder(active,flows.find(f=>f.id===+b.dataset.flowEdit)));
 document.querySelectorAll('[data-legacy-edit]').forEach(b=>b.onclick=()=>workflowBuilder(active,null,all.find(p=>p.id===+b.dataset.legacyEdit)));
 document.querySelectorAll('[data-product-delete]').forEach(b=>b.onclick=()=>{
  const p=all.find(p=>p.id===+b.dataset.productDelete);
  formModal('确认停用工序',`<p class="full">停用「<strong>${esc(p.product)}</strong>」后不能用于新录入，历史记录保留。请先停用后续工序。</p>`+field('请输入完整项目名称以确认','confirm_name','','text','autocomplete="off"'),'product_delete',{id:p.id});
  const form=document.querySelector('#modal-form'),save=form.querySelector('button');save.textContent='确认停用';save.classList.add('danger');save.disabled=true;form.elements.confirm_name.oninput=e=>{save.disabled=e.target.value!==p.product};
 });
}
function workflowBuilder(active, flow=null, legacy=null) {
 const all=state.products;
 const rowFrom=p=>({mode:p.deleted||(state.product_flows||[]).filter(f=>f.steps.includes(p.id)).length>1?'existing':'edit',id:p.id,name:p.step_name||p.product.split('·').at(-1),unit:p.unit,price:p.price/100});
 let rows=flow?flow.steps.map(id=>rowFrom(all.find(p=>p.id===id))):legacy?[{mode:'existing',id:legacy.id,name:legacy.step_name||'完成',unit:legacy.unit,price:legacy.price/100}]:[{mode:'new',name:'',unit:'盒',price:''}];
 showModal(flow?'编辑产品':'添加产品',`<form id="workflow-form"><div class="builder-intro">按生产顺序填写工序。最后一道生产成品，前面的工序只计工作量。</div><div class="builder-top">${field('成品名称','name',flow?.name||legacy?.product||'','text','maxlength="80"','例如：180g 平菇')}${field('启用日期','start_date',flow?.start_date||localDate(),'date',`max="${localDate()}"`)}<label>工序数量<select name="step_count">${[1,2,3].map(n=>`<option value="${n}" ${n===rows.length?'selected':''}>${n} 道工序</option>`).join('')}</select></label></div><div class="builder-section-title"><strong>生产工序</strong><span>按实际生产顺序排列</span></div><div class="builder-steps" id="flow-rows"></div><section class="flow-check"><label><input type="checkbox" name="check_enabled" ${flow?.check_source?'checked':''}> <span>自动核对工序数量 <small>可选</small></span></label><div id="flow-check-fields"></div><p class="muted">选择一道前置工序，与最后一道成品工序按当天总数 1:1 核对；两道工序需使用相同单位。实物入库仍需单独点货。</p></section><div id="workflow-error" class="error" role="alert"></div><div class="form-actions"><button type="button" id="builder-cancel">取消</button><button class="primary" type="submit">${flow?'保存修改':'添加产品'}</button></div></form>`);
 modal.classList.add('workflow-builder');
 const form=document.querySelector('#workflow-form'),el=name=>form.elements.namedItem(name);
 let checkSource=flow?.check_source?flow.steps.indexOf(flow.check_source)+1:Math.max(1,rows.length-1);
 const capture=()=>{rows=rows.map((r,i)=>({...r,mode:el(`mode_${i}`).value,id:+el(`id_${i}`)?.value||r.id,name:el(`name_${i}`).value,unit:el(`unit_${i}`).value,price:el(`price_${i}`).value}));if(el('check_source'))checkSource=+el('check_source').value;};
 const preview=()=>rows.forEach((r,i)=>{const existing=el(`mode_${i}`).value==='existing',p=all.find(p=>p.id===+el(`id_${i}`)?.value);form.querySelector(`[data-preview="${i}"]`).textContent=existing?(p?'引用：'+p.product:'选择已有同级工序，沿用其名称、单位和单价'):'显示名称：'+(el('name').value||'成品名称')+'·'+(el(`name_${i}`).value||'工序名称');});
 const draw=()=>{
  document.querySelector('#flow-rows').innerHTML=rows.map((r,i)=>{
   const isFinal=i===rows.length-1,stage=isFinal?'finished':'semi',existing=r.mode==='existing';
   const choices=active.filter(p=>p.step_order===i+1&&p.stage===stage);
   const referenced=all.find(p=>p.id===r.id), locked=existing;
   return `<section class="builder-row ${isFinal?'is-finished':''}"><div class="builder-stage"><span>0${i+1}</span><strong>${isFinal?'成品':'半成品'}</strong></div><label class="builder-mode">设置方式<select name="mode_${i}">${flow&&flow.steps.includes(r.id)?`<option value="edit" ${r.mode==='edit'?'selected':''}>编辑本工序</option>`:''}<option value="new" ${r.mode==='new'?'selected':''}>新建工序</option><option value="existing" ${existing?'selected':''}>选择已有同级工序</option></select></label><div class="builder-name"><label ${existing?'hidden':''}>工序名称<input name="name_${i}" value="${esc(r.name||'')}" maxlength="40" ${existing?'disabled':'required'} placeholder="例如：采摘分装"></label><label ${existing?'':'hidden'}>已有第 ${i+1} 道工序<select name="id_${i}" ${existing?'required':'disabled'}><option value="">请选择同级工序</option>${choices.map(p=>`<option value="${p.id}" ${p.id===r.id?'selected':''}>${esc(p.product)}（${esc(p.unit)}）</option>`).join('')}</select></label></div><label>单位<input name="unit_${i}" value="${esc(locked?referenced?.unit||'':r.unit)}" maxlength="12" required ${locked?'readonly':''}></label><label>计件单价<input name="price_${i}" value="${esc(locked?(referenced?referenced.price/100:''):r.price)}" type="number" min="0" step="0.01" required ${locked?'readonly':''}></label><small class="builder-preview" data-preview="${i}"></small></section>`;
  }).join('');
  el('check_enabled').disabled=rows.length===1;
  if(rows.length===1)el('check_enabled').checked=false;
  if(checkSource>=rows.length)checkSource=Math.max(1,rows.length-1);
  document.querySelector('#flow-check-fields').innerHTML=rows.length>1?`<label for="flow-check-source">前置工序</label><div class="flow-check-pair"><select id="flow-check-source" aria-label="前置工序" name="check_source">${rows.slice(0,-1).map((r,i)=>`<option value="${i+1}" ${checkSource===i+1?'selected':''}>第 ${i+1} 道工序</option>`).join('')}</select><span>与第 ${rows.length} 道工序的数量保持一致</span></div>`:'';
  document.querySelector('#flow-check-fields').hidden=!el('check_enabled').checked;
  rows.forEach((r,i)=>{
   el(`mode_${i}`).onchange=()=>{const mode=el(`mode_${i}`).value;capture();if(mode==='new'){rows[i]={mode:'new',name:rows[i].name,unit:rows[i].unit||'盒',price:rows[i].price};}draw();};
   el(`id_${i}`).onchange=()=>{capture();draw();};
   el(`name_${i}`).oninput=preview;
  });
  enhanceLotPickers();preview();
 };
 el('step_count').onchange=()=>{capture();const count=+el('step_count').value;checkSource=Math.max(1,count-1);rows=Array.from({length:count},(_,i)=>rows[i]||{mode:'new',name:'',unit:'盒',price:''});draw();};
 el('name').oninput=preview;
 el('check_enabled').onchange=()=>{document.querySelector('#flow-check-fields').hidden=!el('check_enabled').checked;};
 document.querySelector('#builder-cancel').onclick=()=>modal.close();
 draw();
 form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type="submit"]');if(button.disabled)return;capture();button.disabled=true;
  const steps=rows.map(r=>r.mode==='existing'?{mode:r.mode,id:r.id}:{mode:r.mode,...(r.mode==='edit'?{id:r.id}:{}),name:r.name,unit:r.unit,price:r.price});
  try{await api('product_flow',{...(flow?{id:flow.id,version:flow.version}:{}),name:el('name').value,start_date:el('start_date').value,steps,check_source:el('check_enabled').checked?+el('check_source').value:null});modal.close();await refreshAfterSave(flow?'产品已更新':'产品已添加');}
  catch(err){const error=document.querySelector('#workflow-error');if(error&&modal.open){error.textContent=err.message;error.scrollIntoView({block:'nearest'});}else notify(err.message);button.disabled=false;}
 };
}
function deleteUser(id) {
 const u = state.users.find(u => u.id === id);
 if (!u || u.deleted || id === state.user.id) return;
 formModal('删除用户', `<p class="full">确定删除「<strong>${esc(u.name)}</strong>」（${esc(u.username)}）吗？该账号将无法登录，现有会话会立即失效。历史工作记录、核算数据和操作记录保留。原登录账号不再用于新建用户。</p>` + field('请输入登录账号以确认删除', 'confirm_name', '', 'text', 'autocomplete="off"'), 'user_delete', {id});
 const form = document.querySelector('#modal-form'), button = form.querySelector('button');
 button.textContent = '确认删除'; button.classList.add('danger'); button.disabled = true;
 form.elements.confirm_name.oninput = e => { button.disabled = e.target.value !== u.username };
 const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = '取消'; cancel.onclick = () => modal.close(); form.querySelector('.form-actions').prepend(cancel);
}

function countPermission(u={role:'employee',can_count:0}) {
 if(u.role !== 'employee') return '';
 return `<label>允许入库点货<select name="can_count"><option value="0" ${!u.can_count?'selected':''}>未开启</option><option value="1" ${u.can_count?'selected':''}>开启</option></select><small>只开放点货，不开放他人工资、产品管理或经理报表。</small></label>`;
}
function users() { content(heading('员工与时薪', '经理设置时薪及点货权限；获授权的员工使用同一账号报工和点货。', '<button class="primary" id="add-user">＋ 添加账号</button>') + `<section class="card"><div class="table-wrap"><table><thead><tr><th>姓名</th><th>登录账号</th><th>角色</th><th>计时时薪</th><th>点货权限</th><th></th></tr></thead><tbody>${state.users.filter(u => !u.deleted).map(u => `<tr><td><strong>${esc(u.name)}</strong></td><td>${esc(u.username)}</td><td>${u.role === 'manager' ? '经理' : u.role === 'checker' ? '点货员' : '员工'}</td><td>${cash(u.rate)} / 小时</td><td>${u.role!=='employee'||u.can_count?'已开启':'未开启'}</td><td class="user-actions-cell"><div class="user-actions"><button class="quiet" data-user="${u.id}">编辑</button>${u.id !== state.user.id ? `<button class="quiet danger" data-delete-user="${u.id}">删除</button>` : '<button type="button" class="quiet current-account" disabled title="不能删除当前登录账号，请由另一位经理操作">删除</button>'}</div></td></tr>`).join('')}</tbody></table></div></section>`); document.querySelectorAll('[data-delete-user]').forEach(b => b.onclick = () => deleteUser(+b.dataset.deleteUser)); document.querySelector('#add-user').onclick = () => {
 formModal('添加员工账号', field('姓名', 'name') + field('登录名', 'username') + field('初始密码', 'password', '', 'password', 'minlength="10" autocomplete="new-password"') + field('计时时薪', 'rate', '', 'number', 'min="0" step="0.01"') + '<label>角色<select name="role"><option value="employee">普通员工</option><option value="manager">经理</option></select></label><div id="employee-count-permission">' + countPermission() + '</div>', 'user');
 const form=document.querySelector('#modal-form');
 form.elements.role.onchange=()=>{
  const employee=form.elements.role.value==='employee';
  document.querySelector('#employee-count-permission').hidden=!employee;
  form.elements.can_count.disabled=!employee;
 };
}; document.querySelectorAll('[data-user]').forEach(b => b.onclick = () => { const u = state.users.find(u => u.id === +b.dataset.user); formModal('编辑 ' + esc(u.name), field('姓名', 'name', u.name) + field('计时时薪', 'rate', u.rate / 100, 'number', 'min="0" step="0.01"') + countPermission(u) + '<label class="full">重设密码（留空则不修改）<input name="password" type="password" minlength="10" autocomplete="new-password"></label>', 'user', { id: u.id }) }) }
let auditFilters = {start:'',end:'',actor:'',action:''}, auditPage=1, auditAnchor=null, auditRequest=0;
async function audit(reuse = false) {
    const request=++auditRequest, userId=state.user.id;
    if (!reuse || !document.querySelector('#audit-filters')) {
    auditPage=1;auditAnchor=null;
    content(heading('操作记录','完整保留操作历史，按日期、操作人和类型查找。时间及日期筛选均按多伦多时间。')+`<section class="card audit-card"><form id="audit-filters" class="audit-filters"><label>开始日期<input type="date" name="start" value="${esc(auditFilters.start)}"></label><label>结束日期<input type="date" name="end" value="${esc(auditFilters.end)}"></label><label>操作人<select name="actor" disabled><option>正在加载…</option></select></label><label>操作类型<select name="action" disabled><option>正在加载…</option></select></label></form><div class="audit-filter-note"><small>更改条件后自动更新</small><button type="button" class="quiet" id="audit-reset" hidden>清除筛选</button></div><p id="audit-error" class="error" role="alert"></p><div id="audit-results" aria-live="polite"></div></section>`);
    }
    const form=document.querySelector('#audit-filters');
    const applyFilters=()=>{
        ++auditRequest;
        const values=Object.fromEntries(new FormData(form));
        // Disabled selectors during initial loading must not erase existing filters.
        for(const key of ['actor','action'])if(form.elements[key].disabled)values[key]=auditFilters[key]||'';
        auditFilters=values;
        document.querySelector('#audit-reset').hidden=!Object.values(values).some(Boolean);
        if(!form.checkValidity() || (values.start&&values.end&&values.start>values.end)) {
            document.querySelector('#audit-error').textContent='请选择有效日期，开始日期不能晚于结束日期';
            document.querySelector('#audit-results').textContent='请调整日期范围后查看记录。';return;
        }
        auditPage=1;auditAnchor=null;audit(true);
    };
    form.onchange=applyFilters;
    form.onsubmit=e=>{e.preventDefault();applyFilters()};
    document.querySelector('#audit-reset').hidden=!Object.values(auditFilters).some(Boolean);
    document.querySelector('#audit-reset').onclick=()=>{auditFilters={start:'',end:'',actor:'',action:''};for(const key of Object.keys(auditFilters))form.elements[key].value='';auditPage=1;auditAnchor=null;audit(true)};
    document.querySelector('#audit-error').textContent='';
    document.querySelector('#audit-results').textContent='正在更新记录…';
    const query=new URLSearchParams({page:auditPage});
    if(auditAnchor!==null)query.set('anchor',auditAnchor);
    for(const key of ['actor','action'])if(auditFilters[key])query.set(key,auditFilters[key]);
    // The server interprets calendar dates in Toronto, including DST boundaries.
    for(const key of ['start','end'])if(auditFilters[key]){query.set(key,auditFilters[key])}
    try {
    const data=await api('audit?'+query);
    if(request!==auditRequest||page!=='audit'||state?.user.id!==userId||!form.isConnected)return;
    auditPage=data.page;auditAnchor=data.anchor;
    form.elements.actor.innerHTML='<option value="">全部操作人</option>'+data.actors.map(u=>`<option value="${u.id}">${esc(u.name)}（${esc(u.username)}）</option>`).join('');
    const labels={workflow:'创建产品流程',product:'添加产品 / 调整单价',product_flow:'产品工序设置',product_delete:'停用产品',user:'账号与时薪',user_delete:'删除用户',direct_sale:'直售登记 / 修改',intake_count:'点货登记 / 复点',process_link:'工序关联'};
    form.elements.action.innerHTML='<option value="">全部操作类型</option>'+data.actions.map(action=>`<option value="${esc(action)}">${esc(labels[action]||action)}</option>`).join('');
    for(const key of ['actor','action']){form.elements[key].value=auditFilters[key]||'';form.elements[key].disabled=false}
    enhanceLotPickers();
    const records=data.rows.map(a=>({...a,view:auditView(a,state)}));
    document.querySelector('#audit-results').innerHTML=`<div class="audit-page-head"><span>共 ${data.total} 条 · 每页 50 条</span><small>最新操作在前</small></div><div class="table-wrap"><table><thead><tr><th>操作时间</th><th>操作人</th><th>操作内容</th><th></th></tr></thead><tbody>${records.map(a=>`<tr><td>${esc(businessTime(a.at))}</td><td>${esc(a.view.actor)}</td><td><strong>${esc(a.view.title)}</strong><small>${esc(a.view.subject)}</small></td><td><button class="quiet" data-audit="${a.id}">查看变更</button></td></tr>`).join('')}</tbody></table>${records.length?'':'<div class="empty">没有符合条件的操作记录，请调整筛选条件。</div>'}</div><div class="audit-pagination"><button id="audit-prev" ${data.page<=1?'disabled':''}>上一页</button><span>第 ${data.page} / ${data.pages} 页</span><button id="audit-next" ${data.page>=data.pages?'disabled':''}>下一页</button></div>`;
    document.querySelector('#audit-prev').onclick=()=>{auditPage--;audit(true);document.querySelector('#audit-filters').scrollIntoView({block:'start'})};
    document.querySelector('#audit-next').onclick=()=>{auditPage++;audit(true);document.querySelector('#audit-filters').scrollIntoView({block:'start'})};
    document.querySelectorAll('[data-audit]').forEach(b => b.onclick = () => {
        const a = records.find(a => a.id === +b.dataset.audit), v = a.view;
        showModal('操作详情', `<div class="audit-meta"><div><span>操作人</span><strong>${esc(v.actor)}</strong></div><div><span>操作时间</span><strong>${esc(businessTime(a.at))}</strong></div><div><span>操作内容</span><strong>${esc(v.title)}</strong></div><div><span>操作对象</span><strong>${esc(v.subject)}</strong></div></div>${v.reason ? `<div class="hint audit-reason">修改原因：${esc(v.reason)}</div>` : ''}<div class="audit-changes"><table><thead><tr><th>修改项目</th><th>原来</th><th>现在</th></tr></thead><tbody>${v.rows.map(r => `<tr><td>${esc(r[0])}</td><td class="audit-before">${esc(r[1])}</td><td class="audit-after">${esc(r[2])}</td></tr>`).join('')}</tbody></table></div>${v.note ? `<p class="muted audit-note">${esc(v.note)}</p>` : ''}`);
    });
    } catch(err) {if(request===auditRequest&&form.isConnected){document.querySelector('#audit-results').innerHTML='<button class="quiet" id="audit-retry">重新加载</button>';document.querySelector('#audit-retry').onclick=()=>audit(true);document.querySelector('#audit-error').textContent=err.message}}
}

(async () => { try { await refresh(); page = state.user.role === 'manager' ? 'overview' : state.user.role === 'checker' ? 'inventory' : 'entry'; render() } catch (e) { if (!state) login(); else notify(e.message) } })();

let exportMonth = localDate().slice(0, 7), exportKind = 'employees', exportRequest = 0;
function monthlySummary(report,kind) {
 const sum = name => report.rows.reduce((n,row)=>n+(Number(row[report.columns.indexOf(name)])||0),0);
 const metric=(label,value)=>`<div><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`;
 if(kind==='employees') return `<div class="report-highlights">${metric('员工总产值',cash(Math.round(sum('总产值')*100)))}${metric('总工时',sum('总工时').toFixed(2)+' 小时')}${metric('待核对日报',sum('待核对日报数')+' 份')}</div>`;
 const units=new Map(); const unitIndex=report.columns.indexOf('单位'), totalIndex=report.columns.indexOf('入库 + 直售（已填）');
 report.rows.forEach(row=>{if(row[totalIndex]!=='')units.set(row[unitIndex],(units.get(row[unitIndex])||0)+Number(row[totalIndex]))});
 return `<div class="report-highlights">${metric('已记录成品产量', [...units].map(([unit,total])=>total+' '+unit).join(' / ')||'—')}${metric('待核对产品',report.rows.filter(row=>row[report.columns.indexOf('核对状态')]!=='核对通过').length+' 项')}</div>`;
}
async function monthlyExports() {
    const request = ++exportRequest;
    content(heading('月度导出', '选择月份，预览员工核算或产品产量，再下载 CSV。') + `<div class="export-layout"><aside class="card export-controls"><label>导出月份<input type="month" id="export-month" value="${exportMonth}" max="${localDate().slice(0, 7)}" required></label><label>报表类型<select id="export-kind"><option value="employees" ${exportKind==='employees'?'selected':''}>员工月度核算</option><option value="products" ${exportKind==='products'?'selected':''}>产品月度产量</option></select></label><button class="primary" id="monthly-download" disabled>下载完整报表</button><button id="monthly-reload">刷新预览</button></aside><section class="card export-preview" aria-live="polite"><div id="export-preview">正在加载月度数据…</div></section></div>`);
    document.querySelector('#export-month').onchange = e => { if (!e.target.reportValidity()) { e.target.value = exportMonth; e.target.setCustomValidity(''); notify('请选择有效月份，不能晚于本月'); return } exportMonth = e.target.value; monthlyExports() };
    document.querySelector('#export-kind').onchange=e=>{exportKind=e.target.value;monthlyExports()};
    document.querySelector('#monthly-reload').onclick = () => monthlyExports();
    const month = exportMonth, kind = exportKind;
    try {
        const report = await api('monthly?month=' + encodeURIComponent(month) + '&kind=' + kind);
        if (request !== exportRequest || page !== 'exports') return;
        const drawPreview = () => {
            const selected = report.columns.map((_,i)=>i);
            document.querySelector('#export-preview').innerHTML = `<div class="card-head"><h2>${esc(report.title)}</h2></div><p class="muted">${report.start} 至 ${report.end} · ${report.rows.length} 条记录${report.partial ? ' · 本月统计截至今天' : ''}</p>${monthlySummary(report,kind)}<p class="report-definition">${kind === 'employees' ? '总产值 = 计件金额 + 计时金额；平均时产值 = 总产值 ÷ 总工时。' : '产量合计 = 实际入库 + 未入库直售，仅统计成品，半成品不重复计入。未完成点货时，合计可能不完整。'}</p><details class="export-note"><summary>统计口径与下载说明</summary><p>${esc(report.note)} 下载完整报表保留全部字段。</p></details>${report.rows.length ? `<div class="report-table" tabindex="0" role="region" aria-label="月度报表，宽度不足时可左右滑动"><table><thead><tr>${selected.map(i=>`<th scope="col">${esc(report.columns[i])}</th>`).join('')}</tr></thead><tbody>${report.rows.map(row=>`<tr>${selected.map(i=>`<td>${esc(row[i] === '' ? '—' : row[i])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '<div class="empty">该月没有可导出的记录，请选择其他月份。</div>'}`;

        };
        drawPreview();
        const button = document.querySelector('#monthly-download'); button.disabled = !report.rows.length;
        button.onclick = () => {
            const safe = v => typeof v === 'string' && /^[\s]*[=+\-@\t\r]/.test(v) ? "'" + v : v;
            const cell = v => '"' + String(safe(v)).replace(/"/g, '""') + '"';
            const csv = '\ufeff' + [report.columns, ...report.rows].map(row => row.map(cell).join(',')).join('\r\n') + '\r\n';
            const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' })), a = document.createElement('a'); a.href = url; a.download = report.title + '-' + report.month + '.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        };
    } catch (e) { const target = document.querySelector('#export-preview'); if (request === exportRequest && page === 'exports' && target) target.textContent = e.message }
}



function chineseValidation(input) {
    input.setCustomValidity('');
    const v = input.validity;
    if (v.valid) return;
    let message = '请检查填写内容';
    if (v.valueMissing) message = input.tagName === 'SELECT' ? '请选择一项' : '请填写此项';
    else if (v.badInput || v.typeMismatch) message = '请输入有效的' + (input.type === 'number' ? '数字' : '内容');
    else if (v.rangeUnderflow) message = '请输入不小于 ' + input.min + ' 的值';
    else if (v.rangeOverflow) message = '请输入不大于 ' + input.max + ' 的值';
    else if (v.stepMismatch) message = '请按 ' + (input.step || '1') + ' 的间隔填写';
    else if (v.tooShort) message = '请至少输入 ' + input.minLength + ' 个字符';
    else if (v.tooLong) message = '最多输入 ' + input.maxLength + ' 个字符';
    else if (v.patternMismatch) message = input.id === 'export-month' ? '请按年-月填写，例如 2026-10' : '请按要求的格式填写';
    input.setCustomValidity(message);
}
document.addEventListener('invalid', e => { if (e.target.setCustomValidity) chineseValidation(e.target) }, true);
for (const event of ['input','change']) document.addEventListener(event, e => { if (e.target.setCustomValidity) e.target.setCustomValidity('') }, true);
