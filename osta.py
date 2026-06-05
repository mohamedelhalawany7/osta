import os
import sys
import io
import json
from datetime import datetime, timedelta
from typing import Optional, AsyncGenerator
import re
import logging
from cryptography.fernet import Fernet
import httpx
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import hashlib
from pydantic import BaseModel, ConfigDict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import html
import asyncio
import secrets
import base64

import uvicorn
import pandas as pd
from fastapi import FastAPI, Request, Depends, UploadFile, File, Form, Response, status, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

# --- Firebase ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- AI & LangChain ---
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
import bcrypt
from jose import JWTError, jwt

from openai import OpenAI
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# =====================================================================
# طبقة الأمان المتقدمة
# =====================================================================
fallback_key = base64.urlsafe_b64encode(hashlib.sha256(b"Elderiny_Secret_Key_2026").digest())
FERNET_KEY = os.getenv("FERNET_KEY", fallback_key.decode())
cipher = Fernet(FERNET_KEY.encode())

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 

def encrypt_val(value: str) -> str:
    if not value: return ""
    return cipher.encrypt(value.encode()).decode()

def decrypt_val(value: str) -> str:
    if not value: return ""
    try: return cipher.decrypt(value.encode()).decode()
    except: return value

def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# =====================================================================
# تهيئة قاعدة بيانات Firebase
# =====================================================================
if not firebase_admin._apps:
    try:
        if os.path.exists("firebase-key.json"):
            cred = credentials.Certificate("firebase-key.json")
            firebase_admin.initialize_app(cred)
            logger.info("تم الربط مع Firebase بنجاح.")
        else:
            logger.warning("ملف firebase-key.json غير موجود. قد تفشل بعض العمليات السحابية.")
            firebase_admin.initialize_app()
    except Exception as e:
        logger.error(f"خطأ في تهيئة Firebase: {e}")

try:
    db_firestore = firestore.client()
except Exception:
    db_firestore = None

def get_db():
    yield db_firestore

# =====================================================================
# الموديلز الافتراضية
# =====================================================================
class TenantModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.name = data.get("name", "")
        self.llm_model = data.get("llm_model", "gpt-4o")
        self.openai_api_key = data.get("openai_api_key", "")
        self.pinecone_api_key = data.get("pinecone_api_key", "")
        self.pinecone_index = data.get("pinecone_index", "")
        self.customer_service_prompt = data.get("customer_service_prompt", "أنت 'الأسطى الآلي'، كبير المهندسين والصنايعية. تتحدث بلهجة مصرية عامية (صنايعي صميم). العمال بسطاء، قدم حلولاً هندسية مظبوطة وبلغة سهلة جداً.")

class UserModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.username = data.get("username", "")
        self.role = data.get("role", "admin")
        self.tenant_id = data.get("tenant_id", "")
        self.tenant = None

def init_db():
    if not db_firestore: return
    try:
        tenants = list(db_firestore.collection("tenants").limit(1).stream())
        if not tenants:
            tenant_ref = db_firestore.collection("tenants").document()
            tenant_ref.set({
                "name": "الدريني للآلات والمعدات",
                "llm_model": "gpt-4o",
                "customer_service_prompt": "أنت 'الأسطى الآلي'، كبير المهندسين والصنايعية. تتحدث بلهجة مصرية عامية (صنايعي صميم). العمال بسطاء، قدم حلولاً هندسية مظبوطة وبلغة سهلة جداً."
            })
            db_firestore.collection("users").add({
                "username": "admin",
                "hashed_password": get_password_hash("12345678"),
                "role": "admin",
                "tenant_id": tenant_ref.id
            })
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")

init_db()

def get_current_user_from_cookie(request: Request, db = Depends(get_db)):
    if not db: return None
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username: return None
        
        users = list(db.collection("users").where("username", "==", username).limit(1).stream())
        if not users: return None
        
        user_data = users[0].to_dict()
        user_model = UserModel(users[0].id, user_data)
        
        tenant_id = user_data.get("tenant_id")
        if tenant_id:
            tenant_doc = db.collection("tenants").document(tenant_id).get()
            if tenant_doc.exists:
                user_model.tenant = TenantModel(tenant_doc.id, tenant_doc.to_dict())
                
        return user_model
    except JWTError:
        return None

