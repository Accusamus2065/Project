const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const box={};vm.createContext(box);vm.runInContext(readFileSync('harvest/web/audit.js','utf8'),box);
const ctx={users:[{id:2,name:'林晓'}],lots:[{id:1,code:'LOT-A',product:'香菇',unit:'盒'}]};
const view=(action,d)=>box.auditView({action,name:'经理',detail:JSON.stringify(d)},ctx);
let v=view('user',{format:2,actor_name:'原经理姓名',before:{name:'林晓',rate:1760},after:{name:'林晓',rate:1850},password_reset:true});
assert.equal(v.actor,'原经理姓名');assert.equal(v.rows[0][1],'17.60 / 小时');assert.equal(v.rows[0][2],'18.50 / 小时');assert.equal(v.rows.length,2);
v=view('lot',{id:1,price:'1.50'});assert.equal(v.rows[0][1],'未记录');assert.equal(v.rows[0][2],'1.50');assert.ok(v.note);
v=view('lot',{format:2,before:null,after:{code:'LOT-B',price:100,opening:0}});assert.equal(v.title,'添加 Lot');assert.equal(v.rows[1][2],'1.00');
const report={minutes:480,rate:1760,amount:12604,pieces:[{lot_id:1,code:'LOT-A',product:'香菇',unit:'盒',price:106,quantity:94}],timed:[{minutes:90,memo:'接种'}]};
v=view('提交日报',{user_id:2,date:'2026-09-21',before:null,after:report});assert.equal(v.subject,'林晓 · 2026-09-21');assert.equal(v.rows[0][1],'未填写');assert.equal(v.rows[0][2],'8 小时');
v=view('修改日报',{user_name:'原员工姓名',date:'2026-09-21',before:{...report,pieces:JSON.stringify(report.pieces),timed:JSON.stringify(report.timed)},after:{...report,amount:12710,pieces:[{...report.pieces[0],quantity:95}]},reason:'补录一盒'});assert.ok(v.rows.some(r=>r[1]==='94 盒'&&r[2]==='95 盒'));assert.ok(!v.rows.some(r=>r[0]==='总工时'));assert.equal(v.reason,'补录一盒');
v=view('count',{format:2,lot_id:1,date:'2026-09-21',before:{actual:80},after:{actual:90},expected:90});assert.equal(v.rows[0][1],'80 盒');assert.equal(v.rows[2][2],'核对通过');
v=view('shipment_void',{before:{lot_id:1,date:'2026-09-21',quantity:10,memo:'售出'},reason:'重复'});assert.equal(v.rows[0][2],'已撤销');
console.log('7 audit display scenarios passed');
v=view('intake_count',{product:'两磅平菇',date:'2026-10-07',actor_name:'李点货',before:{actual:9},after:{actual:10},expected:10,reason:'重新点货'});assert.equal(v.title,'修正入库点货');assert.equal(v.actor,'李点货');assert.equal(v.rows[0][1],'9 盒');assert.equal(v.rows[0][2],'10 盒');assert.equal(v.reason,'重新点货');
v=view('product',{format:2,before:null,after:{product:'三磅香菇',price:106,start_date:'2026-10-07'}});assert.equal(v.title,'添加产品');assert.equal(v.rows[1][2],'1.06');
v=view('product_delete',{before:{product:'三磅香菇'},after:{product:'三磅香菇'}});assert.equal(v.title,'停用产品');assert.ok(v.rows[0][2].includes('历史记录保留'));
console.log('3 daily-intake audit scenarios passed');

const saleView = box.auditView({action:'direct_sale',name:'经理',detail:JSON.stringify({product:'香菇',date:'2026-10-09',before:{quantity:10,memo:'旧说明'},after:{quantity:12,memo:'新说明'},reason:'补记'})},{});
assert.equal(saleView.title,'修正未入库直售');
assert.equal(JSON.stringify(saleView.rows[0]),JSON.stringify(['当天直接售出未入库','10 盒','12 盒']));
assert.equal(saleView.reason,'补记');

v=view('intake_count',{product:'香菇采摘',stage:'semi',unit:'筐',date:'2026-10-09',before:{actual:9},after:{actual:10},expected:10});
assert.equal(v.rows[0][0],'当天半成品实点');assert.equal(v.rows[0][2],'10 筐');
v=view('product',{before:null,after:{product:'香菇采摘',price:500,stage:'semi',unit:'筐',start_date:'2026-10-09'}});
assert.ok(v.rows.some(r=>r[0]==='产品类型'&&r[2]==='半成品'));
assert.ok(v.rows.some(r=>r[0]==='计量单位'&&r[2]==='筐'));

v=view('product',{before:{product:'香菇采摘',price:500,stage:'semi',unit:'筐'},after:{product:'香菇采摘',price:600,stage:'semi',unit:'筐'}});
assert.equal(v.rows.length,1);assert.equal(v.rows[0][0],'计件单价');
console.log('Stage, unit and price-only audit checks passed');
