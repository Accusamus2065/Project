const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('harvest/web/app.js', 'utf8');
const fn = source.slice(source.indexOf('function formModal('), source.indexOf('\nconst field'));
function setup() {
  const button = {disabled:false}, error = {textContent:''};
  const form = {isConnected:true,querySelector:s=>s==='[type=submit]'?button:error};
  const notices=[];
  const modal={open:true,close(){this.open=false}};
  let resolve,reject,calls=0;
  const pending=new Promise((a,b)=>{resolve=a;reject=b});
  const context={document:{querySelector:()=>form},showModal(){},modal,
    FormData:class { *[Symbol.iterator](){yield ['actual','5']} },
    api:()=>{calls++;return pending},refresh:async()=>{},notify:s=>notices.push(s)};
  vm.createContext(context);vm.runInContext(fn,context);
  context.formModal('点货','','intake_count');
  return {context,form,button,error,notices,modal,resolve,reject,calls:()=>calls};
}
(async()=>{
  const a=setup();const first=a.form.onsubmit({preventDefault(){}});
  await a.form.onsubmit({preventDefault(){}});assert.equal(a.calls(),1);
  a.resolve({ok:true});await first;assert.equal(a.modal.open,false);assert.equal(a.notices[0],'已保存');
  const b=setup();b.context.refresh=async()=>{throw new Error('网络中断')};
  const saved=b.form.onsubmit({preventDefault(){}});b.resolve({ok:true});await saved;
  assert.match(b.notices[0],/^已保存，但页面刷新失败/);assert.equal(b.calls(),1);
  const c=setup();const failure=c.form.onsubmit({preventDefault(){}});
  c.form.isConnected=false;c.reject(new Error('会话过期'));await failure;
  assert.equal(c.error.textContent,'');assert.equal(c.notices[0],'会话过期');
  const d=setup();const retry=d.form.onsubmit({preventDefault(){}});
  d.reject(new Error('数量有误'));await retry;
  assert.equal(d.error.textContent,'数量有误');assert.equal(d.button.disabled,false);
  console.log('4 modal submission scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1});
