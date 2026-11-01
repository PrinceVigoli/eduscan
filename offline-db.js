/** Minimal IndexedDB store for offline-first attendance. */
window.EduScanDB = (() => {
  const DB_NAME = 'eduscan-local';
  const DB_VERSION = 4;
  let connection;
  let activeUserId = null;
  function setActiveUser(userId) { activeUserId = userId || null; }
  function owned(item) { return item && item.ownerUserId === activeUserId; }

  function open() {
    if (connection) return connection;
    connection = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains('attendance')) {
          const store = db.createObjectStore('attendance', { keyPath: 'id' });
          store.createIndex('syncStatus', 'syncStatus');
          store.createIndex('sessionId', 'sessionId');
        }
        if (!db.objectStoreNames.contains('classPackages')) {
          db.createObjectStore('classPackages', { keyPath: 'classId' });
        }
        if (!db.objectStoreNames.contains('sessions')) {
          const sessions = db.createObjectStore('sessions', { keyPath: 'id' });
          sessions.createIndex('closeStatus', 'closeStatus');
        }
        if (!db.objectStoreNames.contains('verificationAttempts')) {
          const attempts = db.createObjectStore('verificationAttempts', { keyPath: 'id' });
          attempts.createIndex('syncStatus', 'syncStatus');
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return connection;
  }

  async function transaction(mode, operation) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('attendance', mode);
      const store = tx.objectStore('attendance');
      const request = operation(store);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  const saveAttendance = record => transaction('readwrite', store => store.put({ ...record, ownerUserId: activeUserId }));
  const getPending = async () => (await transaction('readonly', store => store.index('syncStatus').getAll('pending'))).filter(owned);
  const countPending = async () => (await getPending()).length;
  async function packageTransaction(mode, operation) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('classPackages', mode);
      const request = operation(tx.objectStore('classPackages'));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  const saveClassPackage = item => packageTransaction('readwrite', store => store.put({ ...item, ownerUserId: activeUserId }));
  const getClassPackage = async classId => { const item = await packageTransaction('readonly', store => store.get(classId)); return owned(item) ? item : undefined; };
  async function sessionTransaction(mode, operation) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('sessions', mode);
      const request = operation(tx.objectStore('sessions'));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  const saveSession = item => sessionTransaction('readwrite', store => store.put({ ...item, ownerUserId: activeUserId }));
  const getPendingSessionClosures = async () => (await sessionTransaction('readonly', store => store.index('closeStatus').getAll('pending'))).filter(owned);
  async function markSessionsClosed(ids) { for (const id of ids) { const item = await sessionTransaction('readonly', store => store.get(id)); if (item) await saveSession({ ...item, closeStatus: 'synced' }); } }
  async function markSynced(ids) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('attendance', 'readwrite');
      const store = tx.objectStore('attendance');
      ids.forEach(id => {
        const request = store.get(id);
        request.onsuccess = () => request.result && store.put({ ...request.result, syncStatus: 'synced', syncedAt: new Date().toISOString() });
      });
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
  async function markConflicts(conflicts) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('attendance', 'readwrite');
      const store = tx.objectStore('attendance');
      conflicts.forEach(conflict => {
        const request = store.get(conflict.record_id);
        request.onsuccess = () => request.result && store.put({ ...request.result, syncStatus: 'conflict', conflictReason: conflict.reason });
      });
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
  async function attemptTransaction(mode, operation) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('verificationAttempts', mode);
      const request = operation(tx.objectStore('verificationAttempts'));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  const saveVerificationAttempt = item => attemptTransaction('readwrite', store => store.put({ ...item, ownerUserId: activeUserId }));
  const getPendingVerificationAttempts = async () => (await attemptTransaction('readonly', store => store.index('syncStatus').getAll('pending'))).filter(owned);
  async function markVerificationAttemptsSynced(ids) { for (const id of ids) { const item = await attemptTransaction('readonly', store => store.get(id)); if (item) await saveVerificationAttempt({ ...item, syncStatus: 'synced' }); } }
  async function clearSensitiveData() {
    const db = await open();
    await new Promise((resolve, reject) => { const tx=db.transaction('classPackages','readwrite');tx.objectStore('classPackages').clear();tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error); });
    activeUserId = null;
  }
  return { open, setActiveUser, clearSensitiveData, saveAttendance, getPending, countPending, markSynced, markConflicts, saveClassPackage, getClassPackage, saveSession, getPendingSessionClosures, markSessionsClosed, saveVerificationAttempt, getPendingVerificationAttempts, markVerificationAttemptsSynced };
})();
