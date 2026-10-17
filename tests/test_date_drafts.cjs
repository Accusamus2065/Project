const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('harvest/web/app.js','utf8');
const fn=src.slice(src.indexOf('function bindDate()'),src.indexOf('\nfunction heading'));
function setup(){
 const input={value:'2026-10-16',disabled:false,reportValidity:()=>true,setCustomValidity(){}};
 const ctx={document:{querySelector:()=>input},day:'2026-10-16',draft:{hours:'1.5',memo:'清洁'},dayDrafts:new Map(),dateRequest:0,state:{user:{id:1}},captureDraft(){},render(){},notify(){},api:async()=>({user:{id:1}})};
 vm.createContext(ctx);vm.runInContext(fn,ctx);ctx.bindDate();return {ctx,input};
}
(async()=>{
 const {ctx,input}=setup();const original=ctx.draft;
 await input.onchange();assert.equal(ctx.draft,original);
 input.value='2026-10-15';await input.onchange();assert.equal(ctx.draft,null);
 ctx.draft={hours:'2',memo:'另一日'};
 input.value='2026-10-16';await input.onchange();assert.equal(ctx.draft,original);
 input.value='2026-10-15';await input.onchange();assert.equal(ctx.draft.memo,'另一日');
 ctx.api=async()=>{throw Error('离线')};input.value='2026-10-14';await input.onchange();
 assert.equal(ctx.day,'2026-10-15');assert.equal(ctx.draft.memo,'另一日');assert.equal(input.value,ctx.day);
 let resolve;ctx.api=()=>new Promise(r=>resolve=r);input.value='2026-10-14';const pending=input.onchange();
 ctx.state=null;ctx.dateRequest++;resolve({user:{id:1}});await pending;assert.equal(ctx.state,null);assert.equal(ctx.day,'2026-10-15');
 console.log('Date drafts: same date, independent days, failed fetch and logout race passed');
})().catch(e=>{console.error(e);process.exitCode=1});
