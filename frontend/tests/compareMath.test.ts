import assert from 'node:assert/strict';
import { largestSpread, valueAt } from '../src/compareMath';
const hourly=(start:string,values:(number|null)[],step=1)=>values.map((value,i)=>({time:new Date(Date.parse(start)+i*step*3600000).toISOString().replace(':00.000Z','Z'),value}));
const gfs=hourly('2026-10-22T00:00Z',[10,11,12,13,14,15,16]);
const ifs=hourly('2026-10-22T00:00Z',[10,14,18],3);
assert.equal(valueAt(ifs,Date.parse('2026-10-22T04:00Z')),14,'IFS 3 小时一帧，4 时取 3 时的值');
assert.equal(valueAt(ifs,Date.parse('2026-10-22T05:00Z')),18,'取最近的 6 时');
assert.equal(valueAt(ifs,Date.parse('2026-10-22T10:00Z')),null,'超出 1.5 小时容差视为无数据');
assert.equal(valueAt(hourly('2026-10-22T00:00Z',[null,5]),Date.parse('2026-10-22T00:00Z')),5,'缺测跳过，取最近有效值');
console.log('通过：不同时间间隔的模型按实际时刻对齐');

const result=largestSpread([{model:'gfs',points:gfs},{model:'ifs',points:ifs}]);
// 只在两者都有帧的 0、3、6 时比较：6 时 GFS 16、IFS 18，相差 2；不拿 GFS 5 时与 IFS 6 时相减。
assert.deepEqual(result,{spread:2,time:'2026-10-22T06:00Z',models:2});
// 起报更晚的模型决定共同起点：GRAPES 从 3 时开始，0 时只有一个模型有值，不计入。
const grapes=hourly('2026-10-22T03:00Z',[20,20]);
assert.deepEqual(largestSpread([{model:'gfs',points:gfs},{model:'grapes',points:grapes}]),{spread:7,time:'2026-10-22T03:00Z',models:2});
assert.equal(largestSpread([{model:'gfs',points:gfs},{model:'ifs',points:[]}]),null,'只有一个模型有值时不比较');
assert.equal(largestSpread([{model:'gfs',points:gfs},{model:'ifs',points:hourly('2026-10-23T12:00Z',[1])}],24)?.spread,undefined,'没有重叠时刻时不比较');
console.log('通过：四模型最大分歧只在共同时段内计算');
