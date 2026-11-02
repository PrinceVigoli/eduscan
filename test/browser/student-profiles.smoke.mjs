import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';

// A separate mock server and browser profile keep this check out of the user's database.
const root=process.cwd(),output=path.join(root,'build','preview');
await mkdir(output,{recursive:true});
const stored=[],requests=[],movements=[],errors=[];
let failProfileOnce=false;
const teacher={id:'11111111-1111-4111-8111-111111111111',full_name:'Preview Admin',role:'administrator'};
const server=createServer(async(req,res)=>{
  try{
    const url=new URL(req.url,'http://localhost'),route=url.pathname;
    if(route.startsWith('/api/v1/')){
      let raw='';for await(const chunk of req)raw+=chunk;
      const data=raw&&req.headers['content-type']?.includes('application/json')?JSON.parse(raw):{};
      requests.push({route,method:req.method,data});let result=[];let status=200;
      if(['POST','PUT'].includes(req.method))await new Promise(resolve=>setTimeout(resolve,250));
      if(route.endsWith('/profile')&&failProfileOnce){failProfileOnce=false;res.writeHead(503,{'Content-Type':'application/json'});res.end(JSON.stringify({detail:'Temporary save failure. Try again.'}));return}
      if(route==='/api/v1/auth/me')result=teacher;
      else if(route==='/api/v1/academic-years')result=[{id:'year',name:'2026-2027',state:'active'}];
      else if(route==='/api/v1/reports/attendance-summary')result={total:10,counts:{present:6,late:2,absent:1,excused:1},attendance_rate:80,sections:[{section:'Grade 7 - A',adviser:'Teacher',present:6,late:2,absent:1,excused:1,total:10,attendance_rate:80}]};
      else if(route==='/api/v1/reports/sf4'&&req.method==='GET')result={rows:[{section:'Grade 7 - A',adviser:'Teacher',grade:'7',registered:{male:1,female:1},attendance:{male:10,female:12},missing_sex:0,recorded_days:12}]};
      else if(route==='/api/v1/reports/sf4'&&req.method==='POST'){res.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});res.end(await readFile(path.join(root,'backend/app/templates/sf4.xlsx')));return}
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
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Emulation.setFocusEmulationEnabled',{enabled:true});await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});await cdp('Page.navigate',{url:'http://127.0.0.1:8897/'});
  await until("typeof availableClasses!=='undefined'&&availableClasses.length===1&&!document.body.classList.contains('auth-pending')");
  await until("document.querySelector('#presentStat').textContent==='6'");
  assert.equal(await evaluate("document.querySelector('#userAvatar').textContent"),'PA');
  assert.equal(await evaluate("document.querySelector('#sidebarSchoolYear').textContent"),'2026-2027');
  assert.equal(await evaluate("document.querySelectorAll('.attendance-line').length"),4);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#sidebarClose')).display"),'none');
  await evaluate("document.querySelector('#sidebarToggle').focus();document.querySelector('#sidebarToggle').click()");
  assert.equal(await evaluate("document.querySelector('#sidebar').getBoundingClientRect().width"),84);
  assert.equal(await evaluate("document.querySelector('#sidebarToggle').getAttribute('aria-expanded')"),'false');
  await evaluate("document.querySelector('.nav-item[data-view=students]').focus()");
  assert.equal(await evaluate("document.querySelector('#navTooltip').hidden"),false,JSON.stringify(await evaluate("({active:document.activeElement.id||document.activeElement.outerHTML.slice(0,200),tooltip:document.querySelector('#navTooltip').outerHTML,collapsed:document.body.className,dialogs:[...document.querySelectorAll('dialog[open]')].map(d=>d.id)})")));
  assert.equal(await evaluate("document.querySelector('#navTooltip').textContent"),'Students');
  const collapsed=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-sidebar-collapsed.png'),Buffer.from(collapsed.data,'base64'));
  await cdp('Page.reload');await until("typeof availableClasses!=='undefined'&&availableClasses.length===1&&document.querySelector('#presentStat').textContent==='6'");
  assert.equal(await evaluate("document.body.classList.contains('sidebar-collapsed')"),true,'Collapsed preference survives reload');
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#sidebar')).backgroundColor"),'rgb(18, 60, 54)');
  await evaluate("document.querySelector('#sidebarToggle').click()");
  assert.equal(await evaluate("document.querySelector('#sidebar').getBoundingClientRect().width"),248);
  await until("document.querySelector('#overviewPendingCount').textContent==='0'");
  const dashboard=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-overview.png'),Buffer.from(dashboard.data,'base64'));
  await evaluate("showView('students');document.querySelector('#addStudent').click()");await until("document.querySelector('#studentDialog').open");
  assert.equal(await evaluate("document.querySelector('#studentForm').checkValidity()"),false);
  await evaluate("document.querySelector('#studentForm').requestSubmit()");assert.equal(stored.length,0);
  const details={first_name:'Maria',middle_name:'Isabel',last_name:'Santos',suffix:'Jr.',lrn:'123456789012',sex:'female',date_of_birth:'2011-03-12',enrollment_date:'2026-06-01',academic_year:'2026-2027',section:'Grade 7 - A',enrollment_type:'transferred_in',guardian_name:'Ana <Santos>',guardian_phone:'09171234567',address:'Luna\nBarangay One'};
  await evaluate(`(()=>{const form=document.querySelector('#studentForm');for(const [name,value]of Object.entries(${JSON.stringify(details)}))form.elements[name].value=value})()`);
  assert.equal(await evaluate("document.querySelector('#studentForm').checkValidity()"),true);
  assert.equal(await evaluate("document.querySelector('#studentForm [type=submit]').getBoundingClientRect().bottom<=document.querySelector('#studentDialog').getBoundingClientRect().bottom"),true,'Student save button must stay fully visible');
  const screenshot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'student-form.png'),Buffer.from(screenshot.data,'base64'));
  await evaluate("document.querySelector('#studentForm').requestSubmit();document.querySelector('#studentForm').requestSubmit()");
  assert.equal(await evaluate("document.querySelector('#studentForm').getAttribute('aria-busy')"),'true');
  assert.equal(await evaluate("document.querySelector('#studentForm [type=submit]').textContent"),'Saving student…');
  await until("document.querySelector('#qrIssuedDialog').open");
  assert.equal(requests.filter(item=>item.route==='/api/v1/students'&&item.method==='POST').length,1,'Duplicate submit sends only one create');
  assert.equal(await evaluate("document.querySelector('#toast').matches(':popover-open')"),true,'Feedback appears above modal dialogs');
  assert.equal(stored.length,1);assert.equal(stored[0].guardian_phone,details.guardian_phone);assert.equal(stored[0].date_of_birth,details.date_of_birth);
  await evaluate("document.querySelector('#qrIssuedDialog').close();document.querySelector('.student-view').click()");await until("document.querySelector('#studentProfileDialog').open&&document.querySelector('#studentMovementHistory').textContent.includes('transferred in')");
  assert((await evaluate("document.querySelector('#profileDetails').textContent")).includes('Ana <Santos>'));
  assert.equal(await evaluate("document.querySelector('#profileDetails img')!==null"),false);
  await evaluate("document.querySelector('#editStudentProfile').click()");await until("document.querySelector('#studentEditDialog').open");
  assert.equal(await evaluate("document.querySelector('#studentEditForm').elements.date_of_birth.value"),'2011-03-12');
  failProfileOnce=true;
  await evaluate("document.querySelector('#studentEditForm').elements.first_name.value='Marina';document.querySelector('#studentEditForm').requestSubmit();document.querySelector('#studentEditForm').requestSubmit();document.querySelector('[data-close-dialog=studentEditDialog]').click()");
  assert.equal(await evaluate("document.querySelector('#studentEditDialog').open"),true,'Saving form stays open');
  await until("document.querySelector('#studentEditError').textContent.includes('Temporary save failure')");
  assert.equal(await evaluate("document.querySelector('#studentEditForm').elements.first_name.value"),'Marina');
  assert.equal(await evaluate("document.querySelector('#studentEditForm [type=submit]').disabled"),false);
  assert.equal(await evaluate("document.querySelector('#studentEditForm [type=submit]').textContent"),'Save details');
  assert.equal(requests.filter(item=>item.route.endsWith('/profile')).length,1);
  await evaluate("document.querySelector('#studentEditForm').elements.first_name.value='Marina';document.querySelector('#studentEditForm').requestSubmit()");await until("!document.querySelector('#studentEditDialog').open");
  assert.equal(await evaluate("document.querySelector('#profileStudentName').textContent"),'Marina Isabel Santos Jr.');assert.equal(stored[0].credential_id,'credential');
  await evaluate("document.querySelector('#studentProfileDialog').close();showView('qr');document.querySelector('#selectAllQr').click();window.print=()=>{window.previewPrinted=true};document.querySelector('#printCards').click()");
  await until('window.previewPrinted===true');
  assert.equal(await evaluate("document.querySelectorAll('.print-card').length"),1);
  await cdp('Emulation.setEmulatedMedia',{media:'print'});
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.app-shell')).display"),'none');
  assert.equal(await evaluate("Math.round(document.querySelector('.print-card').getBoundingClientRect().width)"),324);
  await cdp('Emulation.setEmulatedMedia',{media:''});
  await evaluate("showView('students');document.querySelector('.student-view').click()");
  await until("document.querySelector('#studentProfileDialog').open");
  await evaluate("document.querySelector('#studentStatusButton').click()");await until("document.querySelector('#studentStatusDialog').open");
  await evaluate("(()=>{const form=document.querySelector('#studentStatusForm');form.elements.reason.value='dropped_out';form.elements.effective_on.value=schoolToday();form.elements.reason_note.value='Confirmed with guardian';form.requestSubmit()})()");await until("!document.querySelector('#studentStatusDialog').open&&!document.querySelector('#studentProfileDialog').open");
  assert.equal(stored[0].is_active,false);const status=requests.find(item=>item.route.endsWith('/status'));assert.equal(status.data.reason_note,'Confirmed with guardian');assert.match(status.data.effective_on,/^\d{4}-\d{2}-\d{2}$/);
  await evaluate("showView('reports');window.sf4Downloads=[];download=(name,content,type)=>window.sf4Downloads.push({name,size:content.size,type});document.querySelector('#createSf4').click()");
  await until("document.querySelector('#sf4Dialog').open");
  const sf4Meta={school_name:'Test School',school_id:'123456',region:'Region I',division:'Division',district:'Luna',school_head:'School Head',academic_year:'2026-2027',month:'2026-11',school_days:'20',school_level:'secondary'};
  await evaluate(`(()=>{const form=document.querySelector('#sf4Form');for(const[name,value]of Object.entries(${JSON.stringify(sf4Meta)}))form.elements[name].value=value;document.querySelector('#loadSf4').click()})()`);
  await until("document.querySelectorAll('#sf4Rows .sf4-section').length===1");
  await evaluate("document.querySelectorAll('#sf4Rows input[type=number]').forEach(input=>{if(input.value==='')input.value='0'});document.querySelector('#sf4Rows').dispatchEvent(new Event('input'));document.querySelector('#sf4Form').requestSubmit();document.querySelector('#sf4Form').requestSubmit()");
  assert.equal(await evaluate("document.querySelector('#downloadSf4').textContent"),'Generating SF4…');
  await until('window.sf4Downloads.length===1');
  assert.equal(requests.filter(item=>item.route==='/api/v1/reports/sf4'&&item.method==='POST').length,1);
  assert.equal(requests.find(item=>item.route==='/api/v1/reports/sf4'&&item.method==='POST').data.rows[0].registered.female,1);
  assert((await evaluate('window.sf4Downloads[0].size'))>1000);
  await evaluate("document.querySelector('#sf4Dialog').close();showView('students')");
  await evaluate("window.previewDownloads=[];download=(name,content)=>window.previewDownloads.push({name,content});document.querySelector('#downloadTemplate').click();document.querySelector('#exportStudents').click()");
  const downloads=await evaluate('window.previewDownloads');assert(downloads[0].content.includes('date_of_birth'));assert(downloads[1].content.includes('09171234567'));assert(downloads[1].content.includes('Marina'));
  const csv='first_name,last_name,lrn,section,sex,date_of_birth,enrollment_date,academic_year\nNew,Learner,123456789013,Grade 7 - A,M,2011-01-01,2026-06-01,2026-2027\nMissing,Birthday,123456789014,Grade 7 - A,F,,2026-06-01,2026-2027';
  await evaluate(`(()=>{const transfer=new DataTransfer();transfer.items.add(new File([${JSON.stringify(csv)}],'students.csv',{type:'text/csv'}));const input=document.querySelector('#csvFile');input.files=transfer.files;input.dispatchEvent(new Event('change'))})()`);
  await until("document.querySelector('#csvResultsDialog').open");assert.equal(await evaluate("document.querySelector('#csvResultsSummary').textContent"),'1 student(s) imported; 1 row(s) skipped.');
  await evaluate("document.querySelector('#csvResultsDialog').close()");
  await evaluate(`(()=>{window.savedStudentFixtures=[...students];students.splice(0,students.length,...Array.from({length:23},(_,i)=>({...window.savedStudentFixtures[0],id:'page-'+i,name:'Learner '+String(i+1).padStart(2,'0'),lrn:String(100000000000+i),section:i===22?'Grade 7 - AB':'Grade 7 - A',isActive:i%2===0})));renderStudents()})()`);
  assert.equal(await evaluate("document.querySelectorAll('.student-view').length"),10);
  assert.equal(await evaluate("document.querySelector('#studentResults').textContent"),'Showing 1–10 of 23 students');
  await evaluate("document.querySelector('#studentNextPage').click();document.querySelector('#studentNextPage').click()");
  assert.equal(await evaluate("document.querySelectorAll('.student-view').length"),3);
  assert.equal(await evaluate("document.querySelector('#studentNextPage').disabled"),true);
  await evaluate("document.querySelector('#studentStatusFilter').value='inactive';document.querySelector('#studentStatusFilter').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate("document.querySelector('#studentResults').textContent"),'Showing 1–10 of 11 students');
  assert.equal(await evaluate("document.querySelector('#studentPageLabel').textContent"),'1 / 2');
  await evaluate("document.querySelector('#resetStudentFilters').click();document.querySelector('#sectionFilter').value='Grade 7 - A';document.querySelector('#sectionFilter').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate("document.querySelector('#studentResults').textContent"),'Showing 1–10 of 22 students','Section filter must match exactly');
  await evaluate("document.querySelector('#resetStudentFilters').click();document.querySelector('#studentPageSize').value='25';document.querySelector('#studentPageSize').dispatchEvent(new Event('change'))");
  assert.equal(await evaluate("document.querySelectorAll('.student-view').length"),23);
  await evaluate("document.querySelector('[data-student-sort=name]').click()");
  assert.equal(await evaluate("document.querySelector('#studentTable .student-identity strong').textContent"),'Learner 23');
  assert.equal(await evaluate("document.querySelector('[data-student-sort=name]').closest('th').getAttribute('aria-sort')"),'descending');
  await evaluate("document.querySelector('#studentSearch').value='100000000022';document.querySelector('#studentSearch').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("document.querySelectorAll('.student-view').length"),1);
  await evaluate("document.querySelector('#studentSearch').value='no matching learner';document.querySelector('#studentSearch').dispatchEvent(new Event('input'))");
  assert.equal(await evaluate("document.querySelector('#studentResults').textContent"),'0 students');
  assert.equal(await evaluate("document.querySelector('#studentNextPage').disabled"),true);
  await evaluate("document.querySelector('#resetStudentFilters').click();students.splice(0,students.length,...window.savedStudentFixtures);document.querySelector('[data-student-sort=name]').click();document.querySelector('#studentPageSize').value='10';document.querySelector('#studentPageSize').dispatchEvent(new Event('change'))");
  const studentList=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-students.png'),Buffer.from(studentList.data,'base64'));
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await until("!document.body.classList.contains('sidebar-collapsed')");
  await until("document.querySelector('#sidebar').getBoundingClientRect().right<=0");
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#sidebarToggle')).display"),'none');
  for(const view of ['overview','students','classes','reports','qr','scanner']){
    await evaluate(`showView('${view}')`);
    assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true,`Mobile overflow in ${view}`);
    if(view==='students'){const capture=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-students-mobile.png'),Buffer.from(capture.data,'base64'))}
  }
  await evaluate("document.querySelector('#menuButton').click()");
  assert.equal(await evaluate("document.querySelector('#menuButton').getAttribute('aria-expanded')"),'true');
  assert.equal(await evaluate("document.querySelector('#mainContent').inert"),true);
  await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate("document.querySelector('#menuButton').getAttribute('aria-expanded')"),'false');
  assert.equal(await evaluate("document.activeElement.id"),'menuButton');
  await evaluate("document.querySelector('#menuButton').click();document.querySelector('#sidebarBackdrop').click()");
  assert.equal(await evaluate("document.querySelector('#mainContent').inert"),false);
  await evaluate("document.querySelector('#menuButton').click();document.querySelector('.nav-item[data-view=reports]').click()");
  await until("document.querySelector('#reports').classList.contains('active')&&!document.querySelector('#sidebar').classList.contains('open')");
  await until("document.querySelector('#sidebar').getBoundingClientRect().right<=0");
  const mobileReports=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-reports-mobile.png'),Buffer.from(mobileReports.data,'base64'));
  await evaluate("showView('students')");
  await evaluate("document.querySelector('#addStudent').click()");await until("document.querySelector('#studentDialog').open");
  assert.equal(await evaluate("document.querySelector('#studentDialog').getBoundingClientRect().width<=window.innerWidth"),true);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#studentForm .form-grid')).gridTemplateColumns.split(' ').length"),1);
  const mobileScreenshot=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'student-form-mobile.png'),Buffer.from(mobileScreenshot.data,'base64'));
  await evaluate("document.querySelector('#studentDialog').close();activateAuthenticatedUser({id:'principal',full_name:'Principal Preview',role:'principal'})");
  await until("document.querySelector('#principalHome').classList.contains('active')&&document.querySelector('#principalHome .report-banner strong').textContent==='80%'");
  assert.equal(await evaluate("document.querySelector('.nav-item[data-view=students]').hidden"),true);
  assert.equal(await evaluate("document.querySelector('.nav-item[data-view=reports]').hidden"),false);
  await evaluate("activateAuthenticatedUser({id:'teacher',full_name:'Teacher Preview',role:'teacher'})");
  await until("document.querySelector('#teacherHome').classList.contains('active')&&document.querySelector('#teacherClassStat').textContent==='1'");
  assert.equal(await evaluate("document.querySelector('#createUserButton').hidden"),true);
  assert.equal(await evaluate("document.querySelector('#teacherClassList').textContent.includes('Math')"),true);
  await evaluate("document.querySelector('#studentDialog').close();showLogin()");
  assert.equal(await evaluate("document.querySelector('#loginDialog').getBoundingClientRect().width<=window.innerWidth"),true);
  const mobileLogin=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-login-mobile.png'),Buffer.from(mobileLogin.data,'base64'));
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  assert.equal(await evaluate("document.body.classList.contains('sidebar-collapsed')"),false);
  const desktopLogin=await cdp('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'ui-login.png'),Buffer.from(desktopLogin.data,'base64'));
  assert.equal(errors.length,0,JSON.stringify(errors));console.log('PASS: government workspace, student sorting/filtering/pagination, dashboard data, student creation/editing, movement status, CSV import/export, SF4 download, QR print layout, mobile navigation/focus, responsive views, and login.');
}finally{
  if(socket?.readyState===WebSocket.OPEN){try{await cdp('Browser.close')}catch{}socket.close()}
  chrome.kill();await new Promise(resolve=>server.close(resolve));
}
