import assert from 'node:assert/strict';
import { textureColor, type EarthTexture } from '../src/basemap';
const texture:EarthTexture={width:2,height:2,pixels:new Uint8ClampedArray([255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255])};
assert.deepEqual(textureColor(texture,-180,90),[255,0,0]);
assert.deepEqual(textureColor(texture,-180,-90),[0,0,255]);
assert.deepEqual(textureColor(texture,180,90),textureColor(texture,-180,90));
assert.deepEqual(textureColor(texture,540,90),textureColor(texture,-180,90));
assert.deepEqual(textureColor(texture,-90,0),[127.5,127.5,127.5]);
console.log('通过：底图南北方向、日期变更线和双线性采样');
