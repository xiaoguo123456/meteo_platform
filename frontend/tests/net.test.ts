import assert from 'node:assert/strict';
import { fetchJson, isNetworkSlow, RequestError } from '../src/net';
const original=globalThis.fetch;
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
// 模拟卡住的请求：不返回，直到被中止。
const hang=(signal?:AbortSignal|null)=>new Promise<Response>((_,reject)=>signal?.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))));
let calls=0;
try{
 globalThis.fetch=(async(_:unknown,init?:RequestInit)=>{calls++;return calls===1?hang(init?.signal):json({ok:1});}) as typeof fetch;
 assert.deepEqual(await fetchJson('/a',{timeout:30}),{ok:1});assert.equal(calls,2,'第一次卡住超时后自动重试');
 console.log('通过：请求卡住时限时并自动重试');

 calls=0;globalThis.fetch=(async()=>{calls++;return json({detail:'省平均正在后台计算（1/2）'},503);}) as typeof fetch;
 await assert.rejects(fetchJson('/b',{timeout:30}),(e:unknown)=>e instanceof RequestError&&e.message.includes('后台计算')&&!isNetworkSlow(e));
 assert.equal(calls,1,'后端业务错误不重试');

 calls=0;globalThis.fetch=(async()=>{calls++;return calls<3?new Response('origin timeout',{status:524}):json([1]);}) as typeof fetch;
 assert.deepEqual(await fetchJson('/c',{timeout:30}),[1]);assert.equal(calls,3,'Cloudflare 524 回源超时重试');
 console.log('通过：业务错误不重试，网关超时重试');

 calls=0;globalThis.fetch=(async(_:unknown,init?:RequestInit)=>{calls++;return hang(init?.signal);}) as typeof fetch;
 await assert.rejects(fetchJson('/d',{timeout:20,retries:1}),(e:unknown)=>e instanceof RequestError&&e.timeout&&isNetworkSlow(e));
 assert.equal(calls,2);
 console.log('通过：重试用尽后报"网络较慢"，便于界面区分');

 calls=0;const outer=new AbortController();globalThis.fetch=(async(_:unknown,init?:RequestInit)=>{calls++;return hang(init?.signal);}) as typeof fetch;
 setTimeout(()=>outer.abort(),10);
 await assert.rejects(fetchJson('/e',{signal:outer.signal,timeout:1000}),(e:unknown)=>e instanceof DOMException&&e.name==='AbortError');
 assert.equal(calls,1,'外部取消后不再重试');
 console.log('通过：切换视图取消请求时立即停止');
}finally{globalThis.fetch=original;}
