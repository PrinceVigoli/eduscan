const students=[];
const classes=[];
const activities=[];
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const browserFetch=window.fetch.bind(window);window.fetch=(input,options={})=>browserFetch(input,{credentials:'include',...options});
function toast(message){const t=$('#toast');t.textContent=message;t.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.classList.remove('show'),2600)}
function showView(id){$$('.view').forEach(v=>v.classList.toggle('active',v.id===id));$$('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.view===id));$('#crumbTitle').textContent=id[0].toUpperCase()+id.slice(1);$('#sidebar').classList.remove('open');scrollTo(0,0)}
$$('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));$$('[data-view-target]').forEach(b=>b.onclick=()=>showView(b.dataset.viewTarget));
$('#menuButton').onclick=()=>$('#sidebar').classList.toggle('open');
$('#attendanceChart').innerHTML='<div class="empty-state">No attendance data yet</div>';
$('#activityList').innerHTML='<div class="empty-state">No attendance activity yet</div>';
function renderStudents(list=students){$('#studentTable').innerHTML=list.length?list.map(s=>`<tr><td><strong>${escapePrintText(s.name)}</strong><small>${s.isActive?'Student':`Inactive · ${escapePrintText(s.inactiveReason||'school decision')}`}</small></td><td>${escapePrintText(s.lrn)}</td><td>${escapePrintText(s.section)}</td><td><span class="status ${s.qr==='Active'?'present':''}">${escapePrintText(s.qr||'No active QR')}</span></td><td><span class="status">${escapePrintText(s.today||'—')}</span></td><td><button class="text-button student-view" data-student-id="${s.id}">View →</button></td></tr>`).join(''):'<tr><td colspan="6"><div class="empty-state">No students yet. Add a student or import the CSV template.</div></td></tr>'}
renderStudents();
function filterStudents(){const q=$('#studentSearch').value.toLowerCase(), sec=$('#sectionFilter').value;renderStudents(students.filter(s=>(s.name.toLowerCase().includes(q)||s.lrn.includes(q))&&(sec==='All sections'||s.section.includes(sec))))}
$('#studentSearch').oninput=filterStudents;$('#sectionFilter').onchange=filterStudents;
$('#classGrid').innerHTML='<article class="panel empty-state">No classes configured yet</article>';
$('#reportTable').innerHTML='<tr><td colspan="6"><div class="empty-state">No consolidated attendance data yet</div></td></tr>';
$('#qrGrid').innerHTML='<div class="empty-state">No QR credentials issued yet</div>';
let session=false, scanIndex=0, stream, activeSessionId, activeClassId, activeOfflineAuthorization=null, activeSessionOpenedAt=null, sessionRoster=[];
function renderRoster(){const roster=sessionRoster;$('#rosterList').innerHTML=roster.length?roster.map(s=>{const present=scannedStudentLrns.has(s.lrn);return`<div class="roster-row"><span class="avatar">${s.initials}</span><span><strong>${escapePrintText(s.name)}</strong><small>LRN ending ${s.lrn.slice(-4)}</small></span><span class="status ${present?'present':''}">${present?'Present':'Waiting'}</span></div>`}).join(''):'<div class="empty-state">No students are enrolled in this class</div>';$('#rosterSummary').textContent=`${scannedStudentLrns.size} of ${roster.length} confirmed present`}
async function openStudentDialog(){
  await loadAcademicYears();if(!availableClasses.length)await loadClasses();
  const years=availableAcademicYears.filter(year=>['active','planning'].includes(year.state));
  $('#studentAcademicYear').innerHTML=years.map(year=>`<option value="${escapePrintText(year.name)}">${escapePrintText(year.name)} · ${year.state}</option>`).join('');
  $('#studentAcademicYear').value=years.find(year=>year.state==='active')?.name||years[0]?.name||'';
  refreshStudentCreateSections();
  if(![...$('#studentSection').options].some(option=>option.value))return toast('Create a class with a grade and section in a writable school year first.');
  setStudentDateLimits($('#studentForm'));$('#studentCreateError').textContent='';
  $('#studentDialog').showModal();
}
$('#addStudent').onclick=openStudentDialog;
function download(name,content,type='text/csv'){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([content],{type}));a.download=name;a.click();URL.revokeObjectURL(a.href)}
$('#downloadReport').onclick=()=>download('eduscan-attendance-report.csv','section,adviser,present,late,absent,rate\r\n');
if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});

// Offline-first persistence and synchronization.
function getDeviceId(){const key=`eduscan-device-id:${authenticatedUser?.id||'anonymous'}`;let id=localStorage.getItem(key);if(!id){id=crypto.randomUUID();localStorage.setItem(key,id)}return id}
async function updateSyncStatus(){const count=await EduScanDB.countPending();const online=navigator.onLine;$('#syncButton').className=`sync-status ${online?'online':''}`;$('#syncLabel').textContent=online?(count?`${count} pending`:'All synced'):`Offline · ${count} pending`}
async function synchronize(){const pending=await EduScanDB.getPending(),closures=await EduScanDB.getPendingSessionClosures(),attempts=await EduScanDB.getPendingVerificationAttempts();if(!pending.length&&!closures.length&&!attempts.length)return updateSyncStatus();$('#syncLabel').textContent=`Syncing ${pending.length+attempts.length} records…`;const apiBase=location.port==='8080'?'http://localhost:8000':'';try{const response=await fetch(`${apiBase}/api/v1/sync/attendance`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id:getDeviceId(),records:pending.map(r=>({record_id:r.id,session_id:r.sessionId,student_lrn:r.studentLrn,status:r.status,scanned_at:r.scannedAt,credential:r.credential||null,offline_authorization:r.offlineAuthorization||null,offline_opened_at:r.offlineOpenedAt||null})),session_closures:closures.map(item=>({session_id:item.id,offline_authorization:item.authorization,offline_opened_at:item.openedAt})),verification_attempts:attempts.map(item=>({attempt_id:item.id,session_id:item.sessionId,student_lrn:item.studentLrn,credential:item.credential,action:item.action,reason:item.reason,occurred_at:item.occurredAt}))})});if(!response.ok)throw new Error('Server unavailable');const result=await response.json();await EduScanDB.markSynced([...result.accepted_record_ids,...result.duplicate_record_ids]);await EduScanDB.markConflicts(result.conflicts);await EduScanDB.markSessionsClosed(result.closed_session_ids||[]);await EduScanDB.markVerificationAttemptsSynced(result.accepted_attempt_ids||[]);toast(`${result.accepted_record_ids.length} attendance record${result.accepted_record_ids.length===1?'':'s'} synchronized${result.conflicts.length?` · ${result.conflicts.length} need review`:''}`)}catch{$('#syncButton').classList.add('error');toast('Records are safe on this device; the server is unavailable.')}finally{updateSyncStatus()}}

$('#syncButton').onclick=synchronize;
window.addEventListener('online',()=>{updateSyncStatus();synchronize()});
window.addEventListener('offline',updateSyncStatus);
EduScanDB.open().then(updateSyncStatus);

// Role-specific workspaces. The API will enforce the same permissions server-side.
const roleConfig={
  teacher:{label:'Teacher',name:'Jamie Reyes',home:'teacherHome',views:['scanner','students','classes','reports','qr']},
  administrator:{label:'IT Administrator',name:'Alex Mendoza',home:'overview',views:['scanner','students','classes','reports','qr']},
  principal:{label:'Principal',name:'Dr. Elena Ramos',home:'principalHome',views:['reports']}
};
let currentRole='administrator';
function applyRole(role){const config=roleConfig[role];if(!config)return;currentRole=role;$('#roleLabel').textContent=config.label;$('#userName').textContent=config.name;$$('.nav-item').forEach(item=>{item.hidden=item.dataset.view!=='overview'&&!config.views.includes(item.dataset.view)});const homeNav=$('.nav-item[data-view="overview"]');homeNav.innerHTML=`<span>⌂</span> ${role==='principal'?'Consolidation':role==='teacher'?'My day':'System overview'}`;homeNav.onclick=()=>showView(config.home);const takeButton=$('.top-actions [data-view-target="scanner"]');takeButton.hidden=role!=='teacher';showView(config.home)}
$$('[data-action="student-add"]').forEach(button=>button.onclick=openStudentDialog);

// Student creation is server-authoritative and automatically issues a credential.
$('#closeQrDialog').onclick=()=>$('#qrIssuedDialog').close();
$('#copyQrLink').onclick=async()=>{await navigator.clipboard.writeText($('#copyQrLink').dataset.url);toast('Secure QR download link copied')};

