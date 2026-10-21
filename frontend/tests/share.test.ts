import assert from 'node:assert/strict';
import { buildShare, nearestTime, parseShare } from '../src/share';
const fieldIds=['wind','temperature','cloud'];
const state={model:'ifs',field:'cloud',time:'2026-10-22T06:00Z',center:[115.004,12.5] as [number,number],zoom:1.4,point:[116.4,39.9] as [number,number],province:'110000',compare:true};
const hash=buildShare(state);
assert.equal(hash,'#home?m=ifs&f=cloud&t=2026-10-22T06:00Z&r=115.00,12.50&z=1.40&p=116.400,39.900&s=110000&c=1');
assert.deepEqual(parseShare(hash,fieldIds),{...state,center:[115,12.5]});
console.log('通过：分享链接编码与解析往返一致');

// 非法或越界参数全部忽略，不能让手改的链接打坏页面。
assert.deepEqual(parseShare('#home?m=ecmwf&f=snow&t=昨天&r=200,10&z=abc&p=1,2,3&s=../',fieldIds),{center:undefined,point:undefined});
assert.equal(parseShare('#home?z=9',fieldIds).zoom,3);
assert.equal(parseShare('#home?s=110000',fieldIds).province,undefined,'没有点击位置时不恢复省份');
assert.deepEqual(parseShare('#station',fieldIds),{});
assert.deepEqual(parseShare('',fieldIds),{});
console.log('通过：非法参数被忽略，缩放限制在可用范围');

const times=['2026-10-22T00:00Z','2026-10-22T03:00Z','2026-10-22T06:00Z'];
assert.deepEqual(nearestTime(times,'2026-10-22T03:00Z'),{index:1,exact:true});
assert.deepEqual(nearestTime(times,'2026-10-22T04:00Z'),{index:1,exact:false});
assert.deepEqual(nearestTime(times,'2026-10-19T00:00Z'),{index:0,exact:false});
console.log('通过：过期时刻按最近一帧打开');