# =====================================================================
# واجهة الـ HTML / CSS (التصميم النيون)
# =====================================================================
def render_html_layout(content: str, title: str, user=None):
    nav_links = ""
    if user:
        nav_links += f'<li class="nav-item"><a class="nav-link" href="/chat"><i class="bi bi-robot"></i> الأسطى الآلي (الشات)</a></li>'
        if user.role == 'admin':
            nav_links += f"""
            <li class="nav-item"><a class="nav-link" href="/data_management"><i class="bi bi-database-add"></i> إدارة الكتالوجات</a></li>
            <li class="nav-item"><a class="nav-link" href="/settings"><i class="bi bi-gear"></i> الإعدادات والعمال</a></li>
            """
        nav_links += f'<li class="nav-item mt-5"><a class="btn-logout text-center fw-bold" href="/logout"><i class="bi bi-box-arrow-right me-2"></i> خروج ({user.username})</a></li>'
    else:
        nav_links = """
        <li class="nav-item"><a class="btn-logout text-center fw-bold mb-3" href="/login" style="background-color: var(--neon-primary); color: #000; box-shadow: 0 0 15px var(--neon-primary);"><i class="bi bi-box-arrow-in-right me-2"></i> تسجيل الدخول</a></li>
        <li class="nav-item"><a class="btn-logout text-center fw-bold" href="/register" style="background-color: transparent; color: var(--neon-success); border: 1px solid var(--neon-success); box-shadow: inset 0 0 10px rgba(57, 255, 20, 0.1);"><i class="bi bi-building-add me-2"></i> شركة جديدة</a></li>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0">
        <title>{title} | نظام الدريني</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg-main: #0A0E17;
                --bg-card: rgba(16, 22, 35, 0.7);
                --sidebar-bg: rgba(10, 14, 23, 0.95);
                --text-main: #E2E8F0;
                --text-dark: #FFFFFF;
                --neon-primary: #00F0FF;
                --neon-success: #39FF14;
                --neon-danger: #FF003C;
                --sidebar-width: 290px;
            }}
            body {{ 
                font-family: 'Cairo', sans-serif; 
                background-color: var(--bg-main); 
                color: var(--text-main);
                background-image: radial-gradient(circle at 15% 50%, rgba(176, 38, 255, 0.05), transparent 25%), radial-gradient(circle at 85% 30%, rgba(0, 240, 255, 0.05), transparent 25%);
            }}
            .sidebar {{ width: var(--sidebar-width); background-color: var(--sidebar-bg); position: fixed; right: 0; top: 0; height: 100vh; overflow-y: auto; padding-top: 2rem; border-left: 1px solid rgba(0, 240, 255, 0.1); z-index: 1000; transition: 0.3s; }}
            .sidebar .brand {{ font-size: 1.8rem; font-weight: 800; text-align: center; margin-bottom: 2rem; color: #FFF; text-shadow: 0 0 10px rgba(0, 240, 255, 0.5); }}
            .sidebar .nav-link {{ color: #8B9BB4; font-weight: 700; padding: 1rem 1.5rem; border-radius: 12px; margin: 0.5rem 1rem; transition: 0.3s; border: 1px solid transparent; }}
            .sidebar .nav-link:hover, .sidebar .nav-link.active {{ background-color: rgba(0, 240, 255, 0.1); color: #FFF; border-color: rgba(0, 240, 255, 0.4); box-shadow: 0 0 15px rgba(0, 240, 255, 0.2); transform: translateX(-5px); }}
            .btn-logout {{ background-color: rgba(255, 0, 60, 0.1); color: var(--neon-danger); border-radius: 12px; padding: 1rem; margin: 1rem; display: block; text-decoration: none; border: 1px solid rgba(255, 0, 60, 0.3); transition: 0.3s; }}
            .btn-logout:hover {{ background-color: var(--neon-danger); color: #FFF; box-shadow: 0 0 20px var(--neon-danger); }}
            .main-content {{ margin-right: var(--sidebar-width); padding: 2rem; min-height: 100vh; }}
            .card {{ background-color: var(--bg-card); border-radius: 20px; border: 1px solid rgba(255,255,255,0.05); box-shadow: 0 10px 30px rgba(0,0,0,0.4); margin-bottom: 20px; backdrop-filter: blur(10px); }}
            .form-control, .form-select {{ background-color: rgba(0,0,0,0.5) !important; border: 1px solid rgba(255,255,255,0.1) !important; color: #FFF !important; border-radius: 12px; padding: 0.8rem; }}
            .form-control:focus {{ border-color: var(--neon-primary) !important; box-shadow: 0 0 10px rgba(0, 240, 255, 0.3) !important; }}
            .btn-primary {{ background-color: transparent; border: 1px solid var(--neon-primary); color: var(--neon-primary); font-weight: bold; border-radius: 12px; transition: 0.3s; box-shadow: inset 0 0 10px rgba(0,240,255,0.1); }}
            .btn-primary:hover {{ background-color: var(--neon-primary); color: #000; box-shadow: 0 0 20px var(--neon-primary); }}
            @media (max-width: 992px) {{
                .sidebar {{ transform: translateX(100%); }}
                .sidebar.show {{ transform: translateX(0); }}
                .main-content {{ margin-right: 0; padding: 1rem; }}
                .mobile-header {{ display: flex; justify-content: space-between; padding: 1rem; background: var(--sidebar-bg); border-bottom: 1px solid rgba(0,240,255,0.2); }}
            }}
        </style>
    </head>
    <body>
        <div class="mobile-header d-lg-none">
            <h5 class="mb-0 text-white"><i class="bi bi-cpu text-primary me-2"></i>نظام الدريني</h5>
            <button class="btn btn-sm btn-outline-primary border-0 fs-4" onclick="document.querySelector('.sidebar').classList.toggle('show')"><i class="bi bi-list"></i></button>
        </div>
        <aside class="sidebar">
            <div class="brand"><i class="bi bi-cpu me-2 text-primary"></i>نظام الدريني</div>
            <ul class="nav flex-column">{nav_links}</ul>
        </aside>
        <main class="main-content">{content}</main>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    </body>
    </html>
    """

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/")
async def home(request: Request, db = Depends(get_db)):
    if get_current_user_from_cookie(request, db): return RedirectResponse(url="/chat")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    content = """
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-md-5">
            <div class="card p-4" style="border-top: 4px solid var(--neon-primary);">
                <div class="text-center mb-4"><i class="bi bi-shield-lock fs-1 text-primary"></i><h3 class="fw-bold mt-2">تسجيل الدخول للورشة</h3></div>
                <form action="/login" method="post">
                    <div class="mb-3"><input type="text" class="form-control" name="username" required placeholder="اسم المستخدم أو رقم الموبايل"></div>
                    <div class="mb-4"><input type="password" class="form-control" name="password" required placeholder="الرقم السري"></div>
                    <button type="submit" class="btn btn-primary w-100 py-2 fs-5">دخول <i class="bi bi-arrow-left"></i></button>
                </form>
                <div class="text-center mt-3"><a href="/register" class="text-success text-decoration-none">تسجيل ورشة جديدة</a></div>
            </div>
        </div>
    </div>
    """
    return render_html_layout(content, "تسجيل الدخول")

