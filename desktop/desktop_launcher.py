from __future__ import annotations

import base64, ctypes, json, mimetypes, os, secrets, sys, threading, time, traceback, urllib.request, webbrowser
from pathlib import Path

APP_PORT=8765
APP_URL=f"http://127.0.0.1:{APP_PORT}"

def message(title:str,text:str,error:bool=False)->None: ctypes.windll.user32.MessageBoxW(None,text,title,0x10 if error else 0x40)
def bundle_root()->Path:return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))
def data_root()->Path:
    root=Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData"/"Local"))/"EduScan";root.mkdir(parents=True,exist_ok=True);return root

def configure_environment()->tuple[Path,Path]:
    bundled=bundle_root();backend=bundled/"backend"
    if str(backend) not in sys.path:sys.path.insert(0,str(backend))
    storage=data_root();uploads=storage/"uploads";uploads.mkdir(exist_ok=True);(storage/"backups").mkdir(exist_ok=True)
    config_path=storage/"desktop-config.json"
    if config_path.is_file():config=json.loads(config_path.read_text(encoding="utf-8"))
    else:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key=ec.generate_private_key(ec.SECP256R1());der=key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        config={"offline_signing_key":secrets.token_urlsafe(48),"offline_private_key_der":base64.urlsafe_b64encode(der).rstrip(b"=").decode("ascii")};config_path.write_text(json.dumps(config,indent=2),encoding="utf-8")
    database=(storage/"eduscan.db").as_posix()
    os.environ.update({"EDUSCAN_DATABASE_URL":f"sqlite:///{database}","EDUSCAN_ALLOWED_ORIGINS":APP_URL,"EDUSCAN_SESSION_DAYS":"7","EDUSCAN_SECURE_COOKIES":"false","EDUSCAN_OFFLINE_SIGNING_KEY":config["offline_signing_key"],"EDUSCAN_OFFLINE_PRIVATE_KEY_DER":config["offline_private_key_der"],"EDUSCAN_UPLOAD_DIR":str(uploads),"EDUSCAN_AUTO_CREATE_SCHEMA":"false"})
    os.chdir(storage);return bundled,storage

def migrate_database(bundled:Path)->None:
    from alembic import command
    from alembic.config import Config
    config=Config(str(bundled/"backend"/"alembic.ini"));config.set_main_option("script_location",str(bundled/"backend"/"migrations").replace("%","%%"));command.upgrade(config,"head")

def has_administrator()->bool:
    from app.database import SessionLocal
    from app.models import User,UserRole
    with SessionLocal() as db:return bool(db.query(User).filter(User.role==UserRole.administrator).count())

