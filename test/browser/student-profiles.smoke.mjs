import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';

// A separate mock server and browser profile keep this check out of the user's database.
const root=process.cwd(),output=path.join(root,'build','preview');
await mkdir(output,{recursive:true});
const stored=[],requests=[],movements=[],errors=[];
const teacher={id:'11111111-1111-4111-8111-111111111111',full_name:'Preview Admin',role:'administrator'};
const server=createServer(async(req,res)=>{
  try{
    const url=new URL(req.url,'http://localhost'),route=url.pathname;
    if(route.startsWith('/api/v1/')){
      let raw='';for await(const chunk of req)raw+=chunk;
      const data=raw&&req.headers['content-type']?.includes('application/json')?JSON.parse(raw):{};
      requests.push({route,method:req.method,data});let result=[];let status=200;
      if(route==='/api/v1/auth/me')result=teacher;
      else if(route==='/api/v1/academic-years')result=[{id:'year',name:'2026-2027',state:'active'}];
      else if(route==='/api/v1/classes')result=[{id:'class',school_year:'2026-2027',section:'Grade 7 - A',subject:'Math',schedule_label:'Monday 08:00',weekday:0,start_time:'08:00',end_time:'09:00',teacher_id:teacher.id}];
      else if(route==='/api/v1/students'&&req.method==='POST'){
        result={...data,id:`student-${stored.length+1}`,full_name:[data.first_name,data.middle_name,data.last_name,data.suffix].filter(Boolean).join(' '),age:15,credential_id:'credential',qr_download_url:'/api/v1/qr-credentials/credential/image.svg',qr_status:'active',is_active:true};stored.push(result);status=201;
        movements.push({school_year:data.academic_year,section:data.section,kind:data.enrollment_type==='transferred_in'?'transferred_in':'enrolled',effective_on:data.enrollment_date,reason:null});
      }else if(route==='/api/v1/students')result=stored;
      else if(route.endsWith('/profile')){Object.assign(stored[0],data,{full_name:[data.first_name,data.middle_name,data.last_name,data.suffix].filter(Boolean).join(' ')});result=stored[0]}
      else if(route.endsWith('/movements'))result=movements;
      else if(route.endsWith('/status')){Object.assign(stored[0],{is_active:data.is_active,inactive_reason:data.reason,qr_status:'revoked',qr_download_url:null});movements.push({school_year:data.academic_year,section:stored[0].section,kind:data.reason,effective_on:data.effective_on,reason:data.reason_note});result=stored[0]}
      else if(route.endsWith('.svg')){res.writeHead(200,{'Content-Type':'image/svg+xml'});res.end('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="black"/></svg>');return}
      res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(result));return;
    }
    const file=path.resolve(root,'.'+(route==='/'?'/index.html':route));
    if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return}
    const content=await readFile(file);const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.webmanifest':'application/manifest+json'};
    res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});res.end(content);
  }catch(error){res.writeHead(404);res.end('Not found')}
});
await new Promise(resolve=>server.listen(8897,'127.0.0.1',resolve));
const profile=path.join(output,`browser-profile-${Date.now()}`);
const chrome=spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-extensions','--remote-debugging-port=9224',`--user-data-dir=${profile}`,'about:blank'],{stdio:'ignore'});
let socket,id=0;const pending=new Map();
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function cdp(method,params={}){return new Promise((resolve,reject)=>{const current=++id;pending.set(current,{resolve,reject});socket.send(JSON.stringify({id:current,method,params}))})}
async function evaluate(expression){const response=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,userGesture:true});if(response.exceptionDetails)throw new Error(JSON.stringify(response.exceptionDetails));return response.result.value}
async function until(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await pause(50)}throw new Error('Timed out: '+expression)}
try{
  let ready=false;for(let attempt=0;attempt<80;attempt++){try{const response=await fetch('http://127.0.0.1:9224/json/version');if(response.ok){ready=true;break}}catch{}await pause(100)}assert(ready,'Chrome DevTools did not start');
  const target=await(await fetch('http://127.0.0.1:9224/json/new?about:blank',{method:'PUT'})).json();
  socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
  socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(data.id){const callback=pending.get(data.id);pending.delete(data.id);data.error?callback?.reject(new Error(JSON.stringify(data.error))):callback?.resolve(data.result)}else if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails)});
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:'http://127.0.0.1:8897/'});
  await until("typeof availableClasses!=='undefined'&&availableClasses.length===1&&!document.body.classList.contains('auth-pending')");
  await evaluate("showView('students');document.querySelector('#addStudent').click()");await until("document.querySelector('#studentDialog').open");
  assert.equal(await evaluate("document.querySelector('#studentForm').checkValidity()"),false);
  await evaluate("document.querySelector('#studentForm').requestSubmit()");assert.equal(stored.length,0);
  const details={first_name:'Maria',middle_name:'Isabel',last_name:'Santos',suffix:'Jr.',lrn:'123456789012',sex:'female',date_of_birth:'2011-03-12',enrollment_date:'2026-06-01',academic_year:'2026-2027',section:'Grade 7 - A',enrollment_type:'transferred_in',guardian_name:'Ana <Santos>',guardian_phone:'09171234567',address:'Luna\nBarangay One'};
  await evaluate(`(()=>{const form=document.querySelector('#studentForm');for(const [name,value]of Object.entries(${JSON.stringify(details)}))form.elements[name].value=value})()`);
  assert.equal(await evaluate("document.querySelector('#studentForm').checkValidity()"),true);
  const screenshot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'student-form.png'),Buffer.from(screenshot.data,'base64'));
  await evaluate("document.querySelector('#studentForm').requestSubmit()");await until("document.querySelector('#qrIssuedDialog').open");
  assert.equal(stored.length,1);assert.equal(stored[0].guardian_phone,details.guardian_phone);assert.equal(stored[0].date_of_birth,details.date_of_birth);
  await evaluate("document.querySelector('#qrIssuedDialog').close();document.querySelector('.student-view').click()");await until("document.querySelector('#studentProfileDialog').open&&document.querySelector('#studentMovementHistory').textContent.includes('transferred in')");
  assert((await evaluate("document.querySelector('#profileDetails').textContent")).includes('Ana <Santos>'));
  assert.equal(await evaluate("document.querySelector('#profileDetails img')!==null"),false);
  await evaluate("document.querySelector('#editStudentProfile').click()");await until("document.querySelector('#studentEditDialog').open");
  assert.equal(await evaluate("document.querySelector('#studentEditForm').elements.date_of_birth.value"),'2011-03-12');
  await evaluate("document.querySelector('#studentEditForm').elements.first_name.value='Marina';document.querySelector('#studentEditForm').requestSubmit()");await until("!document.querySelector('#studentEditDialog').open");
  assert.equal(await evaluate("document.querySelector('#profileStudentName').textContent"),'Marina Isabel Santos Jr.');assert.equal(stored[0].credential_id,'credential');
  await evaluate("document.querySelector('#studentStatusButton').click()");await until("document.querySelector('#studentStatusDialog').open");
  await evaluate("(()=>{const form=document.querySelector('#studentStatusForm');form.elements.reason.value='dropped_out';form.elements.effective_on.value=schoolToday();form.elements.reason_note.value='Confirmed with guardian';form.requestSubmit()})()");await until("!document.querySelector('#studentStatusDialog').open&&!document.querySelector('#studentProfileDialog').open");
  assert.equal(stored[0].is_active,false);const status=requests.find(item=>item.route.endsWith('/status'));assert.equal(status.data.reason_note,'Confirmed with guardian');assert.match(status.data.effective_on,/^\d{4}-\d{2}-\d{2}$/);
  await evaluate("window.previewDownloads=[];download=(name,content)=>window.previewDownloads.push({name,content});document.querySelector('#downloadTemplate').click();document.querySelector('#exportStudents').click()");
  const downloads=await evaluate('window.previewDownloads');assert(downloads[0].content.includes('date_of_birth'));assert(downloads[1].content.includes('09171234567'));assert(downloads[1].content.includes('Marina'));
  const csv='first_name,last_name,lrn,section,sex,date_of_birth,enrollment_date,academic_year\nNew,Learner,123456789013,Grade 7 - A,M,2011-01-01,2026-06-01,2026-2027\nMissing,Birthday,123456789014,Grade 7 - A,F,,2026-06-01,2026-2027';
  await evaluate(`(()=>{const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(csv)}],'students.csv',{type:'text/csv'}));const input=document.querySelector('#csvFile');input.files=transfer.files;input.dispatchEvent(new Event('change'))})()`);
  await until("document.querySelector('#csvResultsDialog').open");assert.equal(await evaluate("document.querySelector('#csvResultsSummary').textContent"),'1 student(s) imported; 1 row(s) skipped.');
  await evaluate("document.querySelector('#csvResultsDialog').close()");
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("document.querySelector('#addStudent').click()");await until("document.querySelector('#studentDialog').open");
  assert.equal(await evaluate("document.querySelector('#studentDialog').getBoundingClientRect().width<=window.innerWidth"),true);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#studentForm .form-grid')).gridTemplateColumns.split(' ').length"),1);
  const mobileScreenshot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'student-form-mobile.png'),Buffer.from(mobileScreenshot.data,'base64'));
  assert.equal(errors.length,0,JSON.stringify(errors));console.log('PASS: required fields, creation, profile editing, movement status, CSV import/export, and escaped personal details.');
}finally{
  if(socket?.readyState===WebSocket.OPEN){try{await cdp('Browser.close')}catch{}socket.close()}
  chrome.kill();await new Promise(resolve=>server.close(resolve));
}