@app.post("/login")
async def login_post(response: Response, username: str = Form(...), password: str = Form(...), db = Depends(get_db)):
    if not db: return HTMLResponse(render_html_layout("<div class='alert alert-danger'>خطأ بقاعدة البيانات.</div>", "خطأ"))
    users = list(db.collection("users").where("username", "==", username).limit(1).stream())
    if users and verify_password(password, users[0].to_dict().get("hashed_password")):
        token = create_access_token(data={"sub": username})
        resp = RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)
        resp.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True)
        return resp
    return HTMLResponse(render_html_layout("<div class='alert alert-danger'>بيانات غير صحيحة.</div>", "خطأ"))

@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login")
    resp.delete_cookie("access_token")
    return resp

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    content = """
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-md-5">
            <div class="card p-4" style="border-top: 4px solid var(--neon-success);">
                <div class="text-center mb-4"><i class="bi bi-building fs-1 text-success"></i><h3 class="fw-bold mt-2">تسجيل ورشة جديدة</h3></div>
                <form action="/register" method="post">
                    <div class="mb-3"><input type="text" class="form-control" name="company_name" required placeholder="اسم الورشة"></div>
                    <div class="mb-3"><input type="text" class="form-control" name="admin_username" required placeholder="اسم مدير النظام"></div>
                    <div class="mb-4"><input type="password" class="form-control" name="admin_password" required placeholder="الرقم السري"></div>
                    <button type="submit" class="btn btn-success w-100 py-2 fs-5 text-dark fw-bold" style="background:var(--neon-success);">إنشاء الورشة</button>
                </form>
            </div>
        </div>
    </div>
    """
    return render_html_layout(content, "تسجيل ورشة")

