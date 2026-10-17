const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('harvest/web/app.js','utf8');
const fn=src.slice(src.indexOf('async function saveWorkRecord('),src.indexOf('\nfunction validInputNumber'));
(async()=>{
 let resolve,calls=0;
 const form={dataset:{},isConnected:false},button={disabled:false};
 const ctx={day:'2026-10-16',state:{user:{id:1}},draft:{user_id:1,hours:2},dayDrafts:new Map(),document:{querySelector:()=>button},captureDraft(){},notify(){},refreshAfterSave:async()=>{},api:()=>{calls++;return new Promise(r=>resolve=r)}};
 vm.createContext(ctx);vm.runInContext(fn,ctx);
 const event={preventDefault(){},currentTarget:form};
 let request=ctx.saveWorkRecord(event);await ctx.saveWorkRecord(event);assert.equal(calls,1);
 ctx.day='2026-10-15';const otherDraft={user_id:1,hours:5};ctx.draft=otherDraft;ctx.dayDrafts.set(ctx.day,otherDraft);
 resolve({});await request;assert.equal(ctx.draft,otherDraft);assert.equal(ctx.dayDrafts.get(ctx.day),otherDraft);
 request=ctx.saveWorkRecord(event);ctx.state=null;ctx.draft=null;resolve({});await request;assert.equal(ctx.state,null);
 console.log('Report submit: duplicate guard, date switch and logout passed');
})().catch(e=>{console.error(e);process.exitCode=1});
