import assert from 'node:assert/strict';
import { globeCrop, layout, pickMime, SIZES } from '../src/exportVideo';
assert.deepEqual(pickMime(type=>type.startsWith('video/mp4')),{mime:'video/mp4;codecs=avc1.42E01E',ext:'mp4'});
assert.deepEqual(pickMime(type=>type.startsWith('video/webm')),{mime:'video/webm;codecs=vp9',ext:'webm'},'Firefox 不支持 MP4 时退回 WebM');
assert.equal(pickMime(()=>false),null);
console.log('通过：优先 MP4，不支持时退回 WebM');

// 地球完整可见时按圆盘留边裁剪；放大到超出视口时取视口内最大正方形。
assert.deepEqual(globeCrop(1280,800,300),{x:316,y:76,side:648});
assert.deepEqual(globeCrop(1280,800,900),{x:240,y:0,side:800});
for(const format of ['portrait','landscape'] as const){
 const plan=layout(format),{width,height}=SIZES[format];
 assert.ok(plan.globe.x>=0&&plan.globe.y>=0&&plan.globe.x+plan.globe.side<=width&&plan.globe.y+plan.globe.side<=height,`${format} 地球区域越界`);
 assert.ok(plan.legend.x+plan.legend.width<=width&&plan.legend.y+90<=height,`${format} 色标越界`);
}
// 数据来源行（色标下 80px）与底部水印行（距底 36px）至少相隔 40px，长来源文字不会压到水印。
for(const format of ['portrait','landscape'] as const){const plan=layout(format);assert.ok(SIZES[format].height-36-(plan.legend.y+80)>=40,`${format} 来源与水印太近`);}
assert.equal(SIZES.portrait.width/SIZES.portrait.height,3/4);
assert.equal(SIZES.landscape.width/SIZES.landscape.height,16/9);
console.log('通过：竖版 3:4、横版 16:9 版式不越界');
