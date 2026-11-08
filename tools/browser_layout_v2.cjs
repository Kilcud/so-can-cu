const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const base=process.env.BASE_URL||'http://127.0.0.1:8765';
const out=path.join(root,'evidence_layout/screenshots');
// QA transport: the browser is sandboxed against navigation. Original UI code
// is rendered locally; every API request is relayed to the real local server.
const http = require('node:http');
function realHTTP(pathname,method='GET',headers={},body=null){
 return new Promise((resolve,reject)=>{
  const target=new URL(pathname,base);
  if(target.origin!==new URL(base).origin)return reject(new Error('QA relay accepts only the local application.'));
  const h={...headers,Host:target.host};
  if(body!=null)h['Content-Length']=Buffer.byteLength(body);
  const req=http.request(target,{method,headers:h},res=>{const parts=[];res.on('data',p=>parts.push(p));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,data:Buffer.concat(parts).toString('base64')}));});
  req.on('error',reject);if(body!=null)req.write(body);req.end();
 });
}
async function bootUI(p){
 await p.exposeBinding('__localHTTP',(_,{url,method,headers,body})=>realHTTP(url,method,headers,body));
 let html=fs.readFileSync(path.join(root,'static/index.html'),'utf8');
 html=html.replace(/<link[^>]*rel="stylesheet"[^>]*>/g,'').replace(/<script[^>]*src=[^>]*><\/script>/g,'');
 await p.setContent(html);
 const font=await realHTTP('/ui-font.css');
 await p.addStyleTag({content:Buffer.from(font.data,'base64').toString('utf8')});
 await p.addStyleTag({content:fs.readFileSync(path.join(root,'static/styles.css'),'utf8')});
 await p.evaluate(()=>{
  window.__qaResponses=[];
  window.fetch=async(url,options={})=>{
   const value=await window.__localHTTP({url:String(url),method:options.method||'GET',headers:options.headers||{},body:options.body||null});
   const bytes=Uint8Array.from(atob(value.data),c=>c.charCodeAt(0));
   const response=new Response(bytes,{status:value.status,headers:value.headers});
   let data=null;try{data=JSON.parse(new TextDecoder().decode(bytes));}catch{}
   window.__qaResponses.push({path:new URL(String(url),'http://127.0.0.1:8765').pathname,method:options.method||'GET',status:value.status,data});
   return response;
  };
 });
 await p.addScriptTag({content:fs.readFileSync(path.join(root,'static/app.js'),'utf8')});
 await p.addScriptTag({content:fs.readFileSync(path.join(root,'static/ui_v2.js'),'utf8')});
}
async function captureRegion(page, name, height) {
 const box=await page.locator('#main').boundingBox();
 if(!box)throw new Error('The main panel is not visible.');
 await page.screenshot({path:path.join(out,name),clip:{x:box.x+35,y:box.y+195,width:962,height},animations:'disabled'});
}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1280,height:1050},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await bootUI(page);await page.locator('#main[aria-busy="false"]').waitFor();
 
 await page.evaluate(()=>go('ingest'));
 await page.getByTestId('import-file').waitFor();
 await page.getByTestId('import-file').setInputFiles(path.join(root,'data/demo_import_v2.docx'));
 await page.getByTestId('import-file-submit').click();
 await page.waitForFunction(()=>window.__qaResponses.some(r=>r.path==='/api/import/file'));
 const imp=await page.evaluate(()=>window.__qaResponses.findLast(r=>r.path==='/api/import/file'));
 assert.equal(imp.status,201);
 await page.locator('#toast-region .toast').waitFor({state:'hidden'});
 await captureRegion(page,'41_v2_import.png',762);
 await page.evaluate(()=>go('rag'));
 await page.getByTestId('rag-question').waitFor();
 await page.getByTestId('rag-question').fill((process.env.RAG_QUESTION||"Khi học liệu thay đổi phiên bản thì căn cứ đang sử dụng cần được xử lý như thế nào?"));
 await page.getByTestId('rag-submit').click();
 await page.waitForFunction(()=>window.__qaResponses.some(r=>r.path==='/api/rag/ask'));
 await page.getByTestId('rag-output').locator('[role="alert"]').waitFor();
 await captureRegion(page,'42_v2_rag_unavailable.png',546);
 const rag=await page.evaluate(()=>window.__qaResponses.findLast(r=>r.path==='/api/rag/ask'));
 assert.notEqual(rag.status,200);
 assert.equal(errors.length,0);
 const result={scope:'Actual UI scripts rendered locally; API requests relayed to real localhost server because direct browser navigation is restricted. No real Ollama models used.',font:'Comfortaa fallback; Nunito not installed in capture environment',docx_import:{status:imp.status,result:imp.data},rag:{status:rag.status,result:rag.data},javascript_errors:errors};
 fs.writeFileSync(path.join(root,'evidence_layout/v2_ui_capture.json'),JSON.stringify(result,null,2));
 await browser.close();console.log('V2 CAPTURE PASS');
})().catch(e=>{console.error(e);process.exit(1)});
