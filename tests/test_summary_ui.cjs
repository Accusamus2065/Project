const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('harvest/web/app.js','utf8');
const ctx={esc:s=>String(s),cash:n=>(n/100).toFixed(2)};vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('function monthlySummary('),src.indexOf('async function monthlyExports()')),ctx);
const html=ctx.monthlySummary({columns:['单位','入库 + 直售（已填）','核对状态'],rows:[['盒',100,'核对通过'],['盒',20,'核对通过'],['箱',5,'待核对'],['盒','','待核对']]},'products');
assert.ok(html.includes('120 盒 / 5 箱'));assert.ok(html.includes('2 项'));assert.ok(!html.includes('125'));
console.log('Mixed-unit totals and incomplete records passed');
