import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OneBotMessage } from './mapper'
import { RecallForwarder, recallCommand, recallForwardOptionsFromEnv } from './recall-forwarder'
const self='100001', account=`qq-${self}`, group='200001'
const recallSuperAdmin='300001', recallForwardDefaultGroups=['200001','200002','200003']
const options={defaultGroups:recallForwardDefaultGroups,superAdmin:recallSuperAdmin}
const stores:RecallForwarder[]=[], roots:string[]=[]
function store(path=':memory:',now?:()=>number){const s=new RecallForwarder(path,options,now);stores.push(s);return s}
function message(g=group,id=1,user='123456789'):OneBotMessage{return {message_type:'group',group_id:g,message_id:id,user_id:user,sender:{nickname:'昵称',card:'群名片'},message:[{type:'text',data:{text:'原始内容'}}]}}
function command(t='/开启防撤回',g='999999999',id=10,user=recallSuperAdmin):OneBotMessage{return {...message(g,id,user),message:[{type:'at',data:{qq:self}},{type:'text',data:{text:` ${t}`}}]}}
function notice(g=group,id=1,user='123456789'){return {notice_type:'group_recall',group_id:g,message_id:id,user_id:user}}
afterEach(()=>{stores.splice(0).forEach(s=>s.close());roots.splice(0).forEach(p=>rmSync(p,{recursive:true,force:true}))})
describe('recall forwarding',()=>{
 it('defaults only to three groups; commands are scoped per account',async()=>{
  const s=store(),send=vi.fn().mockResolvedValue({});for(const g of recallForwardDefaultGroups)expect(s.enabled(account,g)).toBe(true)
  expect(s.enabled(account,'999999999')).toBe(false)
  await s.message(account,self,message('999999999'),send);await s.recall(account,self,notice('999999999'),send);expect(send).not.toHaveBeenCalled()
  await s.message(account,self,command(),send);expect(s.enabled(account,'999999999')).toBe(true);expect(s.enabled('qq-other','999999999')).toBe(false)
 })
 it('requires exact five Chinese characters, slash, real mention and super admin',async()=>{
  expect(recallCommand(command(),self)).toBe(true);expect(recallCommand(command('/关闭防撤回'),self)).toBe(false)
  for(const t of ['/开启防撤回啊','/开启防撤','开启防撤回','/开启 防撤回','/开启防撤回\n更多'])expect(recallCommand(command(t),self)).toBeUndefined()
  for(const raw of [{...command(),message:[{type:'text',data:{text:`@${self} /开启防撤回`}}]}, {...command(),message_type:'private'}, {...command(),message:[{type:'at',data:{qq:'all'}},{type:'text',data:{text:'/开启防撤回'}}]}])expect(recallCommand(raw,self)).toBeUndefined()
  const s=store(),send=vi.fn().mockResolvedValue({});await s.message(account,self,command('/开启防撤回','999999999',1,'888888888'),send)
  expect(s.enabled(account,'999999999')).toBe(false);expect(send).not.toHaveBeenCalled()
 })
 it('shows original sender and content once with out-of-order and duplicate notices',async()=>{
  const s=store(),send=vi.fn().mockResolvedValue({});await s.recall(account,self,notice(),send);expect(send).not.toHaveBeenCalled()
  await s.message(account,self,message(),send);await s.recall(account,self,notice(),send);await s.message(account,self,message(),send)
  expect(send).toHaveBeenCalledTimes(1);expect(send.mock.calls[0]?.[0]).toBe(group)
  expect(JSON.stringify(send.mock.calls[0]?.[1])).toContain('群名片（123456789）');expect(JSON.stringify(send.mock.calls[0]?.[1])).toContain('原始内容')
 })
 it('persists off switches and avoids duplicate command replies after restart',async()=>{
  const root=mkdtempSync(join(tmpdir(),'recall-forward-'));roots.push(root);const path=join(root,'data.sqlite'),send=vi.fn().mockResolvedValue({}),a=store(path)
  await a.message(account,self,command('/关闭防撤回',group),send);a.close();const b=store(path)
  expect(b.enabled(account,group)).toBe(false);await b.message(account,self,command('/关闭防撤回',group),send);expect(send).toHaveBeenCalledTimes(1)
  await b.message(account,self,command('/开启防撤回',group,11),send);expect(b.enabled(account,group)).toBe(true)
 })
 it('does not retry an uncertain send even after restart',async()=>{
  const root=mkdtempSync(join(tmpdir(),'recall-forward-'));roots.push(root);const path=join(root,'data.sqlite'),send=vi.fn().mockRejectedValue(new Error('timeout')),a=store(path)
  await a.message(account,self,message(),send);await expect(a.recall(account,self,notice(),send)).rejects.toThrow('timeout');a.close()
  await store(path).recall(account,self,notice(),send);expect(send).toHaveBeenCalledTimes(1)
 })
 it('ignores own/private messages and expires originals',async()=>{
  let now=1000;const s=store(':memory:',()=>now),send=vi.fn().mockResolvedValue({})
  await s.message(account,self,message(group,1,self),send);await s.recall(account,self,notice(group,1,self),send)
  await s.message(account,self,{...message(),message_type:'private'},send);await s.recall(account,self,{...notice(),notice_type:'friend_recall'},send);expect(send).not.toHaveBeenCalled()
  await s.message(account,self,message(),send);now+=8*86400000;await s.recall(account,self,notice(),send);expect(send).not.toHaveBeenCalled()
  await s.message(account,self,command('/关闭防撤回',group),send);await s.message(account,self,message(group,2),send);await s.recall(account,self,notice(group,2),send);expect(send).toHaveBeenCalledTimes(1)
 })
 it('keeps CQ as text, avoids re-mentions and rejects local file paths',async()=>{
  const s=store(),send=vi.fn().mockResolvedValue({}),raw=message();raw.message=[{type:'text',data:{text:'[CQ:at,qq=all]'}},{type:'at',data:{qq:'all'}},{type:'image',data:{file:'/etc/passwd'}},{type:'image',data:{url:'https://gchat.qpic.cn/image.png'}},{type:'record',data:{file:'private'}}]
  await s.message(account,self,raw,send);await s.recall(account,self,notice(),send);const out=send.mock.calls[0]?.[1]
  expect(out.some((s:{type:string})=>s.type==='at')).toBe(false);expect(JSON.stringify(out)).not.toContain('/etc/passwd')
  expect(out).toContainEqual({type:'image',data:{file:'https://gchat.qpic.cn/image.png'}});expect(JSON.stringify(out)).toContain('[语音]')
 })
 it('reads groups and the super admin from the environment',()=>{
  expect(recallForwardOptionsFromEnv({DUDUDA_RECALL_FORWARD_GROUPS:' 200001, x ,200002',DUDUDA_RECALL_SUPER_ADMIN:' 300001 '}))
   .toEqual({defaultGroups:['200001','200002'],superAdmin:'300001'})
  expect(recallForwardOptionsFromEnv({})).toEqual({defaultGroups:[],superAdmin:''})
 })
})