@app.post("/register")
async def register_post(company_name: str = Form(...), admin_username: str = Form(...), admin_password: str = Form(...), db = Depends(get_db)):
    if list(db.collection("tenants").where("name", "==", company_name).limit(1).stream()):
        return HTMLResponse(render_html_layout("<div class='alert alert-danger'>الشركة موجودة مسبقاً.</div>", "خطأ"))
    t_ref = db.collection("tenants").document()
    t_ref.set({"name": company_name, "cs_prompt": "أنت الأسطى الآلي..."})
    db.collection("users").add({"username": admin_username, "hashed_password": get_password_hash(admin_password), "role": "admin", "tenant_id": t_ref.id})
    return HTMLResponse(render_html_layout("<div class='alert alert-success'>تم التسجيل بنجاح! <a href='/login'>سجل دخولك الآن</a></div>", "نجاح"))

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse(url="/login")
    
    content = """
    <style>
        .main-content { padding: 0 !important; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        .chat-container { flex: 1; display: flex; flex-direction: column; position: relative; background: #0A0E17;}
        .chat-header { height: 70px; background: rgba(16,22,35,0.9); border-bottom: 1px solid rgba(0,240,255,0.2); display: flex; align-items: center; padding: 0 20px; z-index: 10; }
        .chat-messages { flex: 1; overflow-y: auto; padding: 20px; padding-bottom: 90px; }
        .bubble { max-width: 80%; padding: 12px 18px; border-radius: 15px; margin-bottom: 15px; line-height: 1.6; font-size: 16px;}
        .bubble.ai { background: rgba(16,22,35,0.9); border: 1px solid rgba(0,240,255,0.3); color: #fff; align-self: flex-start; border-top-right-radius: 0; }
        .bubble.user { background: var(--neon-primary); color: #000; margin-left: auto; border-top-left-radius: 0; font-weight: bold;}
        .chat-footer { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(10,14,23,0.95); padding: 15px; border-top: 1px solid rgba(0,240,255,0.2); display: flex; gap: 10px; z-index: 10;}
        .chat-input { flex: 1; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 25px; padding: 0 20px; color: #fff; outline: none; }
        .chat-input:focus { border-color: var(--neon-primary); }
        .btn-circle { width: 50px; height: 50px; border-radius: 50%; border: none; display: flex; justify-content: center; align-items: center; font-size: 1.2rem; cursor: pointer; transition: 0.2s;}
        .btn-mic { background: transparent; border: 1px solid var(--neon-primary); color: var(--neon-primary); }
        .btn-mic.recording { background: var(--neon-danger); border-color: var(--neon-danger); color: #fff; animation: pulse 1s infinite; }
        .btn-send { background: var(--neon-primary); color: #000; }
        @keyframes pulse { 0% {box-shadow: 0 0 0 0 rgba(255,0,60,0.7);} 70% {box-shadow: 0 0 0 15px rgba(255,0,60,0);} 100% {box-shadow: 0 0 0 0 rgba(255,0,60,0);} }
    </style>
    
    <div class="chat-container">
        <div class="chat-header">
            <h4 class="mb-0 text-white"><i class="bi bi-tools text-primary me-2"></i>الأسطى الآلي للورشة</h4>
        </div>
        <div class="chat-messages" id="chatBox">
            <div class="bubble ai">يا هلا بيك يا بطل، المكنة فيها إيه؟ دوس على المايك وسجل مشكلتك.</div>
        </div>
        <div class="chat-footer">
            <button class="btn-circle btn-mic" id="micBtn" title="اضغط باستمرار للتسجيل"><i class="bi bi-mic-fill"></i></button>
            <input type="text" class="chat-input" id="chatInput" placeholder="اكتب عطل المكنة هنا..." onkeypress="if(event.key==='Enter') sendMessage()">
            <button class="btn-circle btn-send" onclick="sendMessage()"><i class="bi bi-send-fill"></i></button>
        </div>
    </div>

    <script>
        const chatBox = document.getElementById('chatBox');
        const input = document.getElementById('chatInput');
        const micBtn = document.getElementById('micBtn');
        let recognition;

        function appendMsg(text, sender) {
            const div = document.createElement('div');
            div.className = `bubble ${sender}`;
            div.innerHTML = text.replace(/\\n/g, '<br>');
            chatBox.appendChild(div);
            chatBox.scrollTop = chatBox.scrollHeight;
            return div;
        }

        function speak(text) {
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                let clean = text.replace(/[*#_]/g, '');
                let ut = new SpeechSynthesisUtterance(clean);
                ut.lang = 'ar-EG'; ut.pitch = 0.8;
                window.speechSynthesis.speak(ut);
            }
        }

        async function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            appendMsg(text, 'user');
            input.value = '';
            
            const typing = appendMsg('<i class="spinner-border spinner-border-sm text-primary"></i> الأسطى بيفكر...', 'ai');
            
            try {
                const res = await fetch('/api/simulate_chat', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: text})
                });
                
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let fullText = '';
                typing.innerHTML = '';
                
                while(true) {
                    const {done, value} = await reader.read();
                    if(done) break;
                    const lines = decoder.decode(value).split('\\n');
                    for(let line of lines) {
                        if(line.startsWith('data: ')) {
                            const data = JSON.parse(line.replace('data: ', ''));
                            if(data.chunk) {
                                fullText += data.chunk;
                                typing.innerHTML = fullText.replace(/\\n/g, '<br>');
                                chatBox.scrollTop = chatBox.scrollHeight;
                            }
                        }
                    }
                }
                speak(fullText);
            } catch(e) {
                typing.innerHTML = "حدث خطأ في الاتصال بالأسطى.";
            }
        }

        // إعداد التسجيل الصوتي
        if(window.SpeechRecognition || window.webkitSpeechRecognition) {
            recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'ar-EG';
            recognition.continuous = true;
            recognition.interimResults = true;
            
            recognition.onstart = () => { micBtn.classList.add('recording'); input.placeholder = 'جاري الاستماع...'; input.value=''; };
            recognition.onresult = (e) => {
                let final = ''; let interim = '';
                for(let i = e.resultIndex; i < e.results.length; i++) {
                    if(e.results[i].isFinal) final += e.results[i][0].transcript;
                    else interim += e.results[i][0].transcript;
                }
                input.value = final + interim;
            };
            recognition.onend = () => { 
                micBtn.classList.remove('recording'); input.placeholder = 'اكتب عطل المكنة...'; 
                if(input.value) sendMessage();
            };
            
            micBtn.onmousedown = () => recognition.start();
            micBtn.onmouseup = () => recognition.stop();
            micBtn.ontouchstart = (e) => { e.preventDefault(); recognition.start(); };
            micBtn.ontouchend = (e) => { e.preventDefault(); recognition.stop(); };
        } else {
            micBtn.onclick = () => alert("المتصفح لا يدعم التسجيل الصوتي المباشر.");
        }
    </script>
    """
    return render_html_layout(content, "الأسطى الآلي", user)

