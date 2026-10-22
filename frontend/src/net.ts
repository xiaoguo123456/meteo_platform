// 国内经 Cloudflare 洛杉矶节点回源，请求偶尔会卡住十几秒甚至不返回：每次请求限时，网络类失败自动重试。
// 后端自身的业务错误（503 + detail，如"省平均正在后台计算""起报批次已更新"）重试也没用，直接抛出。
export class RequestError extends Error{
 constructor(message:string,public status=0,public timeout=false){super(message);this.name='RequestError';}
}
// 408/429 与网关类错误（含 Cloudflare 520–524 回源超时）可重试；后端业务 503 不在其中。
export const RETRY_STATUS=new Set([408,425,429,500,502,504,520,521,522,523,524]);
export const BACKOFF=[800,2500,5000];
export const sleep=(ms:number,signal?:AbortSignal)=>new Promise<void>((resolve,reject)=>{
 if(signal?.aborted){reject(new DOMException('请求已取消','AbortError'));return;}
 const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},ms);
 const stop=()=>{clearTimeout(timer);reject(new DOMException('请求已取消','AbortError'));};
 signal?.addEventListener('abort',stop,{once:true});
});
export const isNetworkSlow=(error:unknown)=>error instanceof RequestError&&(error.timeout||error.status===0||RETRY_STATUS.has(error.status));
export async function fetchJson<T=any>(url:string,{signal,timeout=12000,retries=2,cache}:{signal?:AbortSignal;timeout?:number;retries?:number;cache?:RequestCache}={}):Promise<T>{
 for(let attempt=0;;attempt++){
  const controller=new AbortController(),forward=()=>controller.abort();
  signal?.addEventListener('abort',forward,{once:true});
  let timedOut=false;const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeout);
  let failure:RequestError;
  try{
   const response=await fetch(url,{signal:controller.signal,cache});
   const text=await response.text();let body:any=null;try{body=JSON.parse(text);}catch{/* 非 JSON 时按状态码报错 */}
   if(response.ok)return body as T;
   failure=new RequestError(body?.detail||`请求失败（HTTP ${response.status}）`,response.status);
   if(!RETRY_STATUS.has(response.status))throw failure;
  }catch(error){
   if(signal?.aborted)throw new DOMException('请求已取消','AbortError');
   if(error instanceof RequestError&&!RETRY_STATUS.has(error.status))throw error;
   failure=error instanceof RequestError?error:timedOut?new RequestError('网络较慢，读取超时',0,true):new RequestError('网络连接失败',0);
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',forward);}
  if(attempt>=retries)throw failure;
  await sleep(BACKOFF[Math.min(attempt,BACKOFF.length-1)],signal);
 }
}
