const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('harvest/web/app.js','utf8');
const fn=src.slice(src.indexOf('async function api('),src.indexOf('\nasync function refresh('));
(async()=>{
 const pending=[];
 const ctx={state:{csrf:'old'},draft:{},dayDrafts:new Map(),dateRequest:0,
   modal:{close(){}},login(){ctx.logins++},logins:0,
   fetch:()=>new Promise(resolve=>pending.push(resolve))};
 vm.createContext(ctx);vm.runInContext(fn,ctx);
 const unauthorized={ok:false,status:401,json:async()=>({error:'登录已失效'})};
 const old=ctx.api('state');ctx.state={csrf:'new'};
 pending.shift()(unauthorized);await assert.rejects(old,/登录已失效/);
 assert.equal(ctx.state.csrf,'new','a delayed old-session failure must not log out the new session');
 assert.equal(ctx.logins,0);
 const current=ctx.api('state');pending.shift()(unauthorized);
 await assert.rejects(current,/登录已失效/);
 assert.equal(ctx.state,null);assert.equal(ctx.logins,1);
 console.log('2 session response scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1});
