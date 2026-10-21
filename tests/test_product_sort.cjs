const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('harvest/web/app.js', 'utf8');
const ctx = { esc: String, day: '2026-10-20', draft: { pieces: [] } };
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('function compareProducts('), src.indexOf('function reportCard(')), ctx);
const products = [
    { id: 1, product: '150g 金针菇·分包', process: 'pack' },
    { id: 2, product: '300g 金针菇·封膜', process: 'seal' },
    { id: 3, product: '150g 金针菇·封膜', process: 'seal' },
    { id: 4, product: '150g 金针菇·采摘', process: 'harvest' },
    { id: 5, product: '300g 金针菇·分包', process: 'pack' },
].map(p => ({ ...p, unit: '盒', start_date: '2026-01-01', deleted: false }));
const expected = [4, 1, 3, 5, 2];
assert.deepEqual(Array.from(ctx.sortedReportPieces(products), p => p.id), expected);
assert.deepEqual(products.map(p => p.id), [1, 2, 3, 4, 5], 'sorting must not mutate input');
// Older report snapshots may have labels but no process metadata.
assert.deepEqual(Array.from(ctx.sortedReportPieces(products.map(({process, ...p}) => p)), p => p.id), expected);
ctx.state = { products };
vm.runInContext(src.slice(src.indexOf('const productLabel='), src.indexOf('// Keep the native select')), ctx);
const html = vm.runInContext('lotOptions(1, true)', ctx);
assert.deepEqual([...html.matchAll(/value="(\d+)"/g)].map(m => +m[1]), expected);
assert.match(html, /value="1" selected/);
ctx.state.products[3].deleted = true;
assert.deepEqual([...vm.runInContext('lotOptions(1, true)', ctx).matchAll(/value="(\d+)"/g)].map(m => +m[1]), [1, 3, 5, 2]);
console.log('Product process ordering and picker filtering passed');
const custom = [
 {id:10, product:'3lb mini·剪根后', family_name:'3lb mini', step_name:'剪根后', step_order:2},
 {id:11, product:'3lb mini·采摘', family_name:'3lb mini', step_name:'采摘', step_order:1},
 {id:12, product:'180g 平菇·封膜', family_name:'180g 平菇', step_name:'封膜', step_order:2},
 {id:13, product:'180g 平菇·采摘分装', family_name:'180g 平菇', step_name:'采摘分装', step_order:1}
];
const ordered=Array.from(ctx.sortedReportPieces(custom),p=>p.id);
assert.ok(ordered.indexOf(11)<ordered.indexOf(10));
assert.ok(ordered.indexOf(13)<ordered.indexOf(12));
// Stored order takes precedence over the old semantic names.
assert.deepEqual(Array.from(ctx.sortedReportPieces([
 {product:'产品·采摘',family_name:'产品',step_order:2,process:'harvest'},
 {product:'产品·预处理',family_name:'产品',step_order:1}
]),p=>p.product),['产品·预处理','产品·采摘']);
console.log('Custom workflow names and saved step order passed');