// Real physical-card scanner using the browser's native BarcodeDetector.
let scanning=false, scanBusy=false, zxingControls, pendingVerification=null;
const scannedCredentialPayloads=new Set();
const scannedStudentLrns=new Set();
async function acceptScannedPayload(payload){
  if(scanBusy||pendingVerification)return;
  if(!payload.startsWith('EDUSCAN:'))return toast('This QR is not an EduScan student card.');
  if(scannedCredentialPayloads.has(payload))return toast('Duplicate rejected — this card is already recorded.');
  scanBusy=true;
  const apiBase=location.port==='8080'?'http://localhost:8000':'';
  try{
    let result,response;
    try{response=await fetch(`${apiBase}/api/v1/qr-credentials/validate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload,session_id:activeSessionId})});if(response.ok)result=await response.json();else{const problem=await response.json();throw Object.assign(new Error(problem.detail||'QR card could not be validated'),{serverRejected:true})}}catch(error){if(error.serverRejected)throw error;const packageRecord=await EduScanDB.getClassPackage(activeClassId);if(!packageRecord||new Date(packageRecord.payload.expires_at)<=new Date())throw new Error('Offline class list is missing or expired. Connect before scanning.');const credential=payload.slice('EDUSCAN:'.length);const student=packageRecord.payload.roster.find(item=>item.credential===credential);if(!student)throw new Error('QR card is not valid for this class.');result={full_name:student.full_name,lrn:student.lrn,section:student.section,photograph_url:student.photograph,offline:true}}
    if(scannedStudentLrns.has(result.lrn))throw new Error('Duplicate rejected — student already recorded.');
    $('#scanInitials').textContent=result.full_name.split(' ').map(part=>part[0]).join('').slice(0,2);
    $('#scanStudentName').textContent=result.full_name;
    $('#scanStudentMeta').textContent=`${result.section} · LRN ending ${result.lrn.slice(-4)}`;
    const photo=result.photograph_url;if(photo){$('#scanPhoto').src=photo.startsWith('data:')?photo:`${apiBase}${photo}`;$('#scanPhoto').hidden=false;$('.verification-help').textContent='Compare the photograph with the student in front of you.'}else{$('#scanPhoto').hidden=true;$('.verification-help').textContent='No photograph is registered. Confirm the name, section, and LRN ending before recording attendance.'}
    $('#scanResult').hidden=false;
    pendingVerification={payload,result};
    toast('Check the photograph, then confirm or reject this student.');
  }catch(error){toast(error.message)}finally{setTimeout(()=>{scanBusy=false},1200)}
}
async function clearVerification(){pendingVerification=null;$('#scanResult').hidden=true;$('#scanPhoto').hidden=true}
$('#confirmStudent').onclick=async()=>{if(!pendingVerification)return;const {payload,result}=pendingVerification;scannedCredentialPayloads.add(payload);scannedStudentLrns.add(result.lrn);await EduScanDB.saveAttendance({id:crypto.randomUUID(),sessionId:activeSessionId,studentLrn:result.lrn,status:'present',scannedAt:new Date().toISOString(),deviceId:getDeviceId(),credential:payload.slice('EDUSCAN:'.length),offlineAuthorization:activeOfflineAuthorization,offlineOpenedAt:activeSessionOpenedAt,syncStatus:'pending'});scanIndex=scannedStudentLrns.size;await clearVerification();renderRoster();updateSyncStatus();toast(`${result.full_name} confirmed present`)};
async function recordVerificationAttempt(action,reason){if(!pendingVerification)return;const {payload,result}=pendingVerification;await EduScanDB.saveVerificationAttempt({id:crypto.randomUUID(),sessionId:activeSessionId,studentLrn:result.lrn,credential:payload.slice('EDUSCAN:'.length),action,reason,occurredAt:new Date().toISOString(),syncStatus:'pending'});await clearVerification();updateSyncStatus();if(navigator.onLine)synchronize();toast(action==='flagged'?'Shared card flagged for review':'Scan rejected · no attendance recorded')}
$('#rejectStudent').onclick=()=>recordVerificationAttempt('rejected','Photograph did not match the student presenting the card');
$('#flagStudent').onclick=()=>recordVerificationAttempt('flagged','Teacher suspects the QR card was shared or copied');
async function scanVideoFrame(detector){
  if(!scanning)return;
  try{if($('#camera').readyState>=2){const codes=await detector.detect($('#camera'));if(codes.length)await acceptScannedPayload(codes[0].rawValue)}}catch{}
  if(scanning)requestAnimationFrame(()=>scanVideoFrame(detector));
}
$('#cameraButton').onclick=async()=>{
  if(scanning){scanning=false;if(zxingControls){zxingControls.stop();zxingControls=undefined}if(stream)stream.getTracks().forEach(track=>track.stop());$('#camera').style.display='none';$('.camera-placeholder').style.display='grid';$('.scan-target').style.display='none';$('#cameraButton').textContent='Use camera';return toast('Camera stopped')}
  try{
    if(!window.isSecureContext)throw new Error('Camera scanning requires HTTPS when EduScan is opened from another computer. Use HTTPS or scan a saved QR image.');
    $('#camera').style.display='block';$('.camera-placeholder').style.display='none';$('.scan-target').style.display='block';
    const nativeFormats='BarcodeDetector' in window?await BarcodeDetector.getSupportedFormats():[];
    scanning=true;$('#cameraButton').textContent='Stop camera';
    if(nativeFormats.includes('qr_code')){
      const detector=new BarcodeDetector({formats:['qr_code']});
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}}});
      $('#camera').srcObject=stream;await $('#camera').play();scanVideoFrame(detector);
    }else if(window.ZXingBrowser){
      const reader=new ZXingBrowser.BrowserQRCodeReader();
      zxingControls=await reader.decodeFromConstraints({video:{facingMode:{ideal:'environment'}}},$('#camera'),result=>{if(result)acceptScannedPayload(result.getText())});
    }else throw new Error('No QR decoder is available.');
    toast('Scanner ready — place the physical card inside the frame');
  }catch(error){toast(error.message||'Camera permission was denied.')}
};
$('#qrImageButton').onclick=()=>$('#qrImageFile').click();
$('#qrImageFile').onchange=async event=>{
  const file=event.target.files[0];event.target.value='';
  if(!file||!activeSessionId)return toast('Start an attendance session before scanning a QR image.');
  const imageUrl=URL.createObjectURL(file);
  try{
    let payload='';
    if('BarcodeDetector' in window){
      const formats=await BarcodeDetector.getSupportedFormats();
      if(formats.includes('qr_code')){
        const image=new Image();image.src=imageUrl;await image.decode();
        const codes=await new BarcodeDetector({formats:['qr_code']}).detect(image);
        payload=codes[0]?.rawValue||'';
      }
    }
    if(!payload&&window.ZXingBrowser){
      const result=await new ZXingBrowser.BrowserQRCodeReader().decodeFromImageUrl(imageUrl);
      payload=result?.getText?.()||result?.text||'';
    }
    if(!payload)throw new Error('No readable QR was found. Use the original downloaded image and avoid cropping its white border.');
    await acceptScannedPayload(payload.trim());
  }catch(error){toast(error.message||'The selected image could not be decoded.')}finally{URL.revokeObjectURL(imageUrl)}
};

// Print eight ID-sized student QR cards on each A4 sheet.
function escapePrintText(value){return String(value).replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]))}
$('#printCards').onclick=async()=>{
  const printable=students.filter(student=>student.qrUrl&&selectedQrIds.has(student.credentialId));
  if(!printable.length)return toast('Select at least one QR card before printing.');
  const pages=[];for(let index=0;index<printable.length;index+=8)pages.push(printable.slice(index,index+8));
  $('#printSheet').innerHTML=pages.map(page=>`<section class="print-page">${page.map(student=>`<article class="print-card"><div><p class="school">Luna National High School</p><h2>${escapePrintText(student.name)}</h2><p>${escapePrintText(student.section)}</p><p>LRN ending ${escapePrintText(student.lrn.slice(-4))}</p><p class="card-footer">EduScan ID · Report a lost card for revocation.</p></div><img src="${student.qrUrl}" alt="QR code for ${escapePrintText(student.name)}"></article>`).join('')}</section>`).join('');
  const images=$$('#printSheet img');
  await Promise.all(images.map(image=>image.complete?Promise.resolve():new Promise(resolve=>{image.onload=resolve;image.onerror=resolve})));
  toast(`${printable.length} card${printable.length===1?'':'s'} prepared · eight per A4 sheet`);setTimeout(()=>print(),250);
};
const selectedQrIds=new Set();
function updateQrSelectionCount(){const count=selectedQrIds.size;$('#selectedQrCount').textContent=`(${count})`;$('#selectAllQr').textContent=count&&count===students.length?'Clear all':'Select all'}
function renderQrLibrary(){const cards=students.filter(student=>student.qrUrl);const validIds=new Set(cards.map(student=>student.credentialId));[...selectedQrIds].forEach(id=>{if(!validIds.has(id))selectedQrIds.delete(id)});$('#qrGrid').innerHTML=cards.length?cards.map(student=>`<article class="panel qr-card ${selectedQrIds.has(student.credentialId)?'selected':''}"><input class="qr-select" type="checkbox" aria-label="Select QR for ${escapePrintText(student.name)}" data-credential-id="${student.credentialId}" ${selectedQrIds.has(student.credentialId)?'checked':''}><img class="qr-visual" src="${student.qrUrl}" alt="QR credential for ${escapePrintText(student.name)}"><h3>${escapePrintText(student.name)}</h3><p>${escapePrintText(student.section)} ·••${student.lrn.slice(-4)}</p><span class="status present">Active</span></article>`).join(''):'<div class="empty-state">No QR credentials issued yet</div>';updateQrSelectionCount()}
const qrNavigation=$('.nav-item[data-view="qr"]');
qrNavigation.onclick=()=>{renderQrLibrary();showView('qr')};

function getApiBase(){return location.port==='8080'?'http://localhost:8000':''}
function studentFromApi(record){return{profileDetails:record,id:record.id,firstName:record.first_name,lastName:record.last_name,name:record.full_name,lrn:record.lrn,section:record.section,sex:record.sex,initials:record.full_name.split(' ').map(part=>part[0]).join('').slice(0,2),qr:record.qr_status==='revoked'?`Revoked${record.qr_revocation_reason?` · ${record.qr_revocation_reason}`:''}`:'Active',today:'—',credentialId:record.credential_id,qrUrl:record.qr_download_url?`${getApiBase()}${record.qr_download_url}`:null,photographUrl:record.photograph_url?`${getApiBase()}${record.photograph_url}`:null,isActive:record.is_active!==false,inactiveReason:record.inactive_reason}}
async function loadStudents(){try{const response=await fetch(`${getApiBase()}/api/v1/students`);if(!response.ok)throw new Error();const records=await response.json();students.splice(0,students.length,...records.map(studentFromApi));renderStudents();renderQrLibrary()}catch{renderStudents();toast('Student server unavailable. No sample records were loaded.')}}
async function createStudentRecord(payload){const response=await fetch(`${getApiBase()}/api/v1/students`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(sf4Error(result.detail||'Student could not be created'));const student=studentFromApi(result);students.push(student);students.sort((a,b)=>a.name.localeCompare(b.name));return student}

$$('[data-close-student]').forEach(button=>button.onclick=()=>{$('#studentDialog').close();$('#studentForm').reset()});
$('#studentForm').onsubmit=async event=>{
  event.preventDefault();const form=event.target;if(!form.reportValidity())return;
  const data=new FormData(form),file=data.get('photograph'),button=form.querySelector('[type="submit"]');
  $('#studentCreateError').textContent='';
  if(file?.size>2*1024*1024){$('#studentCreateError').textContent='Photograph must be 2 MB or smaller.';return}
  const payload=Object.fromEntries(data);delete payload.photograph;button.disabled=true;button.textContent='Creating…';
  try{
    const student=await createStudentRecord(payload);let photoError='';
    if(file?.size){try{await saveStudentPhotograph(student,file)}catch(error){photoError=' Photograph could not be saved; upload it through the student profile.'}}
    renderStudents();renderQrLibrary();form.reset();$('#studentDialog').close();
    $('#issuedStudentName').textContent=`${student.name} · ${student.section}${photoError}`;$('#issuedQrImage').src=student.qrUrl;
    $('#downloadQrLink').href=student.qrUrl;$('#downloadQrLink').download=`${student.name.replaceAll(' ','-').toLowerCase()}-eduscan-qr.svg`;
    $('#copyQrLink').dataset.url=student.qrUrl;$('#qrIssuedDialog').showModal();toast('Student saved and QR credential issued'+photoError);
  }catch(error){$('#studentCreateError').textContent=error.message||'Connect to the EduScan server to create a student.'}
  finally{button.disabled=false;button.textContent='Save student'}
};

function csvEscape(value){const text=String(value??'');return /[",\r\n]/.test(text)?`"${text.replaceAll('"','""')}"`:text}
function parseCsv(text){const rows=[];let row=[],field='',quoted=false;for(let index=0;index<text.length;index++){const char=text[index],next=text[index+1];if(char==='"'&&quoted&&next==='"'){field+='"';index++}else if(char==='"'){quoted=!quoted}else if(char===','&&!quoted){row.push(field);field=''}else if((char==='\n'||char==='\r')&&!quoted){if(char==='\r'&&next==='\n')index++;row.push(field);if(row.some(value=>value.trim()))rows.push(row);row=[];field=''}else field+=char}row.push(field);if(row.some(value=>value.trim()))rows.push(row);return rows}
const studentCsvFields=['first_name','middle_name','last_name','suffix','lrn','sex','date_of_birth','enrollment_date','academic_year','section','enrollment_type','guardian_name','guardian_phone','address'];
$('#downloadTemplate').onclick=()=>download('eduscan-student-import-template.csv',studentCsvFields.join(',')+'\r\n');
$('#exportStudents').onclick=()=>{
  const rows=[studentCsvFields.join(','),...students.map(student=>{
    const details={...student.profileDetails};const years=[...new Set(availableClasses.filter(item=>item.section===student.section).map(item=>item.school_year))];
    details.academic_year=years.length===1?years[0]:'';
    return studentCsvFields.map(key=>csvEscape(details[key])).join(',');
  })];download('eduscan-students.csv',rows.join('\r\n'));
};
$('#importCsv').onclick=()=>$('#csvFile').click();
$('#csvFile').onchange=async event=>{
  const file=event.target.files[0];event.target.value='';if(!file)return;
  const rows=parseCsv(await file.text());if(!rows.length)return toast('The CSV file is empty.');
  const headers=rows.shift().map(header=>header.trim().toLowerCase().replace(/^\uFEFF/,'')),required=['first_name','last_name','lrn','section','sex','date_of_birth','enrollment_date','academic_year'];
  if(required.some(header=>!headers.includes(header))){$('#csvResultsSummary').textContent='Use the updated CSV template. Required columns: '+required.join(', ');$('#csvResultsErrors').textContent='Dates must use YYYY-MM-DD. Sex accepts male/female or M/F. Enrollment type accepts regular/transferred_in.';$('#csvResultsDialog').showModal();return}
  let imported=0;const errors=[];const button=$('#importCsv');button.disabled=true;
  try{for(const [index,row] of rows.entries()){
    const record=Object.fromEntries(headers.map((header,column)=>[header,(row[column]||'').trim()]));
    if(required.some(header=>!record[header])){errors.push(`Row ${index+2}: missing a required value`);continue}
    if(!record.enrollment_type)record.enrollment_type='regular';
    try{await createStudentRecord(record);imported++}catch(error){errors.push(`Row ${index+2}: ${error.message}`)}
  }}finally{button.disabled=false}
  renderStudents();renderQrLibrary();$('#csvResultsSummary').textContent=`${imported} student(s) imported; ${errors.length} row(s) skipped.`;
  $('#csvResultsErrors').textContent=errors.join('\n');$('#csvResultsDialog').showModal();
};

$('#qrGrid').onchange=event=>{const checkbox=event.target.closest('.qr-select');if(!checkbox)return;checkbox.checked?selectedQrIds.add(checkbox.dataset.credentialId):selectedQrIds.delete(checkbox.dataset.credentialId);checkbox.closest('.qr-card').classList.toggle('selected',checkbox.checked);updateQrSelectionCount()};
$('#selectAllQr').onclick=()=>{if(selectedQrIds.size===students.filter(student=>student.qrUrl).length)selectedQrIds.clear();else students.filter(student=>student.qrUrl).forEach(student=>selectedQrIds.add(student.credentialId));renderQrLibrary()};

let authenticatedUser=null, availableClasses=[], availableUsers=[], availableAcademicYears=[];
async function apiRequest(path,options={}){return fetch(`${getApiBase()}${path}`,options)}
function showLogin(message=''){document.body.classList.add('auth-pending');$('#loginError').textContent=message;if(!$('#loginDialog').open)$('#loginDialog').showModal()}
async function activateAuthenticatedUser(user){authenticatedUser=user;EduScanDB.setActiveUser(user.id);applyRole(user.role);$('#userName').textContent=user.full_name;$('#roleLabel').textContent=roleConfig[user.role].label;$$('.admin-only').forEach(element=>element.hidden=user.role!=='administrator');document.body.classList.remove('auth-pending');if($('#loginDialog').open)$('#loginDialog').close();if(user.role==='teacher'){const deviceResponse=await apiRequest('/api/v1/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_uuid:getDeviceId(),label:navigator.userAgent.slice(0,120)})});if(!deviceResponse.ok)toast('This browser could not be registered for offline attendance. Ask IT to review the device.')}await loadAcademicYears();await loadClasses();if(user.role!=='principal')await loadStudents();else{students.splice(0);renderStudents();renderQrLibrary()}if(user.role==='administrator')await loadUsers();if(user.role!=='teacher')await loadAttentionItems()}
async function loadAttentionItems(){const container=$('#attentionList');if(!container)return;const response=await apiRequest('/api/v1/audit-logs');if(!response.ok)return;const items=(await response.json()).filter(item=>item.action==='qr_verification.flagged').slice(0,8);container.className=items.length?'activity-list':'empty-state';container.innerHTML=items.length?items.map(item=>`<div class="activity-item"><span class="mini-icon coral">!</span><div><strong>Possible shared QR card</strong><small>${escapePrintText(item.details?.reason||'Teacher requested review')} · LRN ending ${escapePrintText(item.details?.student_lrn_suffix||'unknown')}</small></div><time>${new Date(item.created_at).toLocaleString()}</time></div>`).join(''):'No items need attention'}
async function restoreAuthentication(){try{const response=await apiRequest('/api/v1/auth/me');if(!response.ok)throw new Error();await activateAuthenticatedUser(await response.json())}catch{showLogin()}}
let assignmentRefreshBusy=false;
async function refreshTeacherAssignments(){if(assignmentRefreshBusy||authenticatedUser?.role!=='teacher'||session||document.hidden)return;assignmentRefreshBusy=true;try{const response=await apiRequest('/api/v1/classes');if(!response.ok)return;const latest=await response.json(),signature=list=>list.map(item=>`${item.id}:${item.teacher_id||''}:${item.section}:${item.subject}:${item.weekday}:${item.start_time}:${item.end_time}`).sort().join('|');if(signature(latest)!==signature(availableClasses)){await loadClasses();await loadStudents();toast('Your class assignments and rosters were updated by IT.')}}finally{assignmentRefreshBusy=false}}
setInterval(refreshTeacherAssignments,60000);window.addEventListener('focus',refreshTeacherAssignments);
$('#loginDialog').addEventListener('cancel',event=>event.preventDefault());
$('#loginForm').onsubmit=async event=>{event.preventDefault();const form=event.target,button=form.querySelector('[type="submit"]'),data=new FormData(form);button.disabled=true;button.textContent='Signing in…';$('#loginError').textContent='';try{const response=await apiRequest('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:data.get('email'),password:data.get('password')})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Sign-in failed');form.reset();await activateAuthenticatedUser(result)}catch(error){showLogin(error.message)}finally{button.disabled=false;button.textContent='Sign in'}};
$('#roleButton').onclick=()=>{if(!authenticatedUser)return;$('#accountName').textContent=authenticatedUser.full_name;$('#accountRole').textContent=roleConfig[authenticatedUser.role].label;$('#accountAvatar').textContent=authenticatedUser.full_name.split(' ').map(part=>part[0]).join('').slice(0,2).toUpperCase();$('#accountDialog').showModal()};
$('#logoutButton').onclick=async()=>{const button=$('#logoutButton');button.disabled=true;button.textContent='Signing out…';try{const pending=await EduScanDB.countPending();if(pending&&!confirm(`${pending} attendance record${pending===1?' is':'s are'} still waiting to synchronize. Sign out anyway?`))return;await apiRequest('/api/v1/auth/logout',{method:'POST'});await EduScanDB.clearSensitiveData();authenticatedUser=null;students.splice(0);availableClasses=[];$('#accountDialog').close();showLogin()}finally{button.disabled=false;button.textContent='Sign out'}};
$('#accountSettingsButton').onclick=()=>{$('#accountDialog').close();$('#settingsDialog').showModal()};
$('#togglePassword').onclick=()=>{const input=$('#loginPassword'),showing=input.type==='text';input.type=showing?'password':'text';$('#togglePassword').textContent=showing?'Show':'Hide';$('#togglePassword').setAttribute('aria-label',showing?'Show password':'Hide password')};

async function loadClasses(){const response=await apiRequest('/api/v1/classes');availableClasses=response.ok?await response.json():[];$('#classGrid').innerHTML=availableClasses.length?availableClasses.map(item=>`<article class="panel class-card"><p class="eyebrow">${escapePrintText(item.section)}</p><h3>${escapePrintText(item.subject)}</h3><p>${escapePrintText(item.schedule_label)}</p><div class="class-meta"><span>School year<strong>${escapePrintText(item.school_year)}</strong></span></div>${authenticatedUser?.role==='administrator'?`<div class="dialog-actions"><button class="secondary class-roster" data-class-id="${item.id}">Roster</button><button class="secondary class-policy" data-class-id="${item.id}">Rules</button><button class="secondary class-edit" data-class-id="${item.id}">Edit</button></div>`:''}</article>`).join(''):'<article class="panel empty-state">No classes configured yet</article>';const select=$('#classSelect');select.innerHTML=availableClasses.length?'<option value="">Choose a class…</option>'+availableClasses.map(item=>`<option value="${item.id}">${escapePrintText(item.section)} — ${escapePrintText(item.subject)}</option>`).join(''):'<option value="">No classes assigned</option>';$('#enrollmentClass').innerHTML=availableClasses.map(item=>`<option value="${item.id}">${escapePrintText(item.section)} — ${escapePrintText(item.subject)}</option>`).join('')}
async function loadUsers(){const response=await apiRequest('/api/v1/users');availableUsers=response.ok?await response.json():[];const teachers=availableUsers.filter(user=>user.role==='teacher');$('#teacherSelect').innerHTML='<option value="">Unassigned</option>'+teachers.map(user=>`<option value="${user.id}">${escapePrintText(user.full_name)}</option>`).join('')}
async function loadAcademicYears(){const response=await apiRequest('/api/v1/academic-years');availableAcademicYears=response.ok?await response.json():[];const writable=availableAcademicYears.filter(year=>['planning','active'].includes(year.state));$('#classAcademicYear').innerHTML=writable.map(year=>`<option value="${year.name}">${year.name} · ${year.state}</option>`).join('');renderAcademicYears()}
function renderAcademicYears(){const labels={planning:'Getting ready',active:'Current school year',closing:'Being finalized',archived:'Past school year'};$('#academicYearList').innerHTML=availableAcademicYears.length?availableAcademicYears.map(year=>`<div class="attention-row"><span><strong>${escapePrintText(year.name)}</strong><small>${labels[year.state]||year.state}${year.principal_approved_at?' · approved by principal':''}</small></span><span>${academicYearActions(year)}</span></div>`).join(''):'<div class="empty-state">No school years have been added</div>'}
function academicYearActions(year){if(authenticatedUser?.role==='administrator'){if(year.state==='planning')return`<button class="secondary year-action" data-id="${year.id}" data-state="active">Start school year</button>`;if(year.state==='active')return`<button class="secondary year-action" data-id="${year.id}" data-state="closing">Finish school year</button>`;if(year.state==='closing'&&year.principal_approved_at)return`<button class="primary year-promote" data-id="${year.id}">Review promotions</button> <button class="secondary year-action" data-id="${year.id}" data-state="archived">Move to past years</button>`}if(authenticatedUser?.role==='principal'&&year.state==='closing'&&!year.principal_approved_at)return`<button class="primary year-approve" data-id="${year.id}">Approve year-end</button>`;return''}

function refreshSectionOptions(){
  const sections=[...new Set(availableClasses.map(item=>item.section?.trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  const studentSelect=$('#studentSection'),currentStudentSection=studentSelect.value;
  studentSelect.innerHTML=sections.length
    ? '<option value="">Choose grade &amp; section…</option>'+sections.map(section=>`<option value="${escapePrintText(section)}">${escapePrintText(section)}</option>`).join('')
    : '<option value="">Create a class first</option>';
  if(sections.includes(currentStudentSection))studentSelect.value=currentStudentSection;
  const sectionFilter=$('#sectionFilter'),currentFilter=sectionFilter.value;
  sectionFilter.innerHTML='<option>All sections</option>'+sections.map(section=>`<option value="${escapePrintText(section)}">${escapePrintText(section)}</option>`).join('');
  if(sections.includes(currentFilter))sectionFilter.value=currentFilter;
}

const loadAcademicYearsOnline=loadAcademicYears;
loadAcademicYears=async function(){await loadAcademicYearsOnline();const filter=$('#reports .panel-head select'),selected=filter.value;filter.innerHTML='<option value="">All school years</option>'+availableAcademicYears.map(year=>`<option value="${year.name}">${year.name}</option>`).join('');if(availableAcademicYears.some(year=>year.name===selected))filter.value=selected};

const loadClassesOnline=loadClasses;
loadClasses=async function(){await loadClassesOnline();refreshSectionOptions();if(authenticatedUser?.role==='teacher'){for(const classItem of availableClasses){try{const response=await apiRequest(`/api/v1/classes/${classItem.id}/offline-package?device_id=${encodeURIComponent(getDeviceId())}`);if(response.ok){const packageRecord=await response.json();await EduScanDB.saveClassPackage({classId:classItem.id,...packageRecord,downloadedAt:new Date().toISOString()})}}catch{}}if(availableClasses.length)toast(`${availableClasses.length} class roster${availableClasses.length===1?'':'s'} ready offline`)}};

function canonicalJson(value){if(Array.isArray(value))return`[${value.map(canonicalJson).join(',')}]`;if(value&&typeof value==='object')return`{${Object.keys(value).sort().map(key=>`${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;return JSON.stringify(value)}
function decodeBase64Url(value){const normalized=value.replaceAll('-','+').replaceAll('_','/').padEnd(Math.ceil(value.length/4)*4,'=');return Uint8Array.from(atob(normalized),character=>character.charCodeAt(0))}
async function verifyOfflineAuthorization(envelope,classId){if(!envelope?.payload||!envelope.signature||!envelope.public_key)return false;const payload=envelope.payload,now=new Date();if(payload.class_id!==classId||payload.device_id!==getDeviceId()||payload.teacher_id!==authenticatedUser?.id||payload.max_sessions!==1||new Date(payload.not_before)>now||new Date(payload.expires_at)<now)return false;try{const key=await crypto.subtle.importKey('jwk',envelope.public_key,{name:'ECDSA',namedCurve:'P-256'},false,['verify']);return crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},key,decodeBase64Url(envelope.signature),new TextEncoder().encode(canonicalJson(payload)))}catch{return false}}
function isWithinOfflineSchedule(classInfo){if(classInfo?.weekday==null||!classInfo.start_time||!classInfo.end_time)return false;const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Manila',weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));const dayIndex={Mon:0,Tue:1,Wed:2,Thu:3,Fri:4,Sat:5,Sun:6}[parts.weekday],nowMinutes=Number(parts.hour)*60+Number(parts.minute),toMinutes=value=>{const [hour,minute]=value.split(':').map(Number);return hour*60+minute};return dayIndex===classInfo.weekday&&nowMinutes>=toMinutes(classInfo.start_time)-classInfo.open_before_minutes&&nowMinutes<=toMinutes(classInfo.end_time)+classInfo.close_after_minutes}
function activateSession(id,offlineAuthorization=null){activeSessionId=id;activeOfflineAuthorization=offlineAuthorization;activeSessionOpenedAt=new Date().toISOString();if(offlineAuthorization)EduScanDB.saveSession({id,authorization:offlineAuthorization,openedAt:activeSessionOpenedAt,closeStatus:'open'});session=true;scanIndex=0;sessionRoster=[];scannedCredentialPayloads.clear();scannedStudentLrns.clear();pendingVerification=null;$('#scanResult').hidden=true;$('#sessionPill').textContent=offlineAuthorization?'● Session live · offline':'● Session live';$('#sessionPill').classList.add('live');$('#startSession').disabled=true;$('#classSelect').disabled=true;$('#cameraButton').disabled=false;$('#qrImageButton').disabled=false;$('#closeSession').disabled=false;renderRoster();EduScanDB.getClassPackage(activeClassId).then(packageRecord=>{if(!packageRecord)return;sessionRoster=packageRecord.payload.roster.map(item=>({name:item.full_name,lrn:item.lrn,initials:item.full_name.split(' ').map(part=>part[0]).join('').slice(0,2)}));renderRoster()})}
$('#startSession').onclick=async()=>{const classId=$('#classSelect').value;if(!classId)return toast('Choose an assigned class first.');try{const response=await apiRequest(`/api/v1/classes/${classId}/sessions`,{method:'POST'});const result=await response.json();if(!response.ok)throw Object.assign(new Error(result.detail||'Session could not be opened'),{serverRejected:true});activateSession(result.id);toast('Attendance is open for this class')}catch(error){if(error.serverRejected)return toast(error.message);const packageRecord=await EduScanDB.getClassPackage(classId);if(!packageRecord||new Date(packageRecord.payload.expires_at)<=new Date()||!await verifyOfflineAuthorization(packageRecord.authorization,classId)||!isWithinOfflineSchedule(packageRecord.payload.class))return toast('Attendance cannot open offline outside this class schedule. Connect for an updated schedule.');activateSession(crypto.randomUUID(),packageRecord.authorization);toast('Attendance opened offline within the class schedule')}};
function resetClosedSession(){scanning=false;if(zxingControls){zxingControls.stop();zxingControls=undefined}if(stream)stream.getTracks().forEach(track=>track.stop());session=false;pendingVerification=null;activeSessionId=null;activeOfflineAuthorization=null;activeSessionOpenedAt=null;$('#camera').style.display='none';$('.camera-placeholder').style.display='grid';$('.scan-target').style.display='none';$('#scanResult').hidden=true;$('#sessionPill').textContent='Session closed';$('#sessionPill').classList.remove('live');$('#cameraButton').disabled=true;$('#qrImageButton').disabled=true;$('#cameraButton').textContent='Use camera';$('#closeSession').disabled=true;$('#startSession').disabled=false;$('#classSelect').disabled=false}
$('#closeSession').onclick=async()=>{if(!activeSessionId)return;if(pendingVerification)return toast('Confirm or reject the scanned student before closing.');const closingId=activeSessionId,authorization=activeOfflineAuthorization,openedAt=activeSessionOpenedAt;try{const response=await apiRequest(`/api/v1/attendance-sessions/${closingId}/close`,{method:'POST'});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Session could not be closed');if(authorization)await EduScanDB.markSessionsClosed([closingId]);resetClosedSession();toast(`Session closed · ${result.absences_created} absence${result.absences_created===1?'':'s'} created`)}catch(error){if(!authorization)return toast(error.message);await EduScanDB.saveSession({id:closingId,authorization,openedAt,closeStatus:'pending'});resetClosedSession();toast('Session closed safely offline · closure and absences will synchronize later');updateSyncStatus()}};
const startAuthorizedSession=$('#startSession').onclick;$('#startSession').onclick=event=>{activeClassId=$('#classSelect').value;return startAuthorizedSession(event)};
const closeAuthorizedSession=$('#closeSession').onclick;$('#closeSession').onclick=async event=>{await closeAuthorizedSession(event);if(!session)activeClassId=null};

$$('[data-close-dialog]').forEach(button=>button.onclick=()=>{$(`#${button.dataset.closeDialog}`).close()});
$('#createUserButton').onclick=()=>$('#userDialog').showModal();
$('#createClassButton').onclick=async()=>{await Promise.all([loadUsers(),loadAcademicYears()]);if(!$('#classAcademicYear').options.length)return toast('Create a planning or active academic year first.');const form=$('#classForm');form.reset();delete form.dataset.classId;form.querySelector('h2').textContent='Create class';form.querySelector('[type="submit"]').textContent='Create class';$('#classDialog').showModal()};
$('#enrollButton').onclick=()=>{if(!availableClasses.length||!students.length)return toast('Create a class and student first.');$('#enrollmentStudent').innerHTML=students.map(student=>`<option value="${student.id}">${escapePrintText(student.name)} · ${escapePrintText(student.section)}</option>`).join('');$('#enrollmentDialog').showModal()};
$('#userForm').onsubmit=async event=>{event.preventDefault();const form=event.target,data=Object.fromEntries(new FormData(form));const response=await apiRequest('/api/v1/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)return toast(result.detail||'Account could not be created');form.reset();$('#userDialog').close();await loadUsers();toast(`${result.full_name} account created`)};
$('#classForm').onsubmit=async event=>{event.preventDefault();const form=event.target,data=Object.fromEntries(new FormData(form)),days=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];if(data.end_time<=data.start_time)return toast(data.end_time==='00:00'?'For 12 noon, choose 12:00. The value 00:00 means 12 midnight.':'End time must be later than start time on the same day.');data.weekday=Number(data.weekday);data.schedule_label=`${days[data.weekday]} ${data.start_time}-${data.end_time}`;if(!data.teacher_id)data.teacher_id=null;const editing=form.dataset.classId,response=await apiRequest(editing?`/api/v1/classes/${editing}`:'/api/v1/classes',{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)return toast(result.detail||'Class could not be saved');form.reset();delete form.dataset.classId;$('#classDialog').close();await loadClasses();toast(`${result.subject} class ${editing?'updated':'created'}`)};
$('#enrollmentForm').onsubmit=async event=>{event.preventDefault();const form=event.target,data=Object.fromEntries(new FormData(form));const response=await apiRequest(`/api/v1/classes/${data.class_id}/enrollments`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_id:data.student_id})});const result=await response.json();if(!response.ok)return toast(result.detail||'Student could not be enrolled');$('#enrollmentDialog').close();toast('Student enrolled successfully')};
let profileStudent=null;
const changeSectionButton=document.createElement('button');changeSectionButton.type='button';changeSectionButton.id='changeSectionButton';changeSectionButton.className='secondary admin-only';changeSectionButton.textContent='Change section';$('#studentStatusButton').before(changeSectionButton);
document.addEventListener('click',event=>{const button=event.target.closest('.student-view');if(!button)return;profileStudent=students.find(student=>student.id===button.dataset.studentId);if(!profileStudent)return;$('#profileSex').value=profileStudent.sex||'';$('#profileStudentName').textContent=profileStudent.name;$('#profileStudentMeta').textContent=`${profileStudent.section} · LRN ending ${profileStudent.lrn.slice(-4)}${profileStudent.isActive?'':` · inactive: ${profileStudent.inactiveReason}`}`;$('#profilePhoto').src=profileStudent.photographUrl||'icons/icon.svg';$('#studentStatusButton').textContent=profileStudent.isActive?'Set inactive':'Reactivate';$('#studentStatusButton').hidden=authenticatedUser?.role!=='administrator';$('#studentProfileDialog').showModal();renderStudentDetails();loadStudentMovementHistory()});
changeSectionButton.onclick=()=>{if(!profileStudent||authenticatedUser?.role!=='administrator')return;const sections=[...new Set(availableClasses.map(item=>item.section).filter(Boolean))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));$('#sectionChangeSelect').innerHTML=sections.map(section=>`<option value="${escapePrintText(section)}">${escapePrintText(section)}</option>`).join('');$('#sectionChangeSelect').value=profileStudent.section;$('#sectionChangeDialog').showModal()};
$('#sectionChangeForm').onsubmit=async event=>{event.preventDefault();if(!profileStudent)return;const section=new FormData(event.target).get('section'),response=await apiRequest(`/api/v1/students/${profileStudent.id}/section`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({section})});const result=await response.json();if(!response.ok)return toast(result.detail||'Student section could not be changed');profileStudent.section=result.section;$('#sectionChangeDialog').close();$('#studentProfileDialog').close();renderStudents();toast(`Section updated · ${result.enrolled_class_ids.length} matching class${result.enrolled_class_ids.length===1?'':'es'} assigned`)};
$('#uploadPhotoButton').onclick=()=>$('#profilePhotoFile').click();
$('#profilePhotoFile').onchange=async event=>{const file=event.target.files[0];event.target.value='';if(!file||!profileStudent)return;const body=new FormData();body.append('file',file);const response=await apiRequest(`/api/v1/students/${profileStudent.id}/photograph`,{method:'POST',body});const result=await response.json();if(!response.ok)return toast(result.detail||'Photograph upload failed');profileStudent.photographUrl=`${getApiBase()}${result.photograph_url}?v=${Date.now()}`;$('#profilePhoto').src=profileStudent.photographUrl;toast('Student photograph updated')};
$('#replaceQrButton').onclick=()=>{if(!profileStudent)return;$('#qrActionTitle').textContent=`Replace ${profileStudent.name}'s QR`;$('#qrActionForm').elements.action.value='replace';$('#qrActionDialog').showModal()};
$('#revokeQrButton').onclick=()=>{if(!profileStudent)return;$('#qrActionTitle').textContent=`Revoke ${profileStudent.name}'s QR`;$('#qrActionForm').elements.action.value='revoke';$('#qrActionDialog').showModal()};
$('#studentStatusButton').onclick=async()=>{
  if(!profileStudent||authenticatedUser?.role!=='administrator')return;
  const form=$('#studentStatusForm');form.reset();$('#studentStatusError').textContent='';await loadAcademicYears();
  const years=availableAcademicYears.filter(year=>['planning','active'].includes(year.state));
  $('#studentStatusYear').innerHTML=years.map(year=>`<option value="${escapePrintText(year.name)}">${escapePrintText(year.name)}</option>`).join('');
  $('#studentStatusYear').value=years.find(year=>year.state==='active')?.name||years[0]?.name||'';
  $('#studentStatusTitle').textContent=profileStudent.isActive?'Set student inactive':'Reactivate student';
  $('#studentStatusReasonLabel').hidden=!profileStudent.isActive;form.elements.reason.disabled=!profileStudent.isActive;
  form.elements.effective_on.value=schoolToday();form.elements.effective_on.max=schoolToday();
  $('#studentStatusDialog').showModal();
};
$('#qrActionForm').onsubmit=async event=>{event.preventDefault();if(!profileStudent)return;const form=event.target,data=Object.fromEntries(new FormData(form)),action=data.action;const response=await apiRequest(`/api/v1/students/${profileStudent.id}/qr-credential/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:data.reason})});const result=await response.json();if(!response.ok)return toast(result.detail||'QR action failed');$('#qrActionDialog').close();if(action==='replace'){Object.assign(profileStudent,studentFromApi(result));renderStudents();renderQrLibrary();toast('Old QR revoked and replacement issued')}else{profileStudent.qr='Revoked · '+data.reason;profileStudent.qrUrl=null;profileStudent.credentialId=null;renderStudents();renderQrLibrary();toast('QR credential revoked · the physical card no longer works')}};
$('#profileDownloadQr').onclick=()=>{if(!profileStudent?.qrUrl)return toast('This student has no active QR to download.');const link=document.createElement('a');link.href=profileStudent.qrUrl;link.download=`${profileStudent.name.replaceAll(' ','-').toLowerCase()}-eduscan-qr.svg`;link.click()};
let currentReportSummary=null;async function loadReportSummary(){const filter=$('#reports .panel-head select'),year=filter?.value||'',query=year?`?academic_year=${encodeURIComponent(year)}`:'';const response=await apiRequest(`/api/v1/reports/attendance-summary${query}`);if(!response.ok)return;const report=await response.json();currentReportSummary=report;$('#presentStat').textContent=report.counts.present;$('#lateStat').textContent=report.counts.late;const absentCard=[...$$('.stat-card span')].find(element=>element.textContent.trim()==='Absent')?.parentElement?.querySelector('strong');if(absentCard)absentCard.textContent=report.counts.absent;const banner=$('#reports .report-banner');banner.querySelector('strong').textContent=`${report.attendance_rate}%`;banner.querySelector('small').textContent=`Based on ${report.total} attendance record${report.total===1?'':'s'}`;$('#reportTable').innerHTML=report.sections.length?report.sections.map(row=>`<tr><td>${escapePrintText(row.section)}</td><td>${escapePrintText(row.adviser)}</td><td>${row.present}</td><td>${row.late}</td><td>${row.absent}</td><td>${row.attendance_rate}%</td></tr>`).join(''):'<tr><td colspan="6"><div class="empty-state">No attendance data for this school year</div></td></tr>'}
$('#downloadReport').onclick=async()=>{if(!currentReportSummary)await loadReportSummary();if(!currentReportSummary)return toast('Report data is unavailable.');const rows=['section,adviser,present,late,absent,excused,total,attendance_rate',...currentReportSummary.sections.map(row=>[row.section,row.adviser,row.present,row.late,row.absent,row.excused,row.total,row.attendance_rate].map(csvEscape).join(','))];download(`eduscan-attendance-${new Date().toISOString().slice(0,10)}.csv`,rows.join('\r\n'))};
$('#reports .panel-head select').onchange=loadReportSummary;
const reportsNavigation=$('.nav-item[data-view="reports"]');reportsNavigation.onclick=async()=>{await loadReportSummary();showView('reports')};
$('#settingsButton').onclick=()=>$('#settingsDialog').showModal();
$('#passwordForm').onsubmit=async event=>{event.preventDefault();const form=event.target,data=Object.fromEntries(new FormData(form));const response=await apiRequest('/api/v1/auth/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!response.ok){const result=await response.json();return toast(result.detail||'Password could not be changed')}form.reset();$('#settingsDialog').close();await EduScanDB.clearSensitiveData();authenticatedUser=null;showLogin('Password changed. Sign in again on this device.')};
async function loadClassRoster(classId){const classItem=availableClasses.find(item=>item.id===classId),response=await apiRequest(`/api/v1/classes/${classId}/roster`);if(!response.ok)return toast('Class roster could not be loaded.');const roster=await response.json();$('#rosterDialog').dataset.classId=classId;$('#rosterDialogTitle').textContent=`${classItem?.section||'Class'} · ${classItem?.subject||'Roster'} (${roster.length})`;$('#classRosterList').innerHTML=roster.length?roster.map(student=>`<div class="attention-row"><span><strong>${escapePrintText(student.full_name)}</strong><small>${escapePrintText(student.section)} · LRN ending ${student.lrn.slice(-4)}${student.is_active?'':' · inactive'}</small></span><button class="danger-button roster-remove" data-student-id="${student.id}">Remove</button></div>`).join(''):'<div class="empty-state">No students are enrolled</div>';$('#rosterDialog').showModal()}
$('#classGrid').onclick=async event=>{const policyButton=event.target.closest('.class-policy'),editButton=event.target.closest('.class-edit'),rosterButton=event.target.closest('.class-roster');if(rosterButton)return loadClassRoster(rosterButton.dataset.classId);if(editButton){await Promise.all([loadUsers(),loadAcademicYears()]);const item=availableClasses.find(entry=>entry.id===editButton.dataset.classId),form=$('#classForm');if(!item)return;form.dataset.classId=item.id;form.elements.subject.value=item.subject;form.elements.section.value=item.section;form.elements.school_year.value=item.school_year;form.elements.weekday.value=item.weekday;form.elements.start_time.value=item.start_time;form.elements.end_time.value=item.end_time;form.elements.teacher_id.value=item.teacher_id||'';form.querySelector('h2').textContent='Edit class assignment';form.querySelector('[type="submit"]').textContent='Save changes';return $('#classDialog').showModal()}if(!policyButton)return;const response=await apiRequest(`/api/v1/classes/${policyButton.dataset.classId}/policy`);if(!response.ok)return toast('Attendance rules could not be loaded.');const policy=await response.json(),form=$('#policyForm');form.elements.class_id.value=policyButton.dataset.classId;form.elements.grace_minutes.value=policy.grace_minutes;form.elements.offline_package_hours.value=policy.offline_package_hours;form.elements.open_before_minutes.value=policy.open_before_minutes;form.elements.close_after_minutes.value=policy.close_after_minutes;$('#policyDialog').showModal()};
$('#classRosterList').onclick=async event=>{const button=event.target.closest('.roster-remove');if(!button)return;if(!confirm('Remove this student from this class? Existing attendance history will be kept.'))return;const classId=$('#rosterDialog').dataset.classId,response=await apiRequest(`/api/v1/classes/${classId}/enrollments/${button.dataset.studentId}`,{method:'DELETE'});if(!response.ok){const result=await response.json();return toast(result.detail||'Student could not be removed')}await loadClassRoster(classId);toast('Student removed from this class')};
$('#policyForm').onsubmit=async event=>{event.preventDefault();const form=event.target,data=Object.fromEntries(new FormData(form));const response=await apiRequest(`/api/v1/classes/${data.class_id}/policy`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({grace_minutes:Number(data.grace_minutes),offline_package_hours:Number(data.offline_package_hours),open_before_minutes:Number(data.open_before_minutes),close_after_minutes:Number(data.close_after_minutes)})});if(!response.ok){const result=await response.json();return toast(result.detail||'Rules could not be saved')}$('#policyDialog').close();toast('Attendance rules saved')};
$('#yearButton').onclick=async()=>{await loadAcademicYears();$('#academicYearDialog').showModal()};
$('#academicYearForm').onsubmit=async event=>{event.preventDefault();const form=event.target,data=Object.fromEntries(new FormData(form));if(!data.starts_on)data.starts_on=null;if(!data.ends_on)data.ends_on=null;const response=await apiRequest('/api/v1/academic-years',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)return toast(result.detail||'School year could not be added');form.reset();await loadAcademicYears();toast(`${result.name} added · you can set up classes now`)};
async function openPromotionReview(yearId){const response=await apiRequest(`/api/v1/academic-years/${yearId}/promotion-preview`),result=await response.json();if(!response.ok)return toast(result.detail||'Promotion review could not be opened');const pending=result.students.filter(student=>!student.already_processed);if(!result.target_years.length)return toast('Create the next school year in Planning before reviewing promotions.');if(!pending.length)return toast('Every student in this school year has already been reviewed.');$('#promotionForm').dataset.sourceYearId=yearId;$('#promotionSourceLabel').textContent=`${result.source_year.name} · ${pending.length} student${pending.length===1?'':'s'} to review`;$('#promotionTargetYear').innerHTML=result.target_years.map(year=>`<option value="${year.id}">${year.name}</option>`).join('');$('#promotionStudentList').innerHTML=pending.map(student=>`<div class="promotion-row" data-student-id="${student.student_id}"><span><strong>${escapePrintText(student.full_name)}</strong><small>${escapePrintText(student.current_section)} · LRN ending ${student.lrn_suffix}</small></span><select class="promotion-action"><option value="promoted" ${student.suggested_action==='promoted'?'selected':''}>Promoted</option><option value="retained" ${student.suggested_action==='retained'?'selected':''}>Retained</option><option value="graduated" ${student.suggested_action==='graduated'?'selected':''}>Graduated</option><option value="transferred">Transferred</option><option value="withdrawn">Withdrawn</option></select><input class="promotion-section" value="${escapePrintText(student.suggested_section||student.current_section)}" aria-label="Target section"></div>`).join('');$$('.promotion-row').forEach(row=>{const action=row.querySelector('.promotion-action'),section=row.querySelector('.promotion-section'),toggle=()=>{section.disabled=!['promoted','retained'].includes(action.value)};action.onchange=toggle;toggle()});$('#promotionDialog').showModal()}
$('#promotionForm').onsubmit=async event=>{event.preventDefault();const form=event.target,decisions=$$('.promotion-row').map(row=>({student_id:row.dataset.studentId,action:row.querySelector('.promotion-action').value,target_section:row.querySelector('.promotion-section').disabled?null:row.querySelector('.promotion-section').value.trim()}));if(decisions.some(item=>['promoted','retained'].includes(item.action)&&!item.target_section))return toast('Every promoted or retained student needs a target section.');if(!confirm(`Apply ${decisions.length} reviewed promotion decision${decisions.length===1?'':'s'}? This will update active student records.`))return;const response=await apiRequest(`/api/v1/academic-years/${form.dataset.sourceYearId}/promotions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_year_id:$('#promotionTargetYear').value,decisions})}),result=await response.json();if(!response.ok)return toast(result.detail||'Promotions could not be applied');$('#promotionDialog').close();await Promise.all([loadStudents(),loadAcademicYears(),loadClasses()]);toast(`${result.processed} student promotion${result.processed===1?'':'s'} applied and recorded`)};
$('#academicYearList').onclick=async event=>{const action=event.target.closest('.year-action'),approval=event.target.closest('.year-approve'),promotion=event.target.closest('.year-promote');if(promotion)return openPromotionReview(promotion.dataset.id);if(!action&&!approval)return;const body=action?{state:action.dataset.state}:null;if(action?.dataset.state==='archived'){const year=availableAcademicYears.find(item=>item.id===action.dataset.id),backup=prompt('Enter the completed backup filename or reference:');if(!backup)return;const confirmation=prompt(`Type ARCHIVE ${year.name} to make this year permanently read-only:`);if(confirmation!==`ARCHIVE ${year.name}`)return toast('Archive confirmation did not match.');body.backup_reference=backup;body.confirmation=confirmation}const path=approval?`/api/v1/academic-years/${approval.dataset.id}/approve-closing`:`/api/v1/academic-years/${action.dataset.id}/transition`;const options={method:'POST'};if(action){options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body)}const response=await apiRequest(path,options);if(!response.ok){const result=await response.json();return toast(result.detail||'Academic-year action failed')}await loadAcademicYears();await loadClasses();toast(approval?'Closing approved by principal':'Academic-year state updated')};
restoreAuthentication();

// SF4 uses the supplied Excel template and explicitly reviewed monthly figures.
const sf4Fields=[['registered','Registered learners'],['attendance','Attendance learner-days'],['dropout_previous','Dropped out: previous cumulative'],['dropout_month','Dropped out: this month'],['transfer_out_previous','Transferred out: previous cumulative'],['transfer_out_month','Transferred out: this month'],['transfer_in_previous','Transferred in: previous cumulative'],['transfer_in_month','Transferred in: this month']];
let sf4LoadedContext='';
function sf4Context(){const form=$('#sf4Form');return ['academic_year','month','school_level'].map(key=>form.elements[key].value).join('|')}
function sf4Error(error){return typeof error==='string'?error:Array.isArray(error)?error.map(item=>`${item.loc?.slice(1).join(' → ')}: ${item.msg}`).join('; '):'The report could not be generated.'}
$('#studentSexForm').onsubmit=async event=>{
  event.preventDefault();if(!profileStudent)return;
  const button=event.target.querySelector('button');button.disabled=true;
  try{
    const sex=$('#profileSex').value,response=await apiRequest(`/api/v1/students/${profileStudent.id}/sex`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({sex})});
    const result=await response.json();if(!response.ok)throw new Error(sf4Error(result.detail));
    profileStudent.sex=result.sex;profileStudent.profileDetails.sex=result.sex;renderStudentDetails();toast('Student sex saved for SF4 reporting');
  }catch(error){toast(error.message||'Connect to the server to save this record.')}finally{button.disabled=false}
};
$('#createSf4').onclick=async()=>{
  $('#sf4Error').textContent='';$('#sf4Rows').replaceChildren();$('#downloadSf4').disabled=true;sf4LoadedContext='';
  try{
    await loadAcademicYears();
    const selected=$('#reports .panel-head select').value;
    $('#sf4Year').innerHTML=availableAcademicYears.map(year=>`<option value="${escapePrintText(year.name)}">${escapePrintText(year.name)}</option>`).join('');
    $('#sf4Year').value=selected||availableAcademicYears.find(year=>year.state==='active')?.name||availableAcademicYears[0]?.name||'';
    const form=$('#sf4Form');if(!form.elements.month.value){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Manila',year:'numeric',month:'2-digit'}).formatToParts(new Date());form.elements.month.value=`${parts.find(part=>part.type==='year').value}-${parts.find(part=>part.type==='month').value}`}
    $('#sf4Dialog').showModal();
  }catch{toast('Connect to the server to create an SF4 report.')}
};
$('#sf4Settings').onchange=event=>{
  if(['academic_year','month','school_level'].includes(event.target.name)&&sf4LoadedContext&&sf4Context()!==sf4LoadedContext){$('#sf4Rows').replaceChildren();$('#downloadSf4').disabled=true;sf4LoadedContext='';$('#sf4Error').textContent='Period or school level changed. Load section figures again.'}
  updateSf4Previews();
};
$('#loadSf4').onclick=async()=>{
  if(![...$('#sf4Settings').querySelectorAll('input,select')].every(input=>input.reportValidity()))return;
  const form=$('#sf4Form'),button=$('#loadSf4'),context=sf4Context();button.disabled=true;$('#sf4Error').textContent='';
  try{
    const response=await apiRequest(`/api/v1/reports/sf4?${new URLSearchParams({academic_year:form.elements.academic_year.value,month:form.elements.month.value})}`),result=await response.json();
    if(!response.ok)throw new Error(sf4Error(result.detail));
    if(context!==sf4Context())return;
    if(!result.rows.length)throw new Error('No assigned sections were found for this school year.');
    const grades=form.elements.school_level.value==='elementary'?['K','1','2','3','4','5','6','NG']:['7','8','9','10','11','12','NG'];
    $('#sf4Rows').innerHTML=result.rows.map((row,index)=>`<section class="sf4-section" data-section="${escapePrintText(row.section)}"><h3>${escapePrintText(row.section)}</h3><p class="sf4-note">${row.recorded_days} day(s) have closed attendance records for this month.</p>${row.missing_sex?`<p class="sf4-warning">${row.missing_sex} enrolled learner(s) have no sex recorded. Update their student profiles and reload, or enter verified SF2 male/female figures below.</p>`:''}<div class="form-grid"><label>Advisory teacher<input data-field="adviser" value="${escapePrintText(row.adviser)}" maxlength="160" required></label><label>Grade/year level<select data-field="grade" required><option value="">Choose grade</option>${grades.map(grade=>`<option value="${grade}" ${grade===row.grade?'selected':''}>${grade==='K'?'Kinder':grade==='NG'?'Non-graded':`Grade ${grade}`}</option>`).join('')}</select></label></div><div class="sf4-pairs">${sf4Fields.map(([key,label])=>`<fieldset class="sf4-pair"><legend>${label}</legend>${['male','female'].map(sex=>`<label>${sex==='male'?'M':'F'}<input type="number" min="0" max="100000" step="1" data-field="${key}" data-sex="${sex}" aria-label="${escapePrintText(row.section)} ${label} ${sex}" value="${row[key]?.[sex]??''}" required></label>`).join('')}</fieldset>`).join('')}</div><p class="sf4-preview" aria-live="polite"></p></section>`).join('');
    sf4LoadedContext=context;$('#downloadSf4').disabled=false;updateSf4Previews();
  }catch(error){$('#sf4Error').textContent=error.message||'Connect to the server to load SF4 figures.'}finally{button.disabled=false}
};
function updateSf4Previews(){
  const days=Number($('#sf4Form').elements.school_days.value);
  $$('#sf4Rows .sf4-section').forEach(section=>{
    const get=(field,sex)=>{const input=section.querySelector(`[data-field="${field}"][data-sex="${sex}"]`);return input.value===''?null:Number(input.value)};
    const registered=['male','female'].map(sex=>get('registered',sex)),attended=['male','female'].map(sex=>get('attendance',sex));
    const preview=section.querySelector('.sf4-preview');
    if(!days||[...registered,...attended].some(value=>value===null)){preview.textContent='Complete M/F enrollment and attendance to calculate averages.';return}
    const total=registered[0]+registered[1],learnerDays=attended[0]+attended[1];
    const rate=(value,count)=>count?(value/(count*days)*100).toFixed(2):'0.00';
    preview.textContent=`Registered: M ${registered[0]}, F ${registered[1]}, total ${total} · Daily average: M ${(attended[0]/days).toFixed(2)}, F ${(attended[1]/days).toFixed(2)}, total ${(learnerDays/days).toFixed(2)} · Attendance: M ${rate(attended[0],registered[0])}%, F ${rate(attended[1],registered[1])}%, total ${rate(learnerDays,total)}%`;
  });
}
$('#sf4Rows').oninput=updateSf4Previews;
$('#sf4Form').onsubmit=async event=>{
  event.preventDefault();const form=event.target,button=$('#downloadSf4');$('#sf4Error').textContent='';
  if(!sf4LoadedContext||sf4LoadedContext!==sf4Context()){ $('#sf4Error').textContent='Load section figures for the selected period first.';return }
  if(!form.reportValidity())return;
  const payload=Object.fromEntries(new FormData(form));payload.school_days=Number(payload.school_days);
  payload.rows=$$('#sf4Rows .sf4-section').map(section=>{
    const row={section:section.dataset.section,adviser:section.querySelector('[data-field="adviser"]').value.trim(),grade:section.querySelector('[data-field="grade"]').value};
    for(const [key] of sf4Fields)row[key]=Object.fromEntries(['male','female'].map(sex=>[sex,Number(section.querySelector(`[data-field="${key}"][data-sex="${sex}"]`).value)]));
    return row;
  });
  button.disabled=true;button.textContent='Generating…';
  try{
    const response=await apiRequest('/api/v1/reports/sf4',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok){const result=await response.json();throw new Error(sf4Error(result.detail))}
    download(`eduscan-sf4-${payload.month}.xlsx`,await response.blob(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');toast('SF4 Excel report downloaded');
  }catch(error){$('#sf4Error').textContent=error.message||'Connect to the server to download the report.'}finally{button.disabled=false;button.textContent='Download complete SF4 (.xlsx)'}
};


function schoolToday(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Manila',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
function setStudentDateLimits(form){for(const name of ['date_of_birth','enrollment_date'])if(form.elements[name])form.elements[name].max=schoolToday()}
function refreshStudentCreateSections(){
  const year=$('#studentAcademicYear').value,select=$('#studentSection'),current=select.value;
  const sections=[...new Set(availableClasses.filter(item=>item.school_year===year).map(item=>item.section))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  select.innerHTML=sections.length?sections.map(section=>`<option value="${escapePrintText(section)}">${escapePrintText(section)}</option>`).join(''):'<option value="">No classes for this school year</option>';
  if(sections.includes(current))select.value=current;
}
$('#studentAcademicYear').onchange=refreshStudentCreateSections;
async function saveStudentPhotograph(student,file){
  const body=new FormData();body.append('file',file);
  const response=await apiRequest(`/api/v1/students/${student.id}/photograph`,{method:'POST',body}),result=await response.json();
  if(!response.ok)throw new Error(sf4Error(result.detail));
  student.photographUrl=`${getApiBase()}${result.photograph_url}?v=${Date.now()}`;student.profileDetails.photograph_url=result.photograph_url;
}
function renderStudentDetails(){
  if(!profileStudent)return;const details=profileStudent.profileDetails;
  const fields=[['Sex',details.sex],['Date of birth',details.date_of_birth],['Age',details.age==null?null:`${details.age} years`],['Enrollment date',details.enrollment_date],['Enrollment type',details.enrollment_type==='transferred_in'?'Transferred in':'Regular'],['Parent / guardian',details.guardian_name],['Contact number',details.guardian_phone],['Home address',details.address]];
  $('#profileDetails').innerHTML=fields.map(([label,value])=>`<dt>${label}</dt><dd>${value?escapePrintText(value):'Not recorded'}</dd>`).join('');
}
async function loadStudentMovementHistory(){
  if(!profileStudent)return;const studentId=profileStudent.id;$('#studentMovementHistory').textContent='Loading history…';
  try{
    const response=await apiRequest(`/api/v1/students/${studentId}/movements`),rows=await response.json();
    if(!response.ok)throw new Error(sf4Error(rows.detail));if(profileStudent?.id!==studentId)return;
    $('#studentMovementHistory').innerHTML=rows.length?rows.map(row=>`<article><strong>${escapePrintText(row.kind.replaceAll('_',' '))} · ${escapePrintText(row.effective_on)}</strong><p>${escapePrintText(row.school_year)} · ${escapePrintText(row.section)}</p>${row.reason?`<p>${escapePrintText(row.reason)}</p>`:''}</article>`).join(''):'No dated movement records yet. Earlier history has not been inferred.';
  }catch(error){if(profileStudent?.id===studentId)$('#studentMovementHistory').textContent=error.message||'History is unavailable.'}
}
$('#editStudentProfile').onclick=()=>{
  if(!profileStudent)return;const form=$('#studentEditForm');
  for(const input of form.querySelectorAll('[name]'))input.value=profileStudent.profileDetails[input.name]??'';
  setStudentDateLimits(form);$('#studentEditError').textContent='';$('#studentEditDialog').showModal();
};
$('#studentEditForm').onsubmit=async event=>{
  event.preventDefault();if(!profileStudent)return;const form=event.target,button=form.querySelector('[type="submit"]');button.disabled=true;$('#studentEditError').textContent='';
  try{
    const response=await apiRequest(`/api/v1/students/${profileStudent.id}/profile`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(form)))}),result=await response.json();
    if(!response.ok)throw new Error(sf4Error(result.detail));
    Object.assign(profileStudent.profileDetails,result);Object.assign(profileStudent,{name:result.full_name,firstName:result.first_name,lastName:result.last_name,sex:result.sex,initials:result.full_name.split(' ').map(part=>part[0]).join('').slice(0,2)});
    $('#profileStudentName').textContent=profileStudent.name;$('#profileSex').value=profileStudent.sex;renderStudentDetails();renderStudents();renderQrLibrary();loadStudentMovementHistory();$('#studentEditDialog').close();toast('Student details saved');
  }catch(error){$('#studentEditError').textContent=error.message||'Could not save the student profile.'}finally{button.disabled=false}
};
$('#studentStatusForm').onsubmit=async event=>{
  event.preventDefault();if(!profileStudent)return;const form=event.target,button=form.querySelector('[type="submit"]');button.disabled=true;$('#studentStatusError').textContent='';
  try{
    const data=Object.fromEntries(new FormData(form));data.is_active=!profileStudent.isActive;if(data.is_active)data.reason=null;
    const response=await apiRequest(`/api/v1/students/${profileStudent.id}/status`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),result=await response.json();
    if(!response.ok)throw new Error(sf4Error(result.detail));
    $('#studentStatusDialog').close();$('#studentProfileDialog').close();await loadStudents();toast(result.is_active?'Student reactivated. Issue a replacement QR card.':'Student made inactive; the movement date and reason were saved.');
  }catch(error){$('#studentStatusError').textContent=error.message||'Could not update the student status.'}finally{button.disabled=false}
};