def setup_html(token:str,error:str="")->str:
    safe=error.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    error_html=f'<p class="error">{safe}</p>' if error else ""
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>EduScan Setup</title><style>body{{margin:0;background:#f5f8f6;color:#18342f;font:15px Segoe UI,sans-serif;display:grid;place-items:center;min-height:100vh}}main{{width:min(440px,calc(100% - 32px));background:white;border:1px solid #dfe9e5;border-radius:18px;padding:34px;box-shadow:0 20px 60px #123c3620}}h1{{margin:0;color:#176b5a}}p{{color:#71817d}}label{{display:grid;gap:5px;margin:15px 0;font-weight:600}}input{{padding:11px;border:1px solid #ccd9d5;border-radius:9px;font:inherit}}button{{width:100%;padding:12px;border:0;border-radius:9px;background:#176b5a;color:white;font-weight:700;font-size:15px}}.error{{color:#a22;background:#fee;padding:9px;border-radius:8px}}</style></head><body><main><h1>EduScan</h1><p>First-time setup · Create the IT administrator account.</p>{error_html}<form method='post' action='/desktop/setup'><input type='hidden' name='token' value='{token}'><label>Full name<input name='full_name' minlength='2' maxlength='160' required autofocus></label><label>Email address<input name='email' type='email' maxlength='254' required></label><label>Password<input name='password' type='password' minlength='10' required></label><label>Confirm password<input name='confirmation' type='password' minlength='10' required></label><button type='submit'>Create administrator and open EduScan</button></form></main></body></html>"""

def add_desktop_routes(app,bootstrap_token:str|None):
    from fastapi import Form
    from fastapi.responses import HTMLResponse,RedirectResponse
    from app.database import SessionLocal
    from app.models import User,UserRole
    from app.security import hash_password
    @app.get("/desktop/setup",response_class=HTMLResponse)
    def desktop_setup(token:str=""):
        if has_administrator():return RedirectResponse("/",status_code=303)
        if not bootstrap_token or not secrets.compare_digest(token,bootstrap_token):return HTMLResponse("Setup link is invalid or expired.",status_code=403)
        return HTMLResponse(setup_html(bootstrap_token))
    @app.post("/desktop/setup",response_class=HTMLResponse)
    def create_admin(token:str=Form(...),full_name:str=Form(...),email:str=Form(...),password:str=Form(...),confirmation:str=Form(...)):
        nonlocal bootstrap_token
        if has_administrator() or not bootstrap_token or not secrets.compare_digest(token,bootstrap_token):return HTMLResponse("Setup link is invalid or expired.",status_code=403)
        full_name=full_name.strip();email=email.strip().lower()
        if len(full_name)<2 or "@" not in email:return HTMLResponse(setup_html(bootstrap_token,"Enter a complete name and valid email address."),status_code=422)
        if len(password)<10:return HTMLResponse(setup_html(bootstrap_token,"Password must contain at least 10 characters."),status_code=422)
        if password!=confirmation:return HTMLResponse(setup_html(bootstrap_token,"Passwords do not match."),status_code=422)
        with SessionLocal() as db:db.add(User(full_name=full_name,email=email,role=UserRole.administrator,password_hash=hash_password(password)));db.commit()
        bootstrap_token=None;return RedirectResponse("/",status_code=303)

def already_running()->bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/api/v1/health",timeout=1) as response:return response.status==200
    except Exception:return False

def main()->None:
    try:
        if already_running():webbrowser.open(APP_URL);return
        bundled,storage=configure_environment();migrate_database(bundled)
        if "--backup" in sys.argv:
            from app.backup import main as create_backup
            create_backup();message("EduScan Backup",f"Backup saved under:\n{storage/'backups'}");return
        from fastapi.staticfiles import StaticFiles
        from app.main import app
        from PIL import Image
        import pystray,uvicorn
        # Some Windows installations register .js as text/plain. With the
        # application's nosniff security header, browsers correctly refuse to
        # execute that response and the interface remains hidden.
        mimetypes.add_type("application/javascript",".js",strict=True)
        mimetypes.add_type("application/manifest+json",".webmanifest",strict=True)
        token=None if has_administrator() else secrets.token_urlsafe(32);add_desktop_routes(app,token);app.mount("/",StaticFiles(directory=str(bundled/"web"),html=True),name="desktop-web")
        server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=APP_PORT,log_config=None,access_log=False));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        for _ in range(60):
            if already_running():break
            time.sleep(.1)
        if not already_running():raise RuntimeError("The local EduScan service could not start.")
        start_url=f"{APP_URL}/desktop/setup?token={token}" if token else APP_URL
        if "--no-browser" not in sys.argv:webbrowser.open(start_url)
        tray_image=Image.open(bundled/"web"/"icons"/"luna-school-logo.png").convert("RGBA")
        def open_app(icon=None,item=None):webbrowser.open(APP_URL)
        def backup(icon=None,item=None):
            try:
                from app.backup import main as create_backup
                create_backup();icon.notify("Backup completed successfully.","EduScan")
            except Exception as exc:icon.notify(f"Backup failed: {exc}","EduScan")
        def stop(icon,item=None):server.should_exit=True;icon.stop()
        icon=pystray.Icon("EduScan",tray_image,"EduScan Teacher",pystray.Menu(pystray.MenuItem("Open EduScan",open_app,default=True),pystray.MenuItem("Create backup",backup),pystray.MenuItem("Exit EduScan",stop)))
        icon.run();server.should_exit=True;thread.join(timeout=10)
    except Exception as exc:
        storage=data_root()
        try:(storage/"startup-error.log").write_text(traceback.format_exc(),encoding="utf-8")
        except Exception:pass
        message("EduScan could not start",f"{exc}\n\nDetails: {storage/'startup-error.log'}\nData remains safe under {storage}.",True)

if __name__=="__main__":main()