class ChatRequest(BaseModel): message: str

@app.post("/api/simulate_chat")
async def simulate_chat_api(req: ChatRequest, request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return StreamingResponse((f"data: {json.dumps({'error': 'Unauthorized'})}\n\n" for _ in range(1)), media_type="text/event-stream")
    
    tenant = user.tenant
    key = decrypt_val(tenant.openai_api_key)
    
    if not key:
        return StreamingResponse((f"data: {json.dumps({'chunk': 'الأسطى مش واصله كهربا (لا يوجد API Key في الإعدادات)'})}\n\n" for _ in range(1)), media_type="text/event-stream")
        
    try:
        llm = ChatOpenAI(model_name=tenant.llm_model, openai_api_key=key, temperature=0.3)
        sys_msg = SystemMessage(content=tenant.customer_service_prompt)
        
        # دمج الـ RAG لو متاح
        pc_key = decrypt_val(tenant.pinecone_api_key)
        if pc_key and tenant.pinecone_index:
            embeds = OpenAIEmbeddings(openai_api_key=key)
            pc = PineconeClient(api_key=pc_key)
            idx = pc.Index(tenant.pinecone_index)
            vs = PineconeVectorStore(index=idx, embedding=embeds, namespace=f"tenant_{tenant.id}")
            docs = vs.similarity_search(req.message, k=2)
            if docs:
                ctx = "\n".join([d.page_content for d in docs])
                sys_msg.content += f"\n\nمعلومات من الكتالوج:\n{ctx}"
                
        async def event_gen():
            async for chunk in llm.astream([sys_msg, HumanMessage(content=req.message)]):
                if chunk.content:
                    yield f"data: {json.dumps({'chunk': chunk.content})}\n\n"
                    
        return StreamingResponse(event_gen(), media_type="text/event-stream")
    except Exception as e:
        return StreamingResponse((f"data: {json.dumps({'chunk': f'خطأ: {str(e)}'})}\n\n" for _ in range(1)), media_type="text/event-stream")

@app.get("/settings", response_class=HTMLResponse)
async def settings_view(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role != 'admin': return RedirectResponse(url="/chat")
    
    t = user.tenant
    users_list = list(db.collection("users").where("tenant_id", "==", t.id).stream())
    users_html = "".join([f"<tr><td>{u.to_dict().get('username')}</td><td>{u.to_dict().get('role')}</td><td><button class='btn btn-sm btn-outline-danger' onclick='delUser(\"{u.id}\")'>حذف</button></td></tr>" for u in users_list])
    
    content = f"""
    <div class="row">
        <div class="col-md-6 mb-4">
            <div class="card p-4">
                <h5 class="text-primary mb-3">مفاتيح الذكاء الاصطناعي و Pinecone</h5>
                <form action="/api/settings/save" method="post">
                    <label class="text-white small">OpenAI API Key</label>
                    <input type="password" name="openai_key" class="form-control mb-3" value="{decrypt_val(t.openai_api_key)}">
                    
                    <label class="text-white small">Pinecone API Key</label>
                    <input type="password" name="pinecone_key" class="form-control mb-3" value="{decrypt_val(t.pinecone_api_key)}">
                    
                    <label class="text-white small">Pinecone Index Name</label>
                    <input type="text" name="pinecone_index" class="form-control mb-4" value="{t.pinecone_index}">
                    
                    <button type="submit" class="btn btn-primary w-100">حفظ المفاتيح</button>
                </form>
            </div>
        </div>
        
        <div class="col-md-6 mb-4">
            <div class="card p-4">
                <h5 class="text-warning mb-3">إضافة عامل جديد للورشة</h5>
                <form action="/api/users/add" method="post">
                    <label class="text-white small">رقم العامل (سيكون اليوزر والباسورد)</label>
                    <input type="text" name="worker_phone" class="form-control mb-3" required>
                    <button type="submit" class="btn btn-warning text-dark fw-bold w-100">إضافة العامل</button>
                </form>
                <hr class="border-secondary my-4">
                <table class="table text-white">
                    <thead><tr><th>المستخدم</th><th>الصلاحية</th><th>حذف</th></tr></thead>
                    <tbody>{users_html}</tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
        async function delUser(id) {{
            if(confirm("حذف المستخدم؟")) {{
                await fetch('/api/users/del/'+id, {{method:'DELETE'}});
                location.reload();
            }}
        }}
    </script>
    """
    return render_html_layout(content, "الإعدادات", user)

@app.post("/api/settings/save")
async def save_settings(request: Request, openai_key: str = Form(""), pinecone_key: str = Form(""), pinecone_index: str = Form(""), db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if user and user.role == 'admin':
        db.collection("tenants").document(user.tenant.id).update({
            "openai_api_key": encrypt_val(openai_key),
            "pinecone_api_key": encrypt_val(pinecone_key),
            "pinecone_index": pinecone_index
        })
    return RedirectResponse(url="/settings", status_code=303)

@app.post("/api/users/add")
async def add_worker(request: Request, worker_phone: str = Form(...), db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if user and user.role == 'admin':
        db.collection("users").add({
            "username": worker_phone,
            "hashed_password": get_password_hash(worker_phone),
            "role": "worker",
            "tenant_id": user.tenant.id
        })
    return RedirectResponse(url="/settings", status_code=303)

@app.delete("/api/users/del/{uid}")
async def del_worker(uid: str, request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if user and user.role == 'admin':
        db.collection("users").document(uid).delete()
    return {"status": "ok"}

@app.get("/data_management", response_class=HTMLResponse)
async def data_management_page(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role != 'admin': return RedirectResponse(url="/chat")
    
    files_list = list(db.collection("uploaded_files").where("tenant_id", "==", user.tenant.id).stream())
    files_html = "".join([f"<tr><td>{f.to_dict().get('filename')}</td><td><button class='btn btn-sm btn-outline-danger' onclick='delFile(\"{f.id}\")'>حذف</button></td></tr>" for f in files_list])
    
    content = f"""
    <div class="row">
        <div class="col-md-6">
            <div class="card p-4">
                <h5 class="text-danger mb-3">رفع كتالوج للأسطى (RAG)</h5>
                <form action="/api/upload_rag" method="post" enctype="multipart/form-data">
                    <input type="file" name="file" class="form-control mb-3" required accept=".pdf,.txt">
                    <button type="submit" class="btn btn-danger w-100">رفع وتدريب</button>
                </form>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card p-4">
                <h5 class="text-info mb-3">الملفات المرفوعة</h5>
                <table class="table text-white">
                    <thead><tr><th>اسم الملف</th><th>حذف</th></tr></thead>
                    <tbody>{files_html if files_html else '<tr><td colspan="2">لا يوجد ملفات.</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
        async function delFile(id) {{
            if(confirm("حذف السجل؟")) {{
                await fetch('/api/files/del/'+id, {{method:'DELETE'}});
                location.reload();
            }}
        }}
    </script>
    """
    return render_html_layout(content, "البيانات والملفات", user)

def process_rag_bg(content: bytes, filename: str, tenant_id: str):
    try:
        t_doc = db_firestore.collection("tenants").document(tenant_id).get()
        t = t_doc.to_dict()
        db_firestore.collection("uploaded_files").add({"filename": filename, "tenant_id": tenant_id})
        
        okey = decrypt_val(t.get("openai_api_key"))
        pkey = decrypt_val(t.get("pinecone_api_key"))
        idx_name = t.get("pinecone_index")
        
        if not okey or not pkey or not idx_name: return
        
        text = ""
        if filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(content))
            for p in reader.pages:
                if p.extract_text(): text += p.extract_text() + "\n"
        else:
            text = content.decode('utf-8')
            
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_text(text)
        
        embeds = OpenAIEmbeddings(openai_api_key=okey)
        pc = PineconeClient(api_key=pkey)
        idx = pc.Index(idx_name)
        vs = PineconeVectorStore(index=idx, embedding=embeds, namespace=f"tenant_{tenant_id}")
        vs.add_texts(chunks)
    except Exception as e:
        logger.error(f"RAG Error: {e}")

@app.post("/api/upload_rag")
async def upload_rag(bg: BackgroundTasks, request: Request, file: UploadFile = File(...), db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if user and user.role == 'admin':
        content = await file.read()
        bg.add_task(process_rag_bg, content, file.filename, user.tenant.id)
    return HTMLResponse(render_html_layout("<div class='alert alert-success'>جاري تدريب الأسطى في الخلفية... <a href='/data_management'>عودة</a></div>", "جاري الرفع", user))

@app.delete("/api/files/del/{fid}")
async def del_file(fid: str, request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if user and user.role == 'admin':
        db.collection("uploaded_files").document(fid).delete()
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    # تعليمات التشغيل الصحيح
    print("=====================================================")
    print("هذا النظام تم إعادة بنائه بالكامل كـ FastAPI (للحفاظ على التصميم والسرعة).")
    print("لتشغيله مجاناً: ارفعه على منصة Render.com أو Railway.app كـ Web Service.")
    print("الرجاء عدم محاولة رفعه على Streamlit Cloud لأنه لا يدعم هذه المعمارية المخصصة.")
    print("=====================================================")
    uvicorn.run(app, host="0.0.0.0", port=port)
