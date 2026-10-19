const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('harvest/web/app.js','utf8');
const fn=src.slice(src.indexOf('async function refresh('),src.indexOf('\nasync function refreshAfterSave'));
(async()=>{
 const pending=[];const ctx={day:'2026-10-16',dateRequest:0,state:{user:{id:1}},renders:0,render(){ctx.renders++;ctx.renderedPage=ctx.page},api:()=>new Promise(resolve=>pending.push(resolve))};
 vm.createContext(ctx);vm.runInContext(fn,ctx);
 let request=ctx.refresh();ctx.day='2026-10-15';ctx.dateRequest++;pending.shift()({user:{id:1},date:'2026-10-16'});await request;
 assert.equal(ctx.state.date,undefined,'old refresh must not replace the selected date');
 request=ctx.refresh();ctx.state=null;ctx.dateRequest++;pending.shift()({user:{id:1}});await request;
 assert.equal(ctx.state,null,'logout must not be undone by a late response');
 ctx.state={user:{id:1}};const first=ctx.refresh(),second=ctx.refresh();pending.pop()({user:{id:1},value:'new'});await second;pending.shift()({user:{id:1},value:'old'});await first;
 assert.equal(ctx.state.value,'new','latest refresh must win');
 ctx.page='users';ctx.draft={user_id:1};ctx.dayDrafts=new Map([['old',{}]]);
 request=ctx.refresh(true);pending.shift()({user:{id:1,role:'employee'}});await request;
 assert.equal(ctx.renderedPage,'entry','login must select the new role page before rendering');
 assert.equal(ctx.draft,null);assert.equal(ctx.dayDrafts.size,0);
 console.log('4 refresh race scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1});
