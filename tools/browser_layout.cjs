/* Reproduce the browser evidence against a fresh demo instance.
   NODE_PATH=<Playwright module directory> node tools/browser_layout.cjs
   Optional BASE_URL and CHROMIUM_EXECUTABLE configure the local test browser.
   The workflow creates labelled demonstration records through the actual UI. */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const {chromium} = require("playwright");
const root = path.resolve(__dirname,"..");
const dir = path.join(root,"evidence_layout");
const shots = path.join(dir,"screenshots");
const downloads = path.join(dir,"browser_downloads");
fs.mkdirSync(shots,{recursive:true}); fs.mkdirSync(downloads,{recursive:true});
const base = process.env.BASE_URL || "http://127.0.0.1:8765";
const executablePath = process.env.CHROMIUM_EXECUTABLE;
const cases=[], figures=[], errors=[];
let page, browser, projectId, sourceId, segmentId, factualId, analysisId, proposalId;
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

const started = new Date().toISOString();
const title = "Hồ sơ thực hành — kiểm tra căn cứ theo phiên bản";
const sourceTitle = "Học liệu trình diễn về quản lý phiên bản trích dẫn";
const textV1 = "Căn cứ trích dẫn phải lưu thông tin nguồn, vị trí đoạn và phiên bản được sử dụng. Khi nội dung học liệu thay đổi, người viết cần đọc lại luận điểm và quyết định giữ hoặc thay căn cứ sau khi đối chiếu.";
const textV2 = "Căn cứ trích dẫn phải lưu thông tin nguồn, vị trí đoạn và phiên bản được sử dụng. Khi nội dung học liệu thay đổi, người viết cần đọc lại luận điểm, ghi lý do xử lý và quyết định giữ hoặc thay căn cứ sau khi đối chiếu.";
const by = id => page.getByTestId(id);
async function idle(){await page.locator('#main[aria-busy="false"]').waitFor();}
async function nav(view){await by(`nav-${view}`).click(); await by(`view-${view}`).waitFor(); await idle();}
async function close(){if(await page.locator('#app-dialog').evaluate(e=>e.open))await by("dialog-close").click();}
async function shot(name,title,description,group,locator=null){
  await page.evaluate(()=>document.fonts.ready);
  // Capture stable interface content after any temporary notification expires.
  await page.locator("#toast-region .toast").waitFor({state:"hidden"});
  const filename=`${String(figures.length+1).padStart(2,"0")}_${name}.png`;
  const dest=path.join(shots,filename);
  const side=by("evidence-drawer").locator(".dialog-side");
  const sourceHead=by("source-detail").locator(".detail-heading");
  let regions=null;
  if(["search_accents","search_no_accents","search_filter","retrieval_limit"].includes(name))
    regions=[page.locator(".search-box"),page.locator(".result-card").first()];
  else if(name==="search_empty")regions=[by("search-results")];
  else if(name==="source_law")regions=[sourceHead,by("source-detail").locator(".section-intro").first()];
  else if(name==="source_excerpt"){
    const left=by("evidence-drawer").locator(".dialog-grid > div").first();
    regions=[left.locator(".result-meta").first(),left.locator(".alert.info")];
  }
  else if(name==="source_create_metadata")regions=[by("source-editor").locator(":scope > .form-grid")];
  else if(name==="source_create_segment")regions=[by("segment-editors")];
  else if(name==="source_draft")regions=[sourceHead,by("source-detail").locator(".panel-inner > .alert").first()];
  else if(name==="source_reviewed")regions=[sourceHead,by("source-review-note")];
  else if(name==="source_draft_block")regions=[side.locator(".alert.warning"),by("attach-evidence")];
  else if(name==="quote_rejected")regions=[side.locator(".field").nth(2),by("attach-evidence")];
  else if(name==="quote_ready")regions=[side.locator(".field").first(),side.locator(".field").nth(3)];
  else if(name==="project_empty")regions=[by("project-check")];
  else if(name==="revision_form")regions=[by("source-revision-form").locator(":scope > .alert"),by("segment-editors")];
  else if(name==="attach_version2"){
    const left=by("evidence-drawer").locator(".dialog-grid > div").first();
    regions=[left.locator(".result-meta").first(),left.locator(".metadata-grid")];
  }
  else if(name==="export_html")regions=[page.locator("body > h1"),page.locator("section.claim").first()];
  else if(name==="audit")regions=[by("audit-verification"),by("audit-table").locator("tbody tr").nth(2)];
  else if(name==="guide")regions=[by("guide-start"),by("guide-sources")];
  else if(name==="mobile_overview")regions=[by("view-overview").locator(".page-heading"),by("overview-stats")];
  else if(name==="mobile_project")regions=[by("project-editor").locator(":scope > section.panel").first()];
  let buffer, capture;
  if(regions){
    // These are genuine contiguous screen regions. Only normal scrolling is
    // used to reveal them; no content, styles, labels or data are substituted.
    await regions[0].scrollIntoViewIfNeeded();
    const limits=await regions[0].evaluate(element=>{
      const dialog=element.closest("dialog");
      if(!dialog)return {top:0,bottom:innerHeight};
      const header=dialog.querySelector(".dialog-header");
      const footer=dialog.querySelector(".dialog-footer");
      const box=dialog.getBoundingClientRect();
      return {top:header?header.getBoundingClientRect().bottom:box.top,bottom:footer?footer.getBoundingClientRect().top:box.bottom};
    });
    const viewport=page.viewportSize();
    let bounds;
    for(let attempt=0;attempt<4;attempt++){
      const boxes=await Promise.all(regions.map(region=>region.boundingBox()));
      assert.ok(boxes.every(Boolean),`Missing screenshot region: ${name}`);
      bounds={left:Math.min(...boxes.map(box=>box.x)),top:Math.min(...boxes.map(box=>box.y)),right:Math.max(...boxes.map(box=>box.x+box.width)),bottom:Math.max(...boxes.map(box=>box.y+box.height))};
      const delta=bounds.top<limits.top+4?bounds.top-limits.top-4:bounds.bottom>limits.bottom-4?bounds.bottom-limits.bottom+4:0;
      if(Math.abs(delta)<1)break;
      await regions[0].evaluate((element,dy)=>{
        let parent=element.parentElement;
        while(parent){
          const style=getComputedStyle(parent);
          if(/auto|scroll/.test(style.overflowY)&&parent.scrollHeight>parent.clientHeight){parent.scrollBy(0,dy);return;}
          parent=parent.parentElement;
        }
        window.scrollBy(0,dy);
      },delta);
    }
    assert.ok(bounds.top>=limits.top-1&&bounds.bottom<=limits.bottom+1,`Screenshot region does not fit visible content: ${name} ${JSON.stringify(bounds)} ${JSON.stringify(limits)}`);
    const x=Math.max(0,Math.floor(bounds.left)-4),y=Math.max(Math.ceil(limits.top),Math.floor(bounds.top)-4);
    const right=Math.min(viewport.width,Math.ceil(bounds.right)+4),bottom=Math.min(Math.floor(limits.bottom),Math.ceil(bounds.bottom)+4);
    buffer=await page.screenshot({path:dest,clip:{x,y,width:right-x,height:bottom-y},animations:"disabled"});
    capture="functional_region";
  }else if(locator){buffer=await locator.screenshot({path:dest,animations:"disabled"});capture="element";}
  else {await page.evaluate(()=>window.scrollTo(0,0));buffer=await page.screenshot({path:dest,fullPage:false,animations:"disabled"});capture="overview_viewport";}
  figures.push({path:`evidence_layout/screenshots/${filename}`,title,description,group,pixel_width:buffer.readUInt32BE(16),pixel_height:buffer.readUInt32BE(20),capture});
}
async function step(id,title,fn){
  const t=Date.now();
  try {await fn();cases.push({id,title,status:"passed",duration_ms:Date.now()-t}); console.log(`${id} PASS ${title}`);}
  catch(e){cases.push({id,title,status:"failed",duration_ms:Date.now()-t,error:e.message});throw e;}
}
async function search(q){await by("search-query").fill(q);await by("search-submit").click();await by("search-submit").waitFor({state:"visible"});await page.waitForFunction(()=>!document.querySelector('[data-testid="search-submit"]').disabled);await by("search-results").locator('.results-head').waitFor();}
async function jsonGet(url){const r=await realHTTP(url);assert.equal(r.status,200);return JSON.parse(Buffer.from(r.data,'base64').toString('utf8'));}
async function mutation(action,pathname,method="POST"){
 const n=await page.evaluate(()=>window.__qaResponses.length);
 await action();
 await page.waitForFunction(({n,p,m})=>window.__qaResponses.slice(n).some(r=>r.path===p&&r.method===m),{n,p:pathname,m:method});
 const r=await page.evaluate(({n,p,m})=>window.__qaResponses.slice(n).find(r=>r.path===p&&r.method===m),{n,p:pathname,m:method});
 assert.ok(r.status<300,JSON.stringify(r.data));await page.locator('#app-dialog').waitFor({state:'hidden'});await idle();return r.data;
}
async function selectProject(id){await nav("projects");await by(`project-${id}`).click();await by("project-editor").locator('h2').filter({hasText:title}).waitFor();await by("project-check").waitFor();}
async function selectSource(id){await nav("sources");await by(`source-${id}`).click();await by("source-detail").locator('h2').filter({hasText:sourceTitle}).waitFor();}
async function download(format,id){
 await by("export-format").selectOption(format);
 const pending=page.waitForEvent("download");await by("export-project").click();
 const check=await jsonGet(`/api/projects/${id}/check`);
 if(check.issues.length)await by("confirm-action").click();
 const d=await pending;const dest=path.join(downloads,`project_${format}.${format==='markdown'?'md':format}`);await d.saveAs(dest);assert.ok(fs.statSync(dest).size>0);return dest;
}
async function main(){
 browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{}),args:["--no-sandbox"]});
 page=await browser.newPage({viewport:{width:1280,height:1100},deviceScaleFactor:1,timezoneId:"Asia/Ho_Chi_Minh",acceptDownloads:true});
 page.on("pageerror",e=>errors.push(e.message));
 await bootUI(page);await idle();
 await step("B01","Mở trang và kiểm tra tổng quan",async()=>{
   const b=await jsonGet("/api/bootstrap");assert.ok(b.sources.length>=5);assert.ok(b.projects.length>=1);
   await shot("overview","Không gian làm việc và tổng quan dữ liệu","Màn hình đầu tiên hiển thị số nguồn, hồ sơ, luận điểm và vấn đề cần xem lại trong kho đang mở. Dữ liệu ban đầu thuộc bộ thực hành của bản mẫu. Các số đếm giúp người dùng chọn việc cần xử lý; chúng không phải số liệu hoạt động của Học viện. Nút tạo hồ sơ và đường dẫn tra cứu đưa người dùng vào hai công việc chính.","overview");
   await shot("overview_counts","Các chỉ số theo trạng thái hiện tại của kho","Vùng thống kê được chụp cận cảnh để đọc rõ nhãn và số liệu. Chỉ số vấn đề cần xem lại được tính từ phép kiểm tra căn cứ kỹ thuật. Một luận điểm không có cảnh báo kỹ thuật vẫn cần được kiểm tra về nội dung và ý nghĩa. Kết quả đếm được lấy lại từ máy chủ khi mở tổng quan; đây không phải bảng theo dõi hiệu quả hay thành tích sử dụng.","overview",by("overview-stats"));
 });
 await step("B02","Tra cứu có dấu, không dấu và giới hạn nguồn",async()=>{
   await nav("search");await search("liêm chính khoa học");assert.ok(await page.locator('.result-card').count()>0);
   const accented=await page.locator('.result-card').first().getAttribute('data-testid');
   await shot("search_accents","Tra cứu từ khóa có dấu và đọc kết quả","Truy vấn được gửi tới kho học liệu cục bộ và trả về các đoạn có mức khớp từ khóa phù hợp. Mỗi kết quả kèm trạng thái đối chiếu, tính chất văn bản, vị trí và phiên bản. Người dùng phải mở đoạn để đọc trước khi sử dụng. Thứ tự kết quả chỉ là thứ tự truy hồi của thuật toán; hệ thống không xác nhận đoạn đứng đầu đủ để kết luận về câu hỏi nghiên cứu.","search");
   await search("liem chinh khoa hoc");assert.equal(await page.locator('.result-card').first().getAttribute('data-testid'),accented);
   await shot("search_no_accents","Tra cứu cùng nội dung bằng chữ không dấu","Ảnh ghi nhận truy vấn không dấu trên cùng kho dữ liệu. Phép kiểm tra trình duyệt đối chiếu mã kết quả đầu tiên với truy vấn có dấu ở bước trước. Khả năng chuẩn hóa chữ giúp giảm trở ngại nhập liệu nhưng không thực hiện suy luận ngữ nghĩa. Người dùng vẫn cần chọn thuật ngữ đủ gần nội dung trong nguồn và kiểm tra các đoạn được trả về.","search");
   await by("search-source").selectOption("src-khcn93");await page.waitForFunction(()=>!document.querySelector('[data-testid="search-submit"]').disabled);assert.ok(await page.locator('.result-card').count()>0);
   await shot("search_filter","Giới hạn tìm kiếm trong một nguồn","Bộ chọn phạm vi thu hẹp truy vấn vào một tài liệu cụ thể. Việc đổi bộ lọc gửi lại truy vấn để kết quả và nhãn phạm vi thống nhất. Hình chụp cho thấy người dùng có thể đọc các đoạn thuộc nguồn đã chọn thay vì duyệt toàn kho. Phạm vi này chỉ bao gồm những đoạn đã nhập; nó không thay thế việc tìm kiếm toàn văn tài liệu gốc.","search");
 });
 await step("B03","Trả trạng thái rỗng cho nội dung ngoài kho",async()=>{
   await by("search-source").selectOption("");await page.waitForFunction(()=>!document.querySelector('[data-testid="search-submit"]').disabled);await search("liều amoxicillin trẻ em");assert.equal(await page.locator('.result-card').count(),0);
   await shot("search_empty","Thông báo khi kho không có đoạn phù hợp","Ứng dụng trả trạng thái không tìm thấy đoạn phù hợp đối với truy vấn ngoài phạm vi học liệu. Thông báo hướng dẫn điều chỉnh từ khóa hoặc phạm vi, đồng thời không suy diễn rằng nội dung đó không tồn tại trong tài liệu gốc. Đây là tình huống kiểm tra khả năng trả rỗng, không phải chức năng tư vấn về lĩnh vực được nêu trong câu truy vấn.","search");
 });
 await step("B04","Đọc nguồn pháp luật tóm lược và chỉ dẫn nguồn gốc",async()=>{
   await nav("sources");await by("source-src-nd125").click();await by("source-segment-seg-nd125-01").waitFor();
   await shot("source_law","Thông tin xuất xứ và các đoạn học liệu đang lưu","Nguồn pháp luật có tên tài liệu, cơ quan ban hành, số hiệu, ngày, đường dẫn và số đoạn đã lưu. Nhãn bản tóm lược được hiển thị để phân biệt nội dung diễn đạt lại với nguyên văn. Phần ghi nhận đối chiếu thuộc phiên bản hiện tại của kho thực hành. Các thông tin này giúp tìm lại tài liệu, không tạo ra xác nhận chính thức của cơ quan ban hành.","sources");
   await by("cite-segment-seg-nd125-01").click();await by("evidence-drawer").locator('.dialog-grid').waitFor();assert.ok(await by("evidence-drawer").getByText("Đây là bản tóm lược học liệu.",{exact:false}).count());
   await shot("source_excerpt","Cửa sổ đọc đoạn và cảnh báo về bản tóm lược","Vùng đọc nguồn được chụp riêng, gồm nội dung học liệu, xuất xứ và cảnh báo về bản tóm lược. Dòng lưu ý yêu cầu mở tài liệu gốc khi cần trích nguyên văn quy định. Người dùng có thể rút ngắn đoạn liên tục nhưng không được sửa câu chữ trong ô trích. Ghi chú sử dụng được lưu riêng để tránh lẫn lời của người viết với nội dung nguồn.","sources",page.locator('#app-dialog'));
   await close();
 });
 await step("B05","Tạo nguồn thực hành ở trạng thái chưa đối chiếu",async()=>{
   await by("create-source").click();await by("source-title").fill(sourceTitle);await by("source-issuer").fill("Học liệu tự biên soạn cho kịch bản trình diễn");await by("source-number").fill("DEMO-PHIENBAN-01");await by("source-date").fill("2026-10-26");await by("source-kind").selectOption("learning_note");await by("source-text-kind").selectOption("original");await by("segment-title").fill("Quản lý căn cứ theo phiên bản");await by("segment-locator").fill("Mục 1");await by("segment-text").fill(textV1);
   await shot("source_create_metadata","Biểu mẫu ghi nhận xuất xứ nguồn mới","Nguồn trong kịch bản là học liệu tự biên soạn phục vụ trình diễn nên trường cơ quan hoặc tác giả nêu rõ tính chất này. Người nhập chọn loại nguồn, tính chất nội dung và mã học liệu trước khi lưu. Việc chọn nguyên văn ở đây chỉ mô tả đoạn tự biên soạn được nhập đúng chữ; không gắn nguồn thực hành với thẩm quyền của một cơ quan nhà nước.","sources",page.locator('#app-dialog'));
   await shot("source_create_segment","Cấu trúc nhập từng đoạn học liệu","Mỗi đoạn có tiêu đề, vị trí và nội dung riêng. Cách nhập theo đoạn cho phép gắn căn cứ với vị trí cụ thể thay vì chỉ ghi tên tài liệu chung. Bộ kiểm tra phía máy chủ kiểm soát giới hạn ký tự và sự trùng vị trí trong một phiên bản. Bản mẫu chưa thực hiện nhận dạng ký tự hoặc trích xuất tự động từ tệp PDF; người dùng chịu trách nhiệm về nội dung đã nhập.","sources",by("segment-editors"));
   const d=await mutation(()=>by("save-source").click(),"/api/sources");sourceId=d.source.id;const s=await jsonGet(`/api/sources/${sourceId}`);segmentId=s.segments[0].id;assert.equal(s.source.status,"draft");
   await by(`source-${sourceId}`).click();await by("review-source").waitFor();
   await shot("source_draft","Nguồn mới được lưu ở trạng thái chưa đối chiếu","Sau khi lưu, phần chi tiết nguồn hiển thị trạng thái chưa đối chiếu. Phần mô tả giải thích rằng nội dung có thể được đọc khi bỏ bộ lọc nhưng chưa được gắn thành căn cứ mới. Quy tắc này ngăn việc bỏ qua bước kiểm tra nguồn trong quy trình sử dụng thông thường. Nó không chứng minh người dùng đã đọc đúng tài liệu sau khi tự ghi nhận đối chiếu.","sources");
 });
 await step("B06","Chặn thao tác gắn căn cứ từ nguồn chưa đối chiếu",async()=>{
   await by(`cite-segment-${segmentId}`).click();await by("attach-evidence").waitFor();assert.equal(await by("attach-evidence").isDisabled(),true);
   await shot("source_draft_block","Nút gắn căn cứ bị khóa khi nguồn chưa đối chiếu","Cửa sổ vẫn cho đọc đoạn thực hành, đồng thời hiển thị lý do chưa thể gắn căn cứ. Nút thao tác bị vô hiệu hóa trong giao diện; bộ kiểm thử HTTP và lớp lưu trữ kiểm tra thêm việc từ chối ở phía máy chủ. Vì vậy, trạng thái này không chỉ dựa vào màu nhãn. Người dùng phải quay lại quản lý nguồn và hoàn thành bước đối chiếu cho phiên bản hiện hành.","sources",page.locator('#app-dialog'));
   await close();
 });
 await step("B07","Ghi nhận tự đối chiếu cho phiên bản thứ nhất",async()=>{
   await by("review-source").click();await by("review-note").fill("Đối chiếu với đoạn thực hành được nhập trong kịch bản trình diễn; kiểm tra đủ hai câu, đúng vị trí Mục 1 và ghi rõ đây là học liệu tự biên soạn.");await by("review-confirm").check();
   await shot("source_review","Biểu mẫu ghi nội dung đã đối chiếu","Hộp thoại yêu cầu ghi phạm vi đã kiểm tra và xác nhận đã đọc nguồn phù hợp. Thông báo trong biểu mẫu nêu rõ đây là việc tự đối chiếu của người dùng, không thay thế thẩm định độc lập. Trong kịch bản này, đối tượng kiểm tra là đoạn thực hành do kịch bản nhập vào. Bằng chứng thao tác chỉ chứng minh ứng dụng lưu đúng quy trình, không đánh giá chất lượng thẩm định của một đơn vị.","sources",page.locator('#app-dialog'));
   await mutation(()=>by("save-source-review").click(),`/api/sources/${sourceId}/review`);assert.equal((await jsonGet(`/api/sources/${sourceId}`)).source.status,"reviewed");await by("source-review-note").waitFor();
   await shot("source_reviewed","Ghi nhận đối chiếu được hiển thị theo phiên bản","Nguồn chuyển sang trạng thái đã đối chiếu và hiển thị nội dung ghi nhận. Đoạn học liệu lúc này đủ điều kiện kỹ thuật để gắn vào luận điểm. Khi tạo phiên bản mới, trạng thái sẽ trở về chưa đối chiếu; phần ghi nhận ở bước này không tự chuyển thành xác nhận cho nội dung đã sửa. Quy tắc tách phiên bản được kiểm tra tiếp ở chuỗi thao tác quản lý thay đổi.","sources",by("source-detail").locator('section.panel').first());
 });
 await step("B08","Tạo hồ sơ và hiển thị cảnh báo hồ sơ trống",async()=>{
   await nav("projects");await by("create-project").click();await by("project-title").fill(title);await by("project-description").fill("Hồ sơ mô phỏng để kiểm tra việc gắn căn cứ, thay phiên bản học liệu, giữ cảnh báo và xuất dữ liệu. Không phải kết quả triển khai tại Học viện.");
   await shot("project_create","Xác định mục đích và phạm vi hồ sơ","Hồ sơ được đặt tên theo nhiệm vụ thực hành và ghi rõ phạm vi kiểm tra. Phần mô tả ngăn việc hiểu dữ liệu trình diễn thành kết quả sử dụng thực tế. Một hồ sơ có thể chứa nhiều luận điểm nhưng cần giữ mục đích thống nhất để người đọc biết từng căn cứ đang phục vụ nội dung nào. Tên và mô tả có thể sửa sau khi tạo mà không làm thay đổi đoạn nguồn đã lưu.","projects",page.locator('#app-dialog'));
   const d=await mutation(()=>by("save-project").click(),"/api/projects");projectId=d.project.id;await by("issue-EMPTY_PROJECT").waitFor();
   await shot("project_empty","Cảnh báo đối với hồ sơ chưa có luận điểm","Ngay sau khi tạo, hồ sơ chưa có nội dung lập luận và xuất hiện cảnh báo EMPTY_PROJECT. Thông báo đi cùng nút thêm luận điểm để chỉ ra bước tiếp theo. Cảnh báo này cũng được giữ trong các định dạng xuất; bộ kiểm thử tự động có phép thử riêng cho trường hợp hồ sơ trống. Giao diện không dùng trạng thái không có lỗi trích dẫn để đánh đồng một hồ sơ trống với hồ sơ đã hoàn thiện.","projects");
 });
 await step("B09","Tạo ba loại luận điểm và phân biệt yêu cầu căn cứ",async()=>{
   const specs=[['factual',"Học liệu thực hành yêu cầu lưu nguồn, vị trí đoạn và phiên bản được sử dụng cho mỗi căn cứ trích dẫn."],['analysis',"Việc giữ lại phiên bản đã sử dụng giúp người viết kiểm tra lý do thay đổi căn cứ trong quá trình sửa hồ sơ."],['proposal',"Đề xuất tổ chức một buổi thực hành có nhiệm vụ sửa nguồn để người học tự xử lý cảnh báo phiên bản."]];
   const ids=[];
   for(const [type,text] of specs){await by("add-claim").click();await by("claim-type").selectOption(type);await by("claim-text").fill(text);
     if(type==='factual')await shot("claim_form","Nhập luận điểm và xác định loại nội dung","Biểu mẫu yêu cầu chọn nhận định thực tế, phân tích hoặc đề xuất. Dòng hướng dẫn giải thích rằng việc đổi nhãn không làm một nhận định thực tế trở thành đúng. Trong kịch bản, nhận định thực tế chỉ mô tả nội dung của học liệu thực hành, không suy rộng thành quy định chung. Phân loại hỗ trợ đặt mức cảnh báo nhưng vẫn cần sự tự giác và đánh giá nội dung của người viết.","projects",page.locator('#app-dialog'));
     const d=await mutation(()=>by("save-claim").click(),`/api/projects/${projectId}/claims`);ids.push(d.claim.id);
   }
   [factualId,analysisId,proposalId]=ids;const check=await jsonGet(`/api/projects/${projectId}/check`);assert.equal(check.issues.filter(x=>x.code==='MISSING_EVIDENCE').length,2);
   await shot("claim_missing","Phân biệt lỗi, cảnh báo và đề xuất chưa gắn căn cứ","Sau khi thêm ba loại luận điểm, phần kiểm tra ghi nhận nhận định thực tế thiếu căn cứ là lỗi, phân tích thiếu căn cứ là nội dung cần xem lại. Đề xuất được giữ như ý kiến của người viết và có thể bổ sung căn cứ giải thích lựa chọn. Cơ chế này thể hiện chính sách kiểm tra của bản mẫu, không tự nhận diện nội dung bị phân loại sai.","projects",by("project-check"));
   await shot("claim_proposal","Thẻ đề xuất và giới hạn của việc phân loại","Thẻ đề xuất nêu rõ đây là ý kiến của người viết và cho phép bổ sung căn cứ khi cần. Nút sửa, xóa và tìm căn cứ nằm ngay trong phạm vi thẻ để giảm nhầm đích thao tác. Số căn cứ hiển thị là số liên kết đã lưu; số lượng nhiều không đồng nghĩa lập luận có chất lượng cao. Người dùng phải giải thích vai trò của từng nguồn khi hoàn thiện bài viết.","projects",by(`claim-${proposalId}`));
 });
 await step("B10","Từ chối đoạn trích bị sửa câu chữ",async()=>{
   await selectSource(sourceId);await by(`cite-segment-${segmentId}`).click();await by("attach-project").selectOption(projectId);await by("attach-claim").locator(`option[value="${factualId}"]`).waitFor({state:"attached"});await by("attach-claim").selectOption(factualId);await by("evidence-quote").fill("Đây là câu được sửa để kiểm tra việc từ chối trích dẫn không khớp.");await by("attach-evidence").click();await page.locator('#app-dialog .form-error.error').waitFor();assert.equal((await jsonGet(`/api/projects/${projectId}`)).claims.find(c=>c.id===factualId).evidence.length,0);
   await shot("quote_rejected","Thông báo từ chối đoạn trích không khớp","Kịch bản cố ý thay toàn bộ nội dung ô trích bằng một câu không có trong đoạn học liệu. Máy chủ từ chối yêu cầu và giao diện giữ biểu mẫu để người dùng sửa. Hồ sơ được đọc lại để xác nhận chưa có căn cứ mới được tạo. Cơ chế chỉ kiểm tra sự khớp của đoạn trích với nội dung đã lưu; nó không phát hiện được một đoạn khớp chữ nhưng được dùng sai ý nghĩa.","projects",page.locator('#app-dialog'));
 });
 await step("B11","Gắn căn cứ hợp lệ và lưu thông tin nguồn",async()=>{
   await by("evidence-quote").fill(textV1);await by("evidence-note").fill("Đoạn thực hành trực tiếp nêu ba thành phần cần lưu. Nhận định chỉ áp dụng cho nội dung học liệu này.");
   await shot("quote_ready","Chọn đúng luận điểm và ghi riêng lý do sử dụng","Vùng nhập được chụp sau khi sửa ô trích về nguyên văn đoạn đang lưu và trước khi gửi lại. Người dùng kiểm tra hồ sơ, luận điểm đích và ghi chú; đây chưa phải thông báo lưu thành công. Ghi chú nêu phần nội dung mà nguồn hỗ trợ, đồng thời giới hạn phạm vi kết luận. Các trường lựa chọn đích được tải từ dữ liệu hồ sơ thực; kịch bản chờ đúng luận điểm xuất hiện trước khi gắn. Đây là bước cần thiết để tránh gắn nguồn đúng vào một luận điểm khác.","projects",page.locator('#app-dialog'));
   await mutation(()=>by("attach-evidence").click(),`/api/claims/${factualId}/evidence`);const p=await jsonGet(`/api/projects/${projectId}`);assert.equal(p.claims.find(c=>c.id===factualId).evidence[0].quote,textV1);
   await shot("evidence_saved","Căn cứ được hiển thị trong thẻ luận điểm","Thẻ luận điểm giữ đoạn trích, tên học liệu, vị trí Mục 1, phiên bản và ghi chú sử dụng. Thông tin được đọc lại từ máy chủ sau khi lưu, không chỉ thêm tạm vào giao diện. Nút bỏ căn cứ xóa liên kết khỏi luận điểm nhưng không xóa nguồn học liệu. Bản chụp cho phép đối chiếu nội dung trước và sau khi nguồn được sửa trong các bước tiếp theo.","projects",by(`claim-${factualId}`));
   await selectSource(sourceId);await by(`cite-segment-${segmentId}`).click();await by("attach-project").selectOption(projectId);await by("attach-claim").locator(`option[value="${analysisId}"]`).waitFor({state:"attached"});await by("attach-claim").selectOption(analysisId);await by("evidence-note").fill("Dùng làm cơ sở giải thích quy trình; người viết vẫn phải kiểm tra tính phù hợp của lập luận phân tích.");await mutation(()=>by("attach-evidence").click(),`/api/claims/${analysisId}/evidence`);
   assert.equal((await jsonGet(`/api/projects/${projectId}/check`)).issues.length,0);
   await shot("checks_clear","Hồ sơ không còn cảnh báo kỹ thuật tại phiên bản đầu","Sau khi bổ sung căn cứ cho nhận định thực tế và phân tích, hệ thống không còn ghi nhận lỗi trong phạm vi kiểm tra kỹ thuật. Phần mô tả trên màn hình vẫn yêu cầu người viết tiếp tục đối chiếu ý nghĩa với luận điểm. Kết quả này không phải điểm chất lượng, xác nhận pháp lý hoặc chứng nhận hoàn thành nghiên cứu. Nó chỉ phản ánh các điều kiện kỹ thuật đã được kiểm tra tại thời điểm chụp.","projects",by("project-check"));
 });
 await step("B12","Tạo phiên bản mới và giữ căn cứ cũ",async()=>{
   await selectSource(sourceId);await by("revise-source").click();await by("revision-note").fill("Bổ sung yêu cầu ghi lý do xử lý căn cứ để trình diễn việc thay đổi nội dung nguồn.");await by("segment-text").fill(textV2);
   await shot("revision_form","Ghi lý do tạo phiên bản và nội dung sửa","Kịch bản bổ sung cụm yêu cầu ghi lý do xử lý vào đoạn thực hành. Hộp thoại nêu rõ phiên bản mới trở về trạng thái chưa đối chiếu và các căn cứ cũ sẽ cần xem lại. Người dùng nhập lý do thay đổi trước khi lưu. Việc ghi lý do giúp giải thích quá trình sửa học liệu, nhưng bản mẫu không đánh giá lý do đó có đầy đủ hoặc có được người khác phê duyệt hay chưa.","versions",page.locator('#app-dialog'));
   await mutation(()=>by("save-source-revision").click(),`/api/sources/${sourceId}/revise`);const s=await jsonGet(`/api/sources/${sourceId}`);assert.equal(s.source.version,2);assert.equal(s.source.status,"draft");segmentId=s.segments[0].id;
   await shot("version_history","Lịch sử hai phiên bản của học liệu","Khung lịch sử ghi nhận phiên bản trước và phiên bản mới, lý do thay đổi và giá trị kiểm tra nội dung. Phần căn cứ đang gắn không tự chuyển sang đoạn mới. Lịch sử này tạo điều kiện đối chiếu thao tác trong kho cục bộ; người có toàn quyền sửa cơ sở dữ liệu vẫn có thể can thiệp vào lịch sử, vì vậy cần kết hợp bản sao và trách nhiệm quản lý khi sử dụng thực tế.","versions",by("source-versions"));
   await selectProject(projectId);const p=await jsonGet(`/api/projects/${projectId}`);assert.equal(p.claims.find(c=>c.id===factualId).evidence[0].quote,textV1);const c=await jsonGet(`/api/projects/${projectId}/check`);assert.ok(c.issues.some(x=>x.code==='SOURCE_CHANGED'));
   await shot("stale_warning","Cảnh báo khi nguồn đã chuyển sang phiên bản mới","Sau khi nguồn đổi, phần kiểm tra hiển thị cảnh báo cho các luận điểm còn dùng căn cứ từ phiên bản trước. Kịch bản đọc lại dữ liệu để xác nhận đoạn trích cũ vẫn được giữ nguyên. Người viết có thể cần sửa luận điểm, gắn đoạn mới hoặc giữ căn cứ lịch sử với giải thích phù hợp. Ứng dụng không tự quyết định thay đổi nội dung lập luận.","versions",by("project-check"));
 });
 await step("B13","Đối chiếu phiên bản mới không tự xóa cảnh báo cũ",async()=>{
   await selectSource(sourceId);await by("review-source").click();await by("review-note").fill("Đối chiếu bản thực hành thứ hai với nội dung sửa đã ghi; xác nhận cụm bổ sung về lý do xử lý và vị trí Mục 1.");await by("review-confirm").check();await mutation(()=>by("save-source-review").click(),`/api/sources/${sourceId}/review`);
   await selectProject(projectId);const c=await jsonGet(`/api/projects/${projectId}/check`);assert.ok(c.issues.some(x=>x.code==='SOURCE_CHANGED'));
   await shot("stale_after_review","Cảnh báo phiên bản cũ vẫn còn sau khi đối chiếu bản mới","Đối chiếu bản mới chỉ xác lập trạng thái cho nguồn hiện hành. Các căn cứ đã gắn ở phiên bản trước vẫn giữ thông tin riêng và tiếp tục có cảnh báo. Hình này phân biệt hai công việc: kiểm tra học liệu mới và xem lại cách sử dụng học liệu trong từng luận điểm. Người dùng phải thực hiện bước thứ hai nếu muốn hồ sơ phản ánh căn cứ mới.","versions",by("project-check"));
 });
 await step("B14","Gắn bản mới rồi bỏ liên kết cũ theo từng luận điểm",async()=>{
   for(const [index,cid] of [factualId,analysisId].entries()){
     const before=await jsonGet(`/api/projects/${projectId}`);const old=before.claims.find(c=>c.id===cid).evidence[0].id;
     await selectSource(sourceId);await by(`cite-segment-${segmentId}`).click();await by("attach-project").selectOption(projectId);await by("attach-claim").locator(`option[value="${cid}"]`).waitFor({state:"attached"});await by("attach-claim").selectOption(cid);await by("evidence-note").fill("Đã đọc bản thứ hai và thay liên kết cũ sau khi kiểm tra phạm vi của luận điểm.");
     if(index===0)await shot("attach_version2","Chọn căn cứ từ phiên bản thứ hai","Vùng đọc nguồn cho biết phiên bản thứ hai, nội dung đã sửa và xuất xứ trước khi tạo liên kết mới. Người dùng cần đọc lại đoạn và xác định lý do thay căn cứ. Việc gắn bản mới được thực hiện trước khi bỏ bản cũ để còn cơ sở so sánh trong hồ sơ. Hai liên kết cùng tồn tại tạm thời là trạng thái trung gian của thao tác xử lý, không phải lỗi nhân đôi tự động.","versions",page.locator('#app-dialog'));
     await mutation(()=>by("attach-evidence").click(),`/api/claims/${cid}/evidence`);await by(`delete-evidence-${old}`).click();
     if(index===0)await shot("remove_old_evidence","Xác nhận bỏ liên kết căn cứ cũ","Hộp thoại nêu rõ phạm vi xóa chỉ là liên kết căn cứ trong luận điểm. Nguồn và các phiên bản vẫn được giữ trong kho. Kịch bản chỉ xác nhận sau khi đã gắn căn cứ mới và đọc lại nội dung. Đây là thao tác có ý nghĩa học thuật do người dùng quyết định; thông báo của phần mềm không thay thế việc giải thích tại sao căn cứ cũ không còn phù hợp.","versions",page.locator('#app-dialog'));
     await mutation(()=>by("confirm-action").click(),`/api/evidence/${old}`,"DELETE");
   }
   assert.equal((await jsonGet(`/api/projects/${projectId}/check`)).issues.length,0);
   await shot("version_resolved","Hồ sơ sau khi xử lý các liên kết phiên bản cũ","Phần kiểm tra không còn cảnh báo sau khi từng luận điểm được gắn căn cứ mới và bỏ liên kết cũ. Chuỗi thao tác đã kiểm tra cả việc giữ nguyên bản cũ, phát sinh cảnh báo và xử lý bằng quyết định của người viết. Kết quả đạt chỉ áp dụng cho hồ sơ trình diễn này; không cho phép suy rộng tỷ lệ lỗi giảm hoặc thời gian tiết kiệm trong một lớp học chưa được đo.","versions",by("project-check"));
 });
 await step("B15","Xuất HTML, Markdown và JSON từ hồ sơ đã xử lý",async()=>{
   const html=await download('html',projectId);const md=await download('markdown',projectId);const json=await download('json',projectId);
   assert.ok(fs.readFileSync(html,'utf8').includes(title));assert.ok(fs.readFileSync(md,'utf8').includes(textV2));const data=JSON.parse(fs.readFileSync(json,'utf8'));assert.ok(data);
   const exportPage=await browser.newPage({viewport:{width:1100,height:960}});await exportPage.setContent(fs.readFileSync(html,"utf8"));const original=page;page=exportPage;
   await shot("export_html","Bản HTML do sản phẩm xuất để đọc hoặc in","Hình được chụp từ tệp HTML tải trực tiếp bằng nút xuất của ứng dụng. Bản xuất giữ nội dung luận điểm, đoạn trích, thông tin nguồn và trạng thái kiểm tra tại thời điểm tạo tệp. Người dùng có thể mở bằng trình duyệt để đọc hoặc in. Tệp này không tự cập nhật khi kho học liệu thay đổi; khi cần trạng thái mới phải kiểm tra hồ sơ và xuất lại.","export");
   page=original;await exportPage.close();
 });
 await step("B16","Giữ cảnh báo khi xuất hồ sơ mẫu chưa hoàn thiện",async()=>{
   const data=await jsonGet('/api/projects');const demo=data.projects.find(p=>p.id!==projectId);assert.ok(demo);await nav('projects');await by(`project-${demo.id}`).click();await by('project-check').waitFor();await by('export-format').selectOption('html');await by('export-project').click();await by('confirm-action').waitFor();
   await shot("export_warning","Xác nhận xuất kèm các cảnh báo còn tồn tại","Hồ sơ thực hành ban đầu còn vấn đề cần xem lại nên ứng dụng yêu cầu xác nhận trước khi tải tệp. Nội dung hộp thoại giải thích rằng cảnh báo được giữ trong bản xuất để tiếp tục kiểm tra. Chức năng này hỗ trợ bàn giao hoặc sửa bản nháp, không hợp thức hóa hồ sơ chưa hoàn thiện. Việc xuất thành công không làm thay đổi trạng thái kiểm tra của hồ sơ đang lưu.","export",page.locator('#app-dialog'));
   const pending=page.waitForEvent('download');await by('confirm-action').click();const d=await pending;const dest=path.join(downloads,'project_with_warnings.html');await d.saveAs(dest);const txt=fs.readFileSync(dest,'utf8');assert.ok(txt.includes('MISSING_EVIDENCE'));await close();
 });
 await step("B17","Kiểm tra nhật ký và tải bản sao dữ liệu",async()=>{
   await nav('audit');const audit=await jsonGet('/api/audit');assert.equal(audit.verification.valid,true);
   await shot("audit","Nhật ký thao tác sau chuỗi thực hành","Màn hình nhật ký hiển thị các thao tác tạo nguồn, đối chiếu, sửa phiên bản, thêm luận điểm và thay liên kết căn cứ. Phần xác minh kiểm tra chuỗi giá trị trên toàn bộ nhật ký, trong khi bảng chỉ liệt kê số bản ghi gần đây theo phạm vi giao diện. Dòng giới hạn về người có toàn quyền sửa dữ liệu được giữ trên màn hình để tránh hiểu chuỗi băm thành cơ chế chống sửa tuyệt đối.","audit");
   await by('audit-table').locator('details').first().locator('summary').click();
   await shot("audit_hashes","Giá trị liên kết của một bản ghi nhật ký","Vùng mở rộng cho phép đọc giá trị của bản ghi hiện tại và giá trị liên kết trước đó. Những giá trị này phục vụ kiểm tra tính nhất quán của chuỗi ghi nhận. Chúng không xác định danh tính độc lập của người thao tác vì bản mẫu dùng một người trên máy cục bộ. Khi cần chứng cứ ngoài kho đang sử dụng, phải giữ bản sao hoặc mốc kiểm tra ở vị trí quản lý khác.","audit",by('audit-table').locator('tbody tr').first());
   const pending=page.waitForEvent('download');await by('download-backup').click();const d=await pending;await d.saveAs(path.join(downloads,'so_can_cu_demo_backup.zip'));assert.ok(fs.statSync(path.join(downloads,'so_can_cu_demo_backup.zip')).size>1000);
   await by('verify-audit').click();await by('audit-verification').waitFor();
   await shot("audit_verified","Thông báo kết quả xác minh chuỗi nhật ký","Thông báo ghi số bản ghi đã được kiểm tra trong lần thực hiện và trạng thái khớp của chuỗi. Tệp sao lưu đã được tải trong cùng kịch bản để kiểm tra riêng cấu trúc và cơ sở dữ liệu. Đây là hai phép kiểm tra liên quan nhưng khác phạm vi: màn hình kiểm tra chuỗi nhật ký, còn công cụ kiểm bản sao đọc tệp tải về và các thành phần bên trong.","audit",by('audit-verification'));
 });
 await step("B18","Hướng dẫn và thao tác bàn phím",async()=>{
   await nav('guide');assert.equal(await page.locator('.help-card').count(),8);
   await shot("guide","Các bước khởi đầu trong hướng dẫn sử dụng","Hai khung đầu của trang hướng dẫn được chụp cận cảnh, trình bày cách tạo hồ sơ và ghi nhận nguồn trong quy trình sáu bước. Mỗi bước có mô tả, thứ tự thao tác và đường dẫn đến chức năng liên quan. Nội dung hướng dẫn dùng đúng khả năng của phiên bản hiện hành; các chức năng như nhận dạng PDF, tài khoản tập thể hay phê duyệt nhiều cấp không được trình bày như đã có.","guide");
   await shot("guide_scope","Phạm vi sử dụng và ý nghĩa các trạng thái","Khung phạm vi nhắc người dùng rằng ứng dụng chạy cục bộ cho một người và trạng thái đối chiếu là ghi nhận của chính người dùng. Nhãn trạng thái có chữ mô tả bên cạnh màu để giảm lệ thuộc vào nhận biết màu sắc. Học liệu tóm lược, nguồn chưa đối chiếu và nguồn đã đối chiếu được giải thích trong cùng khu vực nhằm hỗ trợ diễn giải đúng kết quả ở các màn hình khác.","guide",by('guide-scope'));
   await nav('projects');await by('create-project').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#app-dialog').evaluate(e=>e.open),false);
   await page.locator('.skip-link').focus();await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>document.activeElement.id),'main');assert.equal(new URL(page.url()).hash,'#projects');
 });
 await step("B19","Quan sát trường hợp truy hồi bổ sung chưa đạt",async()=>{
   await nav('search');await search('biên soạn phần nội dung chưa thực hiện');const resultIds=await page.locator('.result-card').evaluateAll(nodes=>nodes.slice(0,5).map(n=>n.dataset.testid.replace('search-result-','')));assert.ok(!resultIds.includes('seg-thuchanh01-01'));
   await shot("retrieval_limit","Truy vấn bổ sung chưa tìm thấy đoạn chuẩn ở năm vị trí đầu","Truy vấn này thuộc tập bổ sung được cố định sau giai đoạn phát triển thuật toán. Đoạn chuẩn quy định trước không nằm trong năm kết quả đầu, dù một số đoạn có từ gần với truy vấn được trả về. Hình giữ nguyên trường hợp chưa đạt để giải thích giới hạn của tra cứu theo từ khóa. Không sửa thuật toán theo riêng trường hợp này rồi dùng lại cùng tập để tuyên bố kiểm tra độc lập.","testing");
 });
 await step("B20","Kiểm tra sáu trang ở chiều rộng 390 điểm ảnh",async()=>{
   await page.setViewportSize({width:390,height:844});
   for(const view of ['overview','search','projects','sources','audit','guide']){await nav(view);const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(sizes.scroll<=sizes.width+1,`${view}: ${JSON.stringify(sizes)}`);}
   await nav('overview');await shot("mobile_overview","Tổng quan ở khung nhìn điện thoại","Bản chụp sử dụng khung nhìn rộng 390 điểm ảnh trong trình duyệt kiểm thử. Vùng tiêu đề và các chỉ số được chụp riêng để thấy cách sắp nội dung ở chiều rộng hẹp, không làm toàn trang tràn ngang. Kết quả này chỉ xác nhận bố cục trong kích thước và trình duyệt đã thử, không thay thế kiểm tra trên nhiều thiết bị thực. Ứng dụng vẫn cần máy đang chạy dịch vụ cục bộ và không được công bố như một dịch vụ di động qua mạng.","mobile");
   await selectProject(projectId);await shot("mobile_project","Hồ sơ và điều khiển xuất ở khung nhìn hẹp","Thông tin hồ sơ, các nút thao tác và bộ chọn định dạng xuất được chụp cận cảnh trong vùng nhìn hẹp. Kịch bản kiểm tra toàn trang không phát sinh tràn ngang ở sáu trang chính. Bảng nhật ký có vùng cuộn riêng khi cần đọc dữ liệu rộng; điều này khác với việc toàn giao diện vượt ngoài màn hình. Bản mẫu chưa được chứng nhận khả năng tiếp cận trên mọi thiết bị hoặc trình đọc màn hình.","mobile");
   await page.setViewportSize({width:1280,height:1100});
 });
 await step("B21","Không có lỗi JavaScript chưa được xử lý trong chuỗi thao tác",async()=>assert.deepEqual(errors,[]));
}
main().then(async()=>{await browser.close();write(true);}).catch(async e=>{console.error(e.stack);if(page){try{await page.screenshot({path:path.join(dir,'browser_failure.png'),fullPage:false});}catch{}}if(browser)await browser.close();write(false);process.exitCode=1;});
function write(completed){
 const result={started_at:started,finished_at:new Date().toISOString(),completed,base_url:base,viewport:{width:1280,height:1100},mobile_viewport:{width:390,height:844},browser:"Chromium via Playwright",scope:"Original UI DOM interactions with a QA HTTP relay to the real localhost server. Browser navigation is restricted in this environment. Not a direct-navigation browser security test, model-quality evaluation, human usability study or Academy deployment.",cases,page_errors:errors,created_records:{project_id:projectId,source_id:sourceId},screenshots:figures.length};
 fs.writeFileSync(path.join(dir,'browser_results.json'),JSON.stringify(result,null,2));
 fs.writeFileSync(path.join(shots,'manifest.json'),JSON.stringify({created_at:result.finished_at,figures},null,2));
 console.log(JSON.stringify({completed,cases:cases.length,passed:cases.filter(c=>c.status==='passed').length,screenshots:figures.length}));
}
