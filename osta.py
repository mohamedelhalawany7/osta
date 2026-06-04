import os
import sys
import io
import json
import base64
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, AsyncGenerator, List
from collections import defaultdict
import logging
from cryptography.fernet import Fernet
import hashlib
from pydantic import BaseModel, ConfigDict, Field
from threading import Lock
import tempfile
import openai

import html
import asyncio
import secrets
from cachetools import TTLCache
import socket
import threading
import streamlit as st
import requests

import mimetypes
# حذفنا filetype عشان ما تعملش مشاكل

import uvicorn
from fastapi import FastAPI, Request, Depends, UploadFile, File, Form, HTTPException, status, BackgroundTasks, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# --- Environment & Rate Limiting ---
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# --- Resiliency & Cron ---
from tenacity import retry, stop_after_attempt, wait_exponential
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- LangGraph & Memory ---
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# --- Database (Async) ---
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, select, text, func
from sqlalchemy.orm import declarative_base, relationship
import bcrypt
from jose import JWTError, jwt

# --- Langchain ---
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from contextlib import asynccontextmanager

# --- Middleware ---
from starlette.middleware.base import BaseHTTPMiddleware

# --- Cloud & NoSQL Databases ---
import firebase_admin
from firebase_admin import credentials, firestore

# =====================================================================
# الإعدادات الأولية والأمان
# =====================================================================
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

class Vault:
    @staticmethod
    def get_secret(key_name: str, default_value: str = "") -> str:
        return os.getenv(key_name, default_value)

FERNET_KEY = Vault.get_secret("FERNET_KEY")
if not FERNET_KEY:
    FERNET_KEY = Fernet.generate_key().decode()
    with open(".env", "a", encoding="utf-8") as f: f.write(f"\nFERNET_KEY={FERNET_KEY}\n")
cipher = Fernet(FERNET_KEY.encode())

def encrypt_val(value: str) -> str: return cipher.encrypt(value.encode()).decode() if value else ""
def decrypt_val(value: str) -> str:
    if not value: return ""
    try: return cipher.decrypt(value.encode()).decode()
    except: return value

# 1. إجبار SECRET_KEY على أن يكون ثابتاً عبر .env
SECRET_KEY = Vault.get_secret("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    with open(".env", "a", encoding="utf-8") as f: f.write(f"\nSECRET_KEY={SECRET_KEY}\n")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 14400 
IS_PRODUCTION = Vault.get_secret("ENV", "development") == "production"

def verify_password(plain_password, hashed_password): return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
def get_password_hash(password): return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# =====================================================================
# قاعدة البيانات والكاش
# =====================================================================
if IS_PRODUCTION:
    raw_db_url = Vault.get_secret("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/workshop_db")
    # دعم وتوافق شامل لجميع قواعد البيانات السحابية (PostgreSQL, MySQL, SQLite)
    if raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+asyncpg://"):
        raw_db_url = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif raw_db_url.startswith("mysql://"):
        raw_db_url = raw_db_url.replace("mysql://", "mysql+aiomysql://", 1)
    SQLALCHEMY_DATABASE_URL = raw_db_url
else:
    SQLALCHEMY_DATABASE_URL = Vault.get_secret("DATABASE_URL", "sqlite+aiosqlite:///./workshop_db.sqlite")

# استخدام كاش Streamlit لمنع استنزاف الاتصالات بقاعدة البيانات مع كل تحديث للواجهة
@st.cache_resource
def get_db_setup(_db_url):
    engine_kwargs = {"echo": False}
    if not _db_url.startswith("sqlite"):
        engine_kwargs.update({
            "pool_size": int(Vault.get_secret("DB_POOL_SIZE", 5)),       
            "max_overflow": int(Vault.get_secret("DB_MAX_OVERFLOW", 10)),
            "pool_recycle": 1800,                                        
            "pool_pre_ping": True                                        
        })
    _engine = create_async_engine(_db_url, **engine_kwargs)
    _SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine, _SessionLocal

engine, AsyncSessionLocal = get_db_setup(SQLALCHEMY_DATABASE_URL)
Base = declarative_base()

# --- تهيئة Firebase السحابية كخيار موازي وجاهز للاستخدام ---
firebase_cred_json = Vault.get_secret("FIREBASE_CREDENTIALS")
firebase_db = None
if firebase_cred_json:
    try:
        cred_dict = json.loads(firebase_cred_json)
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        firebase_db = firestore.client()
        logger.info("تم تهيئة Firebase Firestore بنجاح وهو جاهز للاستخدام.")
    except Exception as e:
        logger.error(f"خطأ في تهيئة Firebase: {e}")

# =====================================================================
# تحسينات Firebase: الكاش، الدفعات، والتنظيف التلقائي، والمراقبة
# =====================================================================

# 4. مراقبة الاستخدام اليومي (إنذار مبكر)
daily_usage = {"reads": 0, "writes": 0, "date": datetime.utcnow().date()}
usage_lock = Lock()
DAILY_READ_LIMIT = 40000   # 80% من الـ 50k كحد أمان
DAILY_WRITE_LIMIT = 16000  # 80% من الـ 20k كحد أمان

def track_firestore_usage(operation: str, count: int = 1):
    with usage_lock:
        today = datetime.utcnow().date()
        if daily_usage["date"] != today:
            daily_usage.update({"reads": 0, "writes": 0, "date": today})
        
        daily_usage[operation] += count
        
        # إنذار مبكر لو اقتربنا من الحد
        if operation == "reads" and daily_usage["reads"] > DAILY_READ_LIMIT:
            logger.warning(f"⚠️ تحذير: وصلنا {daily_usage['reads']} قراءة اليوم!")
        if operation == "writes" and daily_usage["writes"] > DAILY_WRITE_LIMIT:
            logger.warning(f"⚠️ تحذير: وصلنا {daily_usage['writes']} كتابة اليوم!")

# 1. كاش الذاكرة للقراءة (يقلل القراءة 80%)
firestore_cache = TTLCache(maxsize=500, ttl=600)
firestore_cache_lock = Lock()

async def get_from_firestore_cached(collection: str, doc_id: str):
    cache_key = f"{collection}:{doc_id}"
    with firestore_cache_lock:
        if cache_key in firestore_cache:
            return firestore_cache[cache_key]
    
    if firebase_db:
        track_firestore_usage("reads", 1)  # تسجيل عملية قراءة
        # استخدام run_in_executor عشان القراءة من Firebase ماتعملش Block للـ Async
        loop = asyncio.get_running_loop()
        doc = await loop.run_in_executor(None, lambda: firebase_db.collection(collection).document(doc_id).get())
        data = doc.to_dict() if doc.exists else None
        with firestore_cache_lock:
            firestore_cache[cache_key] = data
        return data
    return None

# 2. تجميع الكتابة (Batch Writing) (يقلل الكتابة 70%)
write_buffer = defaultdict(list)
write_buffer_lock = Lock()

async def buffer_firestore_write(collection: str, data: dict):
    """بيحط الكتابة في buffer ومش بيكتب على طول"""
    with write_buffer_lock:
        write_buffer[collection].append(data)

async def flush_write_buffer():
    """بيكتب كل اللي في الـ buffer دفعة واحدة كل دقيقتين"""
    if not firebase_db:
        return
    
    with write_buffer_lock:
        if not write_buffer:
            return
        # أخذ نسخة من البيانات وتفريغ البافر فوراً للسماح باستقبال بيانات جديدة
        current_buffer = dict(write_buffer)
        write_buffer.clear()
        
    try:
        batch = firebase_db.batch()
        total_ops = 0
        
        for collection, items in current_buffer.items():
            for item in items:
                if total_ops >= 400:  # حد أمان قبل الـ 500 limit
                    await asyncio.to_thread(batch.commit)
                    track_firestore_usage("writes", total_ops) # تسجيل عمليات الكتابة
                    batch = firebase_db.batch()
                    total_ops = 0
                
                ref = firebase_db.collection(collection).document()
                batch.set(ref, item)
                total_ops += 1
                
        if total_ops > 0:
            await asyncio.to_thread(batch.commit)
            track_firestore_usage("writes", total_ops) # تسجيل عمليات الكتابة
            logger.info(f"Flushed {total_ops} writes to Firestore")
    except Exception as e:
        logger.error(f"Error flushing Firestore buffer: {e}")

# 3. حذف البيانات القديمة تلقائياً (يمنع امتلاء الـ 1GB)
async def cleanup_old_firestore_data():
    """بيحذف المحادثات الأقدم من 30 يوم تلقائياً"""
    if not firebase_db:
        return
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        # جلب وحذف بـ batches عشان نوفر في عمليات الحذف
        old_docs = await asyncio.to_thread(
            lambda: list(firebase_db.collection("conversation_history").where("created_at", "<", cutoff_date).limit(400).stream())
        )
        
        batch = firebase_db.batch()
        count = 0
        for doc in old_docs:
            batch.delete(doc.reference)
            count += 1
        
        if count > 0:
            await asyncio.to_thread(batch.commit)
            track_firestore_usage("writes", count) # عمليات الحذف تُحسب كـ Writes في Firebase
            logger.info(f"Cleaned up {count} old Firestore documents")
    except Exception as e:
        logger.error(f"Firestore cleanup error: {e}")

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_uuid = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, default="محادثة جديدة")
    user_id = Column(Integer, ForeignKey("users.id"))
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ConversationHistory(Base):
    __tablename__ = "conversation_history"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))

class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="documents")

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    llm_provider = Column(String, default="google")
    llm_model = Column(String, default="gemini-1.5-flash")
    api_base_url = Column(String, default="")
    openai_api_key = Column(String, default="")
    anthropic_api_key = Column(String, default="")
    google_api_key = Column(String, default="")
    pinecone_api_key = Column(String, default="")
    pinecone_index = Column(String, default="")
    firebase_credentials = Column(Text, default="")
    workshop_prompt = Column(Text, default="""أنت 'الأسطى بلية'، أقدم وأشطر صنايعي ومهندس في ورشة ميكانيكا وصيانة ضواغط هواء ومجففات في مصر.
العمال اللي بيكلموك صنايعية على قدهم ومابيعرفوش يقرأوا ويكتبوا، عشان كده:
1. اتكلم معاهم بلهجة مصرية بلدي صميمة، زي الصنايعية الكبار في الورش (يا بطل، يا هندسة، يا ريس، بص يا سيدي، صلي على النبي، هاتها في شوال).
2. اشرح المشكلة وحلها ببساطة جداً وبدون أي مصطلحات إنجليزي مكلكعة، ولو اضطريت تستخدم اسم قطعة انجليزي بسطه وقول بيعمل إيه.
3. خليك جدع ومشجع وبتحل المشاكل من الأخر بخطوات عملية 1، 2، 3.
4. لو بعتولك صورة، ركز فيها كويس وقولهم فيها إيه بالظبط وايه اللي بايظ وكيفية صيانته حتة حتة.
5. اعتمد في إجاباتك على معلومات الكتالوجات المرفقة، وضيف عليها خبرتك كـ "أسطى كبير" في السوق لتكون الإجابة كاملة.""")
    users = relationship("User", back_populates="tenant")
    documents = relationship("UploadedDocument", back_populates="tenant", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="admin") 
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="users")

# نظام الكاش الآمن في الـ Multi-worker البيئة
tenant_cache = TTLCache(maxsize=200, ttl=300)
tenant_cache_lock = Lock()

async def get_tenant_cached(tenant_id: int, db: AsyncSession):
    with tenant_cache_lock:
        if tenant_id in tenant_cache:
            return tenant_cache[tenant_id]
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if tenant:
        with tenant_cache_lock:
            tenant_cache[tenant_id] = tenant
    return tenant

async def get_db():
    async with AsyncSessionLocal() as session:
        try: yield session
        finally: await session.close()

async def get_chat_history(session_id: str, db: AsyncSession, limit: int = 5) -> str:
    result = await db.execute(
        select(ConversationHistory)
        .where(ConversationHistory.session_id == session_id)
        .order_by(ConversationHistory.created_at.desc())
        .limit(limit)
    )
    history = result.scalars().all()
    if not history: return ""
    return "\n".join([f"{h.role}: {h.content}" for h in reversed(history)])

async def save_chat_history(session_id: str, role: str, content: str, db: AsyncSession, tenant_id: int):
    clean_content = content[:1000] if "data:image" not in content else "[صورة مرفقة]"
    db.add(ConversationHistory(session_id=session_id, role=role, content=clean_content, tenant_id=tenant_id))
    await db.commit()

# =====================================================================
# دالة تم إضافتها لتعمل جميع نقاط الاستعلام بشكل سليم
# =====================================================================
async def get_user_from_header_or_cookie(request: Request, db: AsyncSession):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("access_token", "")
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(select(User).where(User.username == payload.get("sub")))).scalars().first()
        if user:
            user.tenant = await get_tenant_cached(user.tenant_id, db)
        return user
    except:
        return None

# =====================================================================
# Singleton Instances & Cron Jobs
# =====================================================================
pc_client_instance = None
scheduler = AsyncIOScheduler()

async def analyze_machine_issues_cron():
    logger.info("Starting Daily Cron Job: Analyzing machine issues...")
    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for tenant in tenants:
            if not tenant.openai_api_key: continue
            openai_key = decrypt_val(tenant.openai_api_key)
            
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            history_result = await db.execute(
                select(ConversationHistory)
                .where(ConversationHistory.tenant_id == tenant.id)
                .where(ConversationHistory.created_at >= thirty_days_ago)
                .order_by(ConversationHistory.created_at.desc())
                .limit(500) # تحسين الأداء: تقييد العدد لتجنب انهيار الميموري
            )
            history = history_result.scalars().all()
            if len(history) < 10: continue
            
            text_log = "\n".join([f"{h.role}: {h.content}" for h in history])
            prompt = """بصفتك مهندس صيانة ذكي، قم بتحليل سجلات محادثات العمال التالية خلال الشهر الماضي. 
هل تلاحظ وجود عطل في ماكينة معينة أو ضاغط هواء معين تكرر السؤال عنه أكثر من مرتين؟
إذا وجدت تكراراً يعطي مؤشراً على مشكلة مزمنة، اكتب تنبيهاً واحداً مباشراً وموجزاً يوضح الماكينة والمشكلة لمدير الورشة.
إذا كانت الأمور طبيعية ولا يوجد تكرار ملحوظ لأعطال خطيرة، اكتب فقط 'لا يوجد' ولا تضف أي كلمة أخرى."""
            
            try:
                llm = ChatOpenAI(model_name="gpt-4o-mini", openai_api_key=openai_key, temperature=0.0)
                res = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=text_log)])
                if "لا يوجد" not in res.content:
                    db.add(Alert(tenant_id=tenant.id, message=f"⚠️ تنبيه ذكي: {res.content}"))
                    await db.commit()
            except Exception as e:
                logger.error(f"Cron LLM error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pc_client_instance
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE tenants ADD COLUMN api_base_url VARCHAR DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE tenants ADD COLUMN firebase_credentials TEXT DEFAULT ''"))
        except Exception:
            pass

    async with AsyncSessionLocal() as db:
        tenant = (await db.execute(select(Tenant))).scalars().first()
        if not tenant:
            default_tenant = Tenant(name="ورشة الصيانة والتصنيع")
            db.add(default_tenant)
            await db.commit()
            await db.refresh(default_tenant)
            db.add(User(username="admin", hashed_password=get_password_hash("admin123"), role="admin", tenant_id=default_tenant.id))
            db.add(User(username="worker", hashed_password=get_password_hash("1234"), role="worker", tenant_id=default_tenant.id))
            await db.commit()
            tenant = default_tenant

        if tenant and tenant.pinecone_api_key:
            pk = decrypt_val(tenant.pinecone_api_key)
            if pk:
                pc_client_instance = PineconeClient(api_key=pk)
                logger.info("Pinecone Client Initialized (Singleton).")

    # ✅ الحل: شيل الجوبز الموجودة قبل الإضافة، وابدأ بس لو مش شغال
    scheduler.remove_all_jobs()
    scheduler.add_job(analyze_machine_issues_cron, 'cron', hour=2, minute=0)
    scheduler.add_job(flush_write_buffer, 'interval', minutes=2)
    scheduler.add_job(cleanup_old_firestore_data, 'cron', hour=3, minute=0)
    
    if not scheduler.running:
        scheduler.start()
        
    yield
    
    if scheduler.running:
        scheduler.shutdown(wait=False)
    
    # تفريغ قاعدة البيانات عند إغلاق التطبيق
    try:
        await engine.dispose()
    except Exception:
        pass

app = FastAPI(title="Workshop Kiosk AI", lifespan=lifespan)

# --- إضافة دعم CORS ليعمل التطبيق بسلاسة مع أي واجهة خارجية مثل Streamlit ---
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # حماية إضافية من نوع Content-Security-Policy
        response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: https://cdn.jsdelivr.net fonts.googleapis.com fonts.gstatic.com;"
        return response
app.add_middleware(SecurityHeadersMiddleware)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# =====================================================================
# معالجة أخطاء الـ 404 بشكل ذكي & الملفات المهمة للـ SEO
# =====================================================================
@app.get("/robots.txt")
async def robots():
    return Response("User-agent: *\nDisallow: /api/\nDisallow: /dashboard/", media_type="text/plain")

def render_html_layout(content: str, title: str, user=None):
    nav_links = ""
    if user:
        if user.role == 'admin':
            nav_links = """
            <li class="nav-item"><a class="nav-link" href="/dashboard"><i class="bi bi-speedometer2"></i> لوحة التحكم</a></li>
            <li class="nav-item"><a class="nav-link" href="/users"><i class="bi bi-people"></i> إدارة العمال</a></li>
            <li class="nav-item"><a class="nav-link" href="/chat"><i class="bi bi-mic-fill"></i> شاشة العمال (Kiosk)</a></li>
            <li class="nav-item"><a class="nav-link" href="/data_management"><i class="bi bi-journal-arrow-up"></i> الكتالوجات والبيانات</a></li>
            <li class="nav-item"><a class="nav-link" href="/settings"><i class="bi bi-gear"></i> إعدادات النظام</a></li>
            """
        else:
            nav_links = """<li class="nav-item"><a class="nav-link active" href="/chat"><i class="bi bi-mic-fill"></i> المساعد الصوتي</a></li>"""
            
        nav_links += f'<li class="nav-item mt-5"><a class="btn-logout text-center fw-bold" href="/logout"><i class="bi bi-box-arrow-right me-2"></i> خروج</a></li>'

    return f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0">
        <title>{title} | مساعد الورشة الذكي</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;900&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg-main: #121212; --bg-card: #1e1e1e; --text-main: #e0e0e0;
                --primary: #FF9800;
                --sidebar-width: 260px;
            }}
            body {{ font-family: 'Cairo', sans-serif; background-color: var(--bg-main); color: var(--text-main); margin: 0; display: flex; flex-direction: column; min-height: 100vh; overflow-x: hidden; }}
            .sidebar {{ width: var(--sidebar-width); background-color: #000; position: fixed; right: 0; top: 0; height: 100vh; padding-top: 2rem; border-left: 2px solid #333; z-index: 1000; transition: 0.3s; }}
            .sidebar .nav-link {{ color: #aaa !important; font-weight: 700; font-size: 1.1rem; padding: 0.8rem; margin: 0.3rem 1rem; border-radius: 10px; transition: 0.3s; }}
            .sidebar .nav-link.active, .sidebar .nav-link:hover {{ background-color: rgba(255, 152, 0, 0.1) !important; color: var(--primary) !important; border: 1px solid var(--primary); }}
            .btn-logout {{ background-color: #2a0000; color: #ff4d4d; border-radius: 10px; padding: 1rem; margin: 1rem; display: block; text-decoration: none; border: 1px solid #ff4d4d; }}
            .main-content {{ margin-right: var(--sidebar-width); flex: 1; padding: 2rem; width: calc(100% - var(--sidebar-width)); display: flex; flex-direction: column; }}
            
            /* تأثير التظليل للبطاقات (Cards) عند المرور عليها */
            .card {{ background-color: var(--bg-card); border: 1px solid #333; border-radius: 15px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: all 0.3s ease; }}
            .card:hover {{ transform: translateY(-5px); box-shadow: 0 8px 25px rgba(255, 152, 0, 0.4); border-color: var(--primary); z-index: 10; }}
            
            .card-header {{ border-bottom: 1px solid #333; font-weight: bold; font-size: 1.2rem; background: #1a1a1a; padding: 15px; }}
            
            /* تأثير التظليل لحقول الإدخال عند التركيز عليها */
            .form-control, .form-select {{ background: #222 !important; border: 1px solid #444 !important; color: #fff !important; font-size: 1.1rem; padding: 10px; transition: all 0.3s ease; }}
            .form-control:focus, .form-select:focus {{ box-shadow: 0 0 10px rgba(255, 152, 0, 0.5); border-color: var(--primary) !important; }}
            
            .btn-primary {{ background-color: var(--primary); border: none; color: #000; font-weight: bold; }}
            .btn-primary:hover {{ background-color: #e68a00; color: #000; }}
            
            @media (max-width: 992px) {{
                .sidebar {{ transform: translateX(100%); }}
                .sidebar.show {{ transform: translateX(0); }}
                .main-content {{ margin-right: 0; width: 100%; padding: 1rem; }}
                .mobile-header {{ display: flex; justify-content: space-between; padding: 15px; background: #000; border-bottom: 1px solid #333; z-index: 1001; }}
            }}
        </style>
    </head>
    <body>
        <div class="mobile-header d-lg-none">
            <h4 class="mb-0 fw-bold" style="color: var(--primary);"><i class="bi bi-tools me-2"></i> المساعد</h4>
            <button class="btn btn-outline-light" onclick="document.querySelector('.sidebar').classList.toggle('show')"><i class="bi bi-list fs-3"></i></button>
        </div>
        
        {f'<aside class="sidebar"><div class="text-center mb-4"><i class="bi bi-tools display-4 text-warning"></i><h4 class="mt-2 text-white">نظام الورشة</h4></div><ul class="nav flex-column">{nav_links}</ul></aside>' if user else ''}
        
        <main class="main-content" style="{'' if user else 'margin-right:0; width:100%; justify-content:center;'}">
            {content}
        </main>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "المسار غير موجود"}, status_code=404)
        
        content = """
        <div class="card shadow-lg mx-auto" style="max-width: 500px; margin-top: 10vh;">
            <div class="card-body p-5 text-center">
                <i class="bi bi-exclamation-triangle display-1 text-danger"></i>
                <h2 class="fw-bold my-4 text-white">404 - الصفحة غير موجودة</h2>
                <p class="text-muted mb-4">يا هندسة، الصفحة اللي بتدور عليها مش موجودة أو الرابط غلط.</p>
                <a href="/" class="btn btn-primary w-100 py-3 fs-5 rounded-pill"><i class="bi bi-house me-2"></i> ارجع للورشة</a>
            </div>
        </div>
        """
        return HTMLResponse(render_html_layout(content, "صفحة مفقودة"), status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=b"", media_type="image/x-icon")

async def get_current_user_from_cookie(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token.replace("Bearer ", ""), SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(select(User).where(User.username == payload.get("sub")))).scalars().first()
        if user:
            user.tenant = await get_tenant_cached(user.tenant_id, db)
        return user
    except: return None

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        db_status = "Connected"
    except Exception as e:
        db_status = f"Error: {e}"
    pinecone_status = "Connected (Singleton)" if pc_client_instance else "Not Initialized"
    return {"status": "OK", "database": db_status, "pinecone": pinecone_status}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user: return RedirectResponse(url="/chat")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    content = """
    <div class="card shadow-lg mx-auto" style="max-width: 400px; margin-top: 10vh;">
        <div class="card-body p-4 text-center">
            <i class="bi bi-tools display-1" style="color: #FF9800;"></i>
            <h2 class="fw-bold my-3 text-white">دخول الورشة</h2>
            <form action="/login" method="post">
                <input type="text" class="form-control mb-3 text-center" name="username" required placeholder="اسم المستخدم (worker / admin)">
                <input type="password" class="form-control mb-4 text-center" name="password" required placeholder="كلمة السر">
                <button type="submit" class="btn btn-primary w-100 py-3 fs-4 rounded-pill">دخول <i class="bi bi-box-arrow-in-left"></i></button>
            </form>
        </div>
    </div>
    """
    return render_html_layout(content, "الدخول")

@app.post("/login")
async def login_post(username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    if not user or not verify_password(password, user.hashed_password):
        return HTMLResponse(render_html_layout("<div class='alert alert-danger text-center'>بيانات خطأ</div>", "خطأ"))
    access_token = create_access_token(data={"sub": user.username}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    res = RedirectResponse(url="/chat", status_code=303)
    
    # 1. إعداد الـ Cookie بشكل آمن للـ Production
    res.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True, secure=IS_PRODUCTION, samesite="lax")
    return res

@app.get("/logout")
async def logout():
    res = RedirectResponse(url="/login")
    res.delete_cookie("access_token")
    return res

# =====================================================================
# واجهات الـ API الخاصة بتطبيق Streamlit الخارجي
# =====================================================================

class LoginRequest(BaseModel):
    username: str
    password: str

class StreamlitChatRequest(BaseModel):
    message: str
    session_id: str = "streamlit_default"

class FirebaseSettingsRequest(BaseModel):
    firebase_credentials: str

class DatabaseSettingsRequest(BaseModel):
    database_url: str

class LLMSettingsJSON(BaseModel):
    llm_provider: str
    llm_model: str
    api_base_url: str = ""
    openai_key: str = ""
    anthropic_key: str = ""
    google_key: str = ""

@app.post("/api/streamlit_login")
async def streamlit_login(login_req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(
        select(User).where(User.username == login_req.username)
    )).scalars().first()
    
    if not user or not verify_password(login_req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="بيانات خطأ")
        
    token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {
        "access_token": token,
        "user": {"username": user.username, "role": user.role}
    }

@app.post("/api/streamlit_chat")
async def streamlit_chat(
    request: Request,
    chat_req: StreamlitChatRequest,
    db: AsyncSession = Depends(get_db)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(
            select(User).where(User.username == payload.get("sub"))
        )).scalars().first()
        if user:
            user.tenant = await get_tenant_cached(user.tenant_id, db)
    except:
        raise HTTPException(status_code=401)
        
    tenant = user.tenant
    google_key = decrypt_val(tenant.google_api_key)
    openai_key = decrypt_val(tenant.openai_api_key)
    
    try:
        if tenant.llm_provider == "google" and google_key:
            llm = ChatGoogleGenerativeAI(
                model=tenant.llm_model,
                google_api_key=google_key,
                temperature=0.3
            )
        elif tenant.llm_provider == "openai" and openai_key:
            llm = ChatOpenAI(
                model_name=tenant.llm_model,
                openai_api_key=openai_key,
                temperature=0.3
            )
        else:
            raise ValueError("مفيش مفتاح API متاح")
            
        history = await get_chat_history(chat_req.session_id, db, limit=3)
        messages = [
            SystemMessage(content=f"{tenant.workshop_prompt}\n\nتاريخ المحادثة:\n{history}"),
            HumanMessage(content=chat_req.message)
        ]
        
        response = await llm.ainvoke(messages)
        await save_chat_history(chat_req.session_id, "Worker", chat_req.message, db, tenant.id)
        await save_chat_history(chat_req.session_id, "AI", response.content, db, tenant.id)
        
        return {"response": response.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings/save_llm_json")
async def save_llm_json(
    request: Request,
    settings: LLMSettingsJSON,
    db: AsyncSession = Depends(get_db)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(
            select(User).where(User.username == payload.get("sub"))
        )).scalars().first()
        if user:
            user.tenant = await get_tenant_cached(user.tenant_id, db)
    except:
        raise HTTPException(status_code=401)
        
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
        
    user.tenant.llm_provider = settings.llm_provider
    user.tenant.llm_model = settings.llm_model
    if hasattr(user.tenant, 'api_base_url'):
        user.tenant.api_base_url = settings.api_base_url
    user.tenant.openai_api_key = encrypt_val(settings.openai_key)
    user.tenant.anthropic_api_key = encrypt_val(settings.anthropic_key)
    user.tenant.google_api_key = encrypt_val(settings.google_key)
    
    with tenant_cache_lock:
        if user.tenant_id in tenant_cache:
            del tenant_cache[user.tenant_id]
    await db.commit()
    return {"status": "ok"}

@app.post("/api/settings/save_firebase")
async def save_firebase_settings(
    request: Request,
    firebase_req: FirebaseSettingsRequest,
    db: AsyncSession = Depends(get_db)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(
            select(User).where(User.username == payload.get("sub"))
        )).scalars().first()
    except:
        raise HTTPException(status_code=401)
        
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
        
    try:
        # تحقق من صحة الـ JSON
        cred_dict = json.loads(firebase_req.firebase_credentials)
        
        # احفظه مشفر في قاعدة البيانات
        user.tenant.firebase_credentials = encrypt_val(firebase_req.firebase_credentials)
        await db.commit()
        
        # ابدأ Firebase فوراً بدون إعادة تشغيل
        global firebase_db
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        firebase_db = firestore.client()
        
        logger.info(f"Firebase connected by user={user.username}")
        return {"status": "connected"}
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="الـ JSON مش صح")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/test_firebase")
async def test_firebase(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(
            select(User).where(User.username == payload.get("sub"))
        )).scalars().first()
    except:
        raise HTTPException(status_code=401)
        
    if firebase_db:
        try:
            # اختبار بسيط بكتابة وقراءة سريعة
            test_ref = firebase_db.collection("_health").document("test")
            test_ref.set({"ts": datetime.utcnow().isoformat()})
            return {"connected": True}
        except Exception as e:
            return {"connected": False, "error": str(e)}
    return {"connected": False, "error": "Firebase غير مهيأ"}

@app.post("/api/settings/save_database")
async def save_database_settings(
    request: Request,
    db_req: DatabaseSettingsRequest,
    db: AsyncSession = Depends(get_db)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = (await db.execute(
            select(User).where(User.username == payload.get("sub"))
        )).scalars().first()
    except:
        raise HTTPException(status_code=401)
        
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
        
    try:
        # احفظ الـ URL الجديد في ملف .env
        db_url = db_req.database_url
        
        # تصحيح الـ URL تلقائياً
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
            
        # اكتب في .env
        env_content = ""
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                lines = f.readlines()
            lines = [l for l in lines if not l.startswith("DATABASE_URL=")]
            env_content = "".join(lines)
            
        with open(".env", "w", encoding="utf-8") as f:
            f.write(env_content)
            f.write(f"\nDATABASE_URL={db_url}\n")
            
        return {"status": "saved", "message": "أعد تشغيل التطبيق لتطبيق التغييرات"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/firebase_usage")
async def get_firebase_usage_api(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_header_or_cookie(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    with usage_lock:
        return {
            "today": str(daily_usage["date"]),
            "reads": daily_usage["reads"],
            "writes": daily_usage["writes"],
            "reads_limit": 50000,
            "writes_limit": 20000,
            "reads_percent": round((daily_usage["reads"] / 50000) * 100, 1),
            "writes_percent": round((daily_usage["writes"] / 20000) * 100, 1)
        }

class StreamlitChatReq(BaseModel):
    message: str
    session_id: str

@app.post("/api/streamlit_chat")
async def streamlit_chat_api(req: StreamlitChatReq, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_header_or_cookie(request, db)
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    
    tenant = user.tenant
    openai_key = decrypt_val(tenant.openai_api_key)
    google_key = decrypt_val(tenant.google_api_key)
    
    try:
        if tenant.llm_provider == "openai" and openai_key:
            llm = ChatOpenAI(model_name=tenant.llm_model, openai_api_key=openai_key, temperature=0.3)
        elif tenant.llm_provider == "google" and google_key:
            llm = ChatGoogleGenerativeAI(model=tenant.llm_model, google_api_key=google_key, temperature=0.3)
        else:
            return JSONResponse({"response": "عذراً، لم يتم إعداد مفاتيح الذكاء الاصطناعي بشكل صحيح."})
            
        messages = [
            SystemMessage(content=tenant.workshop_prompt),
            HumanMessage(content=req.message)
        ]
        
        response = await llm.ainvoke(messages)
        await save_chat_history(req.session_id, "Worker", req.message, db, tenant.id)
        await save_chat_history(req.session_id, "AI", response.content, db, tenant.id)
        
        return {"response": response.content}
    except Exception as e:
        return JSONResponse({"response": f"حدث خطأ: {str(e)}"}, status_code=500)

class SaveLLMReq(BaseModel):
    llm_provider: str
    llm_model: str
    api_base_url: str = ""
    openai_key: str = ""
    anthropic_key: str = ""
    google_key: str = ""

@app.post("/api/settings/save_llm_json")
async def save_llm_json_api(req: SaveLLMReq, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_header_or_cookie(request, db)
    if not user or user.role != "admin": raise HTTPException(status_code=403)
    user.tenant.llm_provider = req.llm_provider
    user.tenant.llm_model = req.llm_model
    if hasattr(user.tenant, 'api_base_url'): user.tenant.api_base_url = req.api_base_url
    user.tenant.openai_api_key = encrypt_val(req.openai_key)
    user.tenant.anthropic_api_key = encrypt_val(req.anthropic_key)
    user.tenant.google_api_key = encrypt_val(req.google_key)
    with tenant_cache_lock:
        if user.tenant_id in tenant_cache: del tenant_cache[user.tenant_id]
    await db.commit()
    return {"status": "success"}

class SaveFirebaseReq(BaseModel):
    firebase_credentials: str

@app.post("/api/settings/save_firebase")
async def save_firebase_api(req: SaveFirebaseReq, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_header_or_cookie(request, db)
    if not user or user.role != "admin": raise HTTPException(status_code=403)
    # في بيئة الإنتاج الحقيقية، يفضل حفظ هذا في الـ Vault أو قاعدة البيانات مش ملف .env 
    # لكن كمثال لحفظه:
    with open(".env", "a", encoding="utf-8") as f:
        f.write(f"\nFIREBASE_CREDENTIALS='{req.firebase_credentials}'\n")
    return {"status": "success", "message": "تم الحفظ. يجب إعادة تشغيل السيرفر لتفعيل التغييرات."}

@app.get("/api/test_firebase")
async def test_firebase_api(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_header_or_cookie(request, db)
    if not user or user.role != "admin": raise HTTPException(status_code=403)
    is_connected = firebase_db is not None
    return {"connected": is_connected}

class SaveDBReq(BaseModel):
    database_url: str

@app.post("/api/settings/save_database")
async def save_database_api(req: SaveDBReq, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_header_or_cookie(request, db)
    if not user or user.role != "admin": raise HTTPException(status_code=403)
    with open(".env", "a", encoding="utf-8") as f:
        f.write(f"\nDATABASE_URL='{req.database_url}'\n")
    return {"status": "success", "message": "تم الحفظ. يجب إعادة تشغيل السيرفر لتفعيل التغييرات."}

# =====================================================================
# 7. لوحة التحكم للمدير (Dashboard)
# =====================================================================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user or user.role != "admin": return RedirectResponse(url="/chat")
    
    # 3. تحسين الأداء بجلب العد فقط دون تحميل البيانات في الذاكرة
    chats_count_result = await db.execute(select(func.count()).where(ConversationHistory.tenant_id == user.tenant_id))
    chats_count = chats_count_result.scalar() or 0
    
    workers_count_result = await db.execute(select(func.count()).where(User.tenant_id == user.tenant_id, User.role == 'worker'))
    workers_count = workers_count_result.scalar() or 0
    
    alerts = (await db.execute(select(Alert).where(Alert.tenant_id == user.tenant_id).order_by(Alert.created_at.desc()).limit(5))).scalars().all()
    
    alerts_html = "".join([f"<li class='list-group-item bg-dark text-danger border-secondary'><i class='bi bi-exclamation-triangle-fill me-2'></i> [{a.created_at.strftime('%Y-%m-%d')}] {a.message}</li>" for a in alerts])
    if not alerts: alerts_html = "<li class='list-group-item bg-dark text-muted border-secondary text-center'>لا توجد تنبيهات لأعطال متكررة مؤخراً. الوضع مستقر!</li>"

    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="text-white m-0"><i class="bi bi-speedometer2 text-primary me-2"></i> لوحة تحكم الورشة</h2>
    </div>
    
    <div class="row g-4 mb-4">
        <div class="col-md-4">
            <div class="card text-center h-100 border-0 bg-dark">
                <div class="card-body">
                    <i class="bi bi-chat-dots display-4 text-warning mb-3"></i>
                    <h3 class="text-white fw-bold">{chats_count}</h3>
                    <p class="text-muted mb-0">إجمالي الرسائل والاستفسارات</p>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card text-center h-100 border-0 bg-dark">
                <div class="card-body">
                    <i class="bi bi-people display-4 text-info mb-3"></i>
                    <h3 class="text-white fw-bold">{workers_count}</h3>
                    <p class="text-muted mb-0">عدد العمال المسجلين</p>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card text-center h-100 border-0 bg-dark">
                <div class="card-body">
                    <i class="bi bi-cash-coin display-4 text-success mb-3"></i>
                    <h3 class="text-white fw-bold">--</h3>
                    <p class="text-muted mb-0">تكلفة الـ API (راجع مزود الخدمة)</p>
                </div>
            </div>
        </div>
    </div>
    
    <div class="card border-0">
        <div class="card-header text-danger"><i class="bi bi-bell-fill me-2"></i> التنبيهات الذكية (الأعطال المتكررة)</div>
        <ul class="list-group list-group-flush">
            {alerts_html}
        </ul>
    </div>
    """
    return render_html_layout(content, "لوحة التحكم", user)

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, msg: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user or user.role != "admin": return RedirectResponse(url="/chat")
    
    workers = (await db.execute(select(User).where(User.tenant_id == user.tenant_id))).scalars().all()
    workers_html = ""
    for w in workers:
        role_badge = "<span class='badge bg-danger'>مدير</span>" if w.role == 'admin' else "<span class='badge bg-primary'>عامل</span>"
        workers_html += f"""
        <tr>
            <td class="text-white">{w.username}</td>
            <td>{role_badge}</td>
            <td>
                <form action="/api/users/delete/{w.id}" method="post" class="d-inline">
                    <button type="submit" class="btn btn-sm btn-outline-danger" onclick="return confirm('هل تريد حذف المستخدم؟')"><i class="bi bi-trash"></i></button>
                </form>
            </td>
        </tr>
        """

    content = f"""
    <h2 class="text-white mb-4"><i class="bi bi-people text-info me-2"></i> إدارة العمال والصنايعية</h2>
    <div class="row g-4">
        <div class="col-md-4">
            <div class="card border-0">
                <div class="card-header text-success"><i class="bi bi-person-plus me-2"></i> إضافة عامل جديد</div>
                <div class="card-body">
                    <form action="/api/users/add" method="post">
                        <input type="text" name="username" class="form-control mb-3" placeholder="اسم المستخدم" required>
                        <input type="password" name="password" class="form-control mb-3" placeholder="كلمة السر" required>
                        <select name="role" class="form-select mb-3">
                            <option value="worker">عامل (يستخدم المحادثة فقط)</option>
                            <option value="admin">مدير (صلاحيات كاملة)</option>
                        </select>
                        <button type="submit" class="btn btn-success w-100">إضافة المستخدم</button>
                    </form>
                </div>
            </div>
        </div>
        <div class="col-md-8">
            <div class="card border-0">
                <div class="card-header text-primary"><i class="bi bi-list-task me-2"></i> قائمة المستخدمين</div>
                <div class="card-body p-0 table-responsive">
                    <table class="table table-dark table-hover mb-0">
                        <thead><tr><th>اسم المستخدم</th><th>الصلاحية</th><th>إجراءات</th></tr></thead>
                        <tbody>{workers_html}</tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    """
    return render_html_layout(content, "إدارة العمال", user)

@app.post("/api/users/add")
async def add_user(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user and user.role == "admin":
        existing = (await db.execute(select(User).where(User.username == username))).scalars().first()
        if not existing:
            new_user = User(username=username, hashed_password=get_password_hash(password), role=role, tenant_id=user.tenant_id)
            db.add(new_user)
            await db.commit()
    return RedirectResponse(url="/users", status_code=303)

@app.post("/api/users/delete/{user_id}")
async def delete_user(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user and user.role == "admin":
        target = (await db.execute(select(User).where(User.id == user_id, User.tenant_id == user.tenant_id))).scalars().first()
        if target and target.id != user.id:
            await db.delete(target)
            await db.commit()
    return RedirectResponse(url="/users", status_code=303)

# =====================================================================
# الإعدادات المخصصة والتخصيص
# =====================================================================
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, msg: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user or user.role != "admin": return RedirectResponse(url="/chat")
    t = user.tenant
    
    alerts = {
        "llm_success": "<div class='alert alert-success alert-dismissible fade show mb-4'><i class='bi bi-check-circle me-2'></i> تم حفظ إعدادات النماذج (LLM) بنجاح.</div>",
        "pinecone_success": "<div class='alert alert-success alert-dismissible fade show mb-4'><i class='bi bi-check-circle me-2'></i> تم حفظ إعدادات الذاكرة (Pinecone) بنجاح.</div>",
        "prompt_success": "<div class='alert alert-success alert-dismissible fade show mb-4'><i class='bi bi-check-circle me-2'></i> تم تحديث شخصية الأسطى بنجاح.</div>",
        "error": "<div class='alert alert-danger alert-dismissible fade show mb-4'><i class='bi bi-exclamation-triangle me-2'></i> حدث خطأ أثناء الحفظ. تأكد من إدخال البيانات بصورة صحيحة.</div>"
    }
    alert_html = alerts.get(msg, "")
    
    dec_openai = decrypt_val(t.openai_api_key)
    dec_anthropic = decrypt_val(t.anthropic_api_key)
    dec_google = decrypt_val(t.google_api_key)
    dec_pinecone = decrypt_val(t.pinecone_api_key)
    base_url_val = getattr(t, 'api_base_url', '')
    
    content = f"""
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2 class="text-white m-0"><i class="bi bi-gear text-warning me-2"></i> إعدادات النظام والتخصيص</h2>
    </div>
    
    {alert_html}
    
    <div class="row g-4">
        <div class="col-lg-6">
            <div class="card h-100 border-0">
                <div class="card-header text-warning"><i class="bi bi-cpu me-2"></i> إعدادات النماذج الحرة (LLMs)</div>
                <div class="card-body">
                    <form action="/api/settings/save_llm" method="post">
                        <div class="mb-3">
                            <label class="form-label text-light fw-bold">مزود الخدمة (Provider)</label>
                            <select name="llm_provider" class="form-select mb-2">
                                <option value="google" {'selected' if t.llm_provider == 'google' else ''}>Google (Gemini)</option>
                                <option value="openai" {'selected' if t.llm_provider == 'openai' else ''}>OpenAI (ChatGPT)</option>
                                <option value="anthropic" {'selected' if t.llm_provider == 'anthropic' else ''}>Anthropic (Claude)</option>
                                <option value="custom" {'selected' if t.llm_provider == 'custom' else ''}>مزود خارجي متوافق مع OpenAI (مثل Local / Groq)</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label text-light fw-bold">اسم الموديل (اكتبه يدوياً بدقة)</label>
                            <input type="text" name="llm_model" class="form-control dir-ltr" value="{t.llm_model}" placeholder="مثال: gemini-1.5-flash أو gpt-4o" required>
                            <small class="text-muted">ملاحظة: يمكنك إدخال أي اسم موديل تريده بحرية تامة.</small>
                        </div>
                        <div class="mb-4">
                            <label class="form-label text-light fw-bold">الرابط المخصص / Base URL (اختياري)</label>
                            <input type="text" name="api_base_url" class="form-control dir-ltr" value="{base_url_val}" placeholder="اتركه فارغاً للوضع الافتراضي">
                        </div>
                        
                        <hr class="border-secondary">
                        <div class="mb-3">
                            <label class="form-label text-light fw-bold">مفتاح OpenAI (مطلوب للصوت)</label>
                            <div class="input-group">
                                <input type="password" name="openai_key" id="openai_key" class="form-control dir-ltr" placeholder="sk-proj-..." value="{dec_openai}">
                                <button class="btn btn-outline-secondary bg-dark text-white border-secondary" type="button" onclick="toggleVisibility('openai_key', this)"><i class="bi bi-eye"></i></button>
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label text-light fw-bold">مفتاح Anthropic</label>
                            <div class="input-group">
                                <input type="password" name="anthropic_key" id="anthropic_key" class="form-control dir-ltr" placeholder="sk-ant-..." value="{dec_anthropic}">
                                <button class="btn btn-outline-secondary bg-dark text-white border-secondary" type="button" onclick="toggleVisibility('anthropic_key', this)"><i class="bi bi-eye"></i></button>
                            </div>
                        </div>
                        <div class="mb-4">
                            <label class="form-label text-light fw-bold">مفتاح Google Gemini</label>
                            <div class="input-group">
                                <input type="password" name="google_key" id="google_key" class="form-control dir-ltr" placeholder="AIza..." value="{dec_google}">
                                <button class="btn btn-outline-secondary bg-dark text-white border-secondary" type="button" onclick="toggleVisibility('google_key', this)"><i class="bi bi-eye"></i></button>
                            </div>
                        </div>
                        <button type="submit" class="btn btn-primary w-100 py-2"><i class="bi bi-save me-2"></i> حفظ إعدادات الموديل</button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="col-lg-6">
            <div class="card h-100 border-0">
                <div class="card-header text-info"><i class="bi bi-database me-2"></i> الذاكرة والكتالوجات (Pinecone)</div>
                <div class="card-body">
                    <div class="alert alert-dark text-light small border-secondary mb-3">
                        <i class="bi bi-info-circle text-info me-1"></i> 
                        إذا لم تضع مفتاح OpenAI، سيتم استخدام مفتاح <strong>جيميناي (Google)</strong> تلقائياً لتضمين الكتالوجات.
                    </div>
                    <form action="/api/settings/save_pinecone" method="post">
                        <div class="mb-3">
                            <label class="form-label text-light fw-bold">Pinecone API Key</label>
                            <div class="input-group">
                                <input type="password" name="pinecone_key" id="pinecone_key" class="form-control dir-ltr" placeholder="pc-sk-..." value="{dec_pinecone}">
                                <button class="btn btn-outline-secondary bg-dark text-white border-secondary" type="button" onclick="toggleVisibility('pinecone_key', this)"><i class="bi bi-eye"></i></button>
                            </div>
                        </div>
                        <div class="mb-4">
                            <label class="form-label text-light fw-bold">اسم الفهرس (Pinecone Index Name)</label>
                            <input type="text" name="pinecone_index" class="form-control dir-ltr" placeholder="workshop-index" value="{t.pinecone_index}">
                        </div>
                        <button type="submit" class="btn btn-info w-100 py-2 fw-bold"><i class="bi bi-hdd-network me-2"></i> حفظ إعدادات الذاكرة</button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="col-lg-12">
            <div class="card border-0 mb-4">
                <div class="card-header text-success"><i class="bi bi-person-workspace me-2"></i> شخصية المساعد (System Prompt)</div>
                <div class="card-body">
                    <form action="/api/settings/save_prompt" method="post">
                        <textarea name="workshop_prompt" class="form-control mb-3" style="min-height: 150px;">{t.workshop_prompt}</textarea>
                        <button type="submit" class="btn btn-success w-100 py-2 fw-bold text-dark"><i class="bi bi-person-check me-2"></i> تحديث الشخصية</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function toggleVisibility(inputId, btnElement) {{
            var input = document.getElementById(inputId);
            var icon = btnElement.querySelector('i');
            if (input.type === "password") {{
                input.type = "text";
                icon.classList.remove('bi-eye');
                icon.classList.add('bi-eye-slash');
            }} else {{
                input.type = "password";
                icon.classList.remove('bi-eye-slash');
                icon.classList.add('bi-eye');
            }}
        }}
    </script>
    """
    return render_html_layout(content, "الإعدادات", user)

@app.post("/api/settings/save_llm")
async def save_llm(request: Request, llm_provider: str = Form(...), llm_model: str = Form(...), api_base_url: str = Form(""), openai_key: str = Form(""), anthropic_key: str = Form(""), google_key: str = Form(""), db: AsyncSession = Depends(get_db)):
    try:
        user = await get_current_user_from_cookie(request, db)
        if user and user.role == "admin":
            user.tenant.llm_provider = llm_provider
            user.tenant.llm_model = llm_model
            
            # التأكد من وجود الحقل قبل الحفظ (للتوافق مع قواعد البيانات القديمة)
            if hasattr(user.tenant, 'api_base_url'):
                user.tenant.api_base_url = api_base_url
                
            user.tenant.openai_api_key = encrypt_val(openai_key)
            user.tenant.anthropic_api_key = encrypt_val(anthropic_key)
            user.tenant.google_api_key = encrypt_val(google_key)
            with tenant_cache_lock:
                if user.tenant_id in tenant_cache:
                    del tenant_cache[user.tenant_id]
            await db.commit()
            logger.info(f"USER_ACTION | user={user.username} | tenant={user.tenant_id} | action=save_llm_settings")
        return RedirectResponse(url="/settings?msg=llm_success", status_code=303)
    except Exception as e:
        logger.error(f"Error saving LLM settings: {e}")
        return RedirectResponse(url="/settings?msg=error", status_code=303)

@app.post("/api/settings/save_pinecone")
async def save_pinecone(request: Request, pinecone_key: str = Form(""), pinecone_index: str = Form(""), db: AsyncSession = Depends(get_db)):
    global pc_client_instance
    try:
        user = await get_current_user_from_cookie(request, db)
        if user and user.role == "admin":
            user.tenant.pinecone_api_key = encrypt_val(pinecone_key)
            if pinecone_key: 
                pc_client_instance = PineconeClient(api_key=pinecone_key)
            else:
                pc_client_instance = None
            user.tenant.pinecone_index = pinecone_index
            with tenant_cache_lock:
                if user.tenant_id in tenant_cache:
                    del tenant_cache[user.tenant_id]
            await db.commit()
            logger.info(f"USER_ACTION | user={user.username} | tenant={user.tenant_id} | action=save_pinecone_settings")
        return RedirectResponse(url="/settings?msg=pinecone_success", status_code=303)
    except Exception:
        return RedirectResponse(url="/settings?msg=error", status_code=303)

@app.post("/api/settings/save_prompt")
async def save_prompt(request: Request, workshop_prompt: str = Form(...), db: AsyncSession = Depends(get_db)):
    try:
        user = await get_current_user_from_cookie(request, db)
        if user and user.role == "admin":
            user.tenant.workshop_prompt = workshop_prompt
            with tenant_cache_lock:
                if user.tenant_id in tenant_cache:
                    del tenant_cache[user.tenant_id]
            await db.commit()
        return RedirectResponse(url="/settings?msg=prompt_success", status_code=303)
    except Exception:
        return RedirectResponse(url="/settings?msg=error", status_code=303)

# =====================================================================
# إدارة البيانات والكتالوجات المرفوعة
# =====================================================================
async def process_rag_document_bg(file_content: bytes, filename: str, tenant_id: int):
    async with AsyncSessionLocal() as db:
        try:
            tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
            openai_key = decrypt_val(tenant.openai_api_key)
            google_key = decrypt_val(tenant.google_api_key)
            pinecone_key = decrypt_val(tenant.pinecone_api_key)
            
            if not tenant or not pinecone_key or not pc_client_instance or not tenant.pinecone_index: return

            embeddings = None
            if openai_key:
                embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
            elif google_key:
                embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key)
            if not embeddings: return

            text_data = ""
            if filename.lower().endswith('.pdf'):
                pdf_reader = PdfReader(io.BytesIO(file_content))
                for page in pdf_reader.pages: text_data += (page.extract_text() or "") + "\n"
            else: text_data = file_content.decode('utf-8')
                
            chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_text(text_data)
            metadatas = [{"filename": filename} for _ in chunks]
            vector_store = PineconeVectorStore(index=pc_client_instance.Index(tenant.pinecone_index), embedding=embeddings, namespace=f"tenant_{tenant_id}")
            vector_store.add_texts(texts=chunks, metadatas=metadatas)
        except Exception as e: logger.error(f"RAG Error: {e}")

@app.get("/data_management", response_class=HTMLResponse)
async def data_management_page(request: Request, msg: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user or user.role != "admin": return RedirectResponse(url="/chat")
    
    docs = (await db.execute(select(UploadedDocument).where(UploadedDocument.tenant_id == user.tenant_id).order_by(UploadedDocument.id.desc()))).scalars().all()
    docs_html = ""
    for d in docs:
        docs_html += f"""
        <li class="list-group-item d-flex justify-content-between align-items-center bg-dark text-white border-secondary mb-2 rounded">
            <span><i class="bi bi-file-earmark-text text-warning me-3 fs-5"></i> {d.filename}</span>
            <form action="/api/delete_rag/{d.id}" method="post" class="m-0">
                <button type="submit" class="btn btn-outline-danger btn-sm px-3" onclick="return confirm('هل أنت متأكد من حذف هذا الكتالوج؟')"><i class="bi bi-trash"></i> حذف</button>
            </form>
        </li>
        """
    if not docs: docs_html = "<div class='text-center text-muted my-4'><i class='bi bi-inbox fs-1'></i><br>لا توجد كتالوجات مرفوعة حالياً.</div>"

    alert_html = ""
    if msg == "error_size": alert_html = "<div class='alert alert-danger'>حجم الملف يتعدى الحد الأقصى (20 ميجابايت).</div>"
    elif msg == "error_type": alert_html = "<div class='alert alert-danger'>صيغة الملف غير مدعومة. فقط PDF أو TXT مسموح.</div>"
    elif msg == "duplicate": alert_html = "<div class='alert alert-warning'>الملف ده اترفع قبل كده يا هندسة، مفيش داعي للتكرار.</div>"

    content = f"""
    {alert_html}
    <div class="row g-4">
        <div class="col-lg-5">
            <div class="card p-4 h-100 border-0">
                <div class="text-center mb-4">
                    <i class="bi bi-cloud-arrow-up display-1 text-primary"></i>
                    <h4 class="text-white mt-3">رفع الكتالوجات (متعدد)</h4>
                    <p class="text-muted small">يمكنك اختيار ملفات PDF أو TXT (الحد الأقصى 20 ميجا للملف).</p>
                </div>
                <form action="/api/upload_rag" method="post" enctype="multipart/form-data">
                    <input class="form-control form-control-lg mb-4 bg-dark text-white border-secondary" type="file" name="files" multiple accept=".pdf, .txt" required>
                    <button type="submit" class="btn btn-primary w-100 py-3 fs-5 fw-bold rounded-pill"><i class="bi bi-upload me-2"></i> ارفع وعلم المساعد</button>
                </form>
            </div>
        </div>
        <div class="col-lg-7">
            <div class="card p-4 h-100 border-0">
                <h4 class="text-white mb-4 border-bottom border-secondary pb-3"><i class="bi bi-folder-fill text-warning me-2"></i> الملفات والكتالوجات المخزنة</h4>
                <ul class="list-group list-group-flush" style="max-height: 400px; overflow-y: auto; padding-right: 5px;">
                    {docs_html}
                </ul>
            </div>
        </div>
    </div>
    """
    return render_html_layout(content, "الكتالوجات", user)

@app.post("/api/upload_rag")
async def upload_rag_api(request: Request, background_tasks: BackgroundTasks, files: List[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user and user.role == "admin":
        MAX_FILE_SIZE = 20 * 1024 * 1024
        for file in files:
            # 5. منع التكرار
            existing_doc = (await db.execute(select(UploadedDocument).where(UploadedDocument.filename == file.filename, UploadedDocument.tenant_id == user.tenant_id))).scalars().first()
            if existing_doc:
                return RedirectResponse(url="/data_management?msg=duplicate", status_code=303)
                
            content = await file.read()
            if len(content) > MAX_FILE_SIZE: return RedirectResponse(url="/data_management?msg=error_size", status_code=303)
            
            # استنتاج نوع الملف باستخدام امتداده بدل filetype اللي بتعمل مشاكل
            filename_lower = file.filename.lower()
            if not (filename_lower.endswith('.pdf') or filename_lower.endswith('.txt')):
                return RedirectResponse(url="/data_management?msg=error_type", status_code=303)

            new_doc = UploadedDocument(filename=file.filename, tenant_id=user.tenant_id)
            db.add(new_doc)
            await db.commit()
            logger.info(f"USER_ACTION | user={user.username} | tenant={user.tenant_id} | action=upload_doc | file={file.filename}")
            background_tasks.add_task(process_rag_document_bg, content, file.filename, user.tenant_id)
        return RedirectResponse(url="/data_management", status_code=303)
    return RedirectResponse(url="/data_management")

# 2. تغيير مسار الحذف ليكون POST لمنع ثغرات الـ CSRF
@app.post("/api/delete_rag/{doc_id}")
async def delete_rag_api(doc_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user and user.role == "admin":
        doc = (await db.execute(select(UploadedDocument).where(UploadedDocument.id == doc_id, UploadedDocument.tenant_id == user.tenant_id))).scalars().first()
        if doc:
            tenant = user.tenant
            if pc_client_instance and tenant.pinecone_index:
                try:
                    idx = pc_client_instance.Index(tenant.pinecone_index)
                    idx.delete(filter={"filename": doc.filename}, namespace=f"tenant_{tenant.id}")
                except Exception as e: logger.error(f"Failed to delete from Pinecone: {e}")
            await db.delete(doc)
            await db.commit()
            logger.info(f"USER_ACTION | user={user.username} | tenant={user.tenant_id} | action=delete_doc | doc_id={doc_id}")
    return RedirectResponse(url="/data_management", status_code=303)

# =====================================================================
# إدارة جلسات المحادثة (إعادة تسمية / حذف)
# =====================================================================
@app.post("/api/chat/rename/{session_uuid}")
async def rename_chat_session(session_uuid: str, request: Request, title: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user:
        chat_session = (await db.execute(select(ChatSession).where(ChatSession.session_uuid == session_uuid, ChatSession.user_id == user.id))).scalars().first()
        if chat_session:
            chat_session.title = title
            chat_session.updated_at = datetime.utcnow()
            await db.commit()
    return RedirectResponse(url=f"/chat?session={session_uuid}", status_code=303)

@app.post("/api/chat/delete/{session_uuid}")
async def delete_chat_session(session_uuid: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if user:
        chat_session = (await db.execute(select(ChatSession).where(ChatSession.session_uuid == session_uuid, ChatSession.user_id == user.id))).scalars().first()
        if chat_session:
            await db.execute(text("DELETE FROM conversation_history WHERE session_id = :sid AND tenant_id = :tid"), {"sid": session_uuid, "tid": user.tenant_id})
            await db.delete(chat_session)
            await db.commit()
    return RedirectResponse(url="/chat", status_code=303)

# =====================================================================
# واجهة الـ Kiosk ودردشة العمال
# =====================================================================
@app.get("/chat", response_class=HTMLResponse)
async def kiosk_chat_page(request: Request, session: Optional[str] = None, new: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse(url="/login")
    
    # 1. جلب أو إنشاء جلسات المحادثة (Chat Sessions)
    sessions_result = await db.execute(select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc()))
    user_sessions = sessions_result.scalars().all()

    current_session = None

    if new == 1:
        new_sess = ChatSession(user_id=user.id, tenant_id=user.tenant_id, title="محادثة جديدة")
        db.add(new_sess)
        await db.commit()
        await db.refresh(new_sess)
        return RedirectResponse(url=f"/chat?session={new_sess.session_uuid}")

    if session:
        current_session = (await db.execute(select(ChatSession).where(ChatSession.session_uuid == session, ChatSession.user_id == user.id))).scalars().first()
    
    if not current_session:
        if user_sessions:
            current_session = user_sessions[0]
        else:
            new_sess = ChatSession(user_id=user.id, tenant_id=user.tenant_id, title="محادثة جديدة")
            db.add(new_sess)
            await db.commit()
            await db.refresh(new_sess)
            current_session = new_sess
            user_sessions = [current_session]
    
    current_session_uuid = current_session.session_uuid

    # 2. بناء الـ HTML الخاص بقائمة المحادثات (Sidebar)
    sessions_html = ""
    for s in user_sessions:
        active_class = "active" if s.session_uuid == current_session_uuid else ""
        sessions_html += f"""
        <div class="session-item {active_class}">
            <a href="/chat?session={s.session_uuid}" title="{html.escape(s.title)}">
                <i class="bi bi-chat-left-text me-2"></i> {html.escape(s.title)}
            </a>
            <div class="session-actions">
                <button onclick="renameSession('{s.session_uuid}', '{html.escape(s.title)}')"><i class="bi bi-pencil"></i></button>
                <button onclick="deleteSession('{s.session_uuid}')"><i class="bi bi-trash text-danger"></i></button>
            </div>
        </div>
        """

    # 3. جلب تاريخ الرسائل للجلسة الحالية
    history_result = await db.execute(
        select(ConversationHistory)
        .where(ConversationHistory.session_id == current_session_uuid, ConversationHistory.tenant_id == user.tenant_id)
        .order_by(ConversationHistory.created_at.desc())
        .limit(50)
    )
    chat_history = list(reversed(history_result.scalars().all()))

    history_html = ""
    for msg in chat_history:
        if msg.role == "Worker":
            history_html += f'<div class="bubble user">{msg.content}</div>'
        else:
            safe_text = msg.content.replace("\\", "\\\\").replace("'", "\\'").replace('"', '&quot;').replace('\n', ' ')
            display_content = msg.content.replace('\n', '<br>')
            history_html += f'''<div class="bubble ai">{display_content}
            <button class="speak-btn" onclick="speakText(this, '{safe_text}')"><i class="bi bi-volume-up-fill"></i></button>
            </div>'''
            
    content_html = f"""
    <style>
        .main-content {{ padding: 0 !important; width: calc(100% - var(--sidebar-width)); height: 100vh; overflow: hidden; display: flex; flex-direction: column; background: #000; position: relative;}}
        @media (max-width: 992px) {{ .main-content {{ width: 100%; height: calc(100vh - 60px); }} }}
        
        /* تنسيقات الشريط الجانبي للمحادثات */
        .chat-history-sidebar {{
            position: absolute; top: 0; left: 0; width: 300px; height: 100vh;
            background: #111; border-right: 1px solid #333; z-index: 1050;
            transform: translateX(-100%); transition: transform 0.3s ease;
            display: flex; flex-direction: column; box-shadow: 2px 0 10px rgba(0,0,0,0.5);
        }}
        .chat-history-sidebar.show {{ transform: translateX(0); }}
        .session-item {{ display: flex; justify-content: space-between; align-items: center; padding: 15px; border-bottom: 1px solid #222; transition: 0.2s; }}
        .session-item a {{ color: #ccc; text-decoration: none; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 1.1rem; }}
        .session-item:hover, .session-item.active {{ background: #222; }}
        .session-item:hover a, .session-item.active a {{ color: var(--primary); font-weight: bold; }}
        .session-actions {{ display: flex; gap: 15px; margin-right: 10px; }}
        .session-actions button {{ background: none; border: none; color: #777; cursor: pointer; padding: 0; font-size: 1.1rem; }}
        .session-actions button:hover {{ color: #fff; transform: scale(1.1); }}
        .toggle-history-btn {{
            position: absolute; top: 15px; left: 15px; z-index: 1040;
            background: rgba(0,0,0,0.7); border: 1px solid #555; color: var(--primary);
            border-radius: 8px; padding: 8px 15px; font-weight: bold; cursor: pointer;
            backdrop-filter: blur(5px);
        }}
        .toggle-history-btn:hover {{ background: rgba(0,0,0,0.9); color: #fff; border-color: var(--primary); }}

        .chat-area {{ flex: 1; overflow-y: auto; padding: 20px; padding-top: 70px; display: flex; flex-direction: column; gap: 20px; scroll-behavior: smooth; }}
        .bubble {{ max-width: 90%; padding: 20px; border-radius: 20px; font-size: 1.3rem; font-weight: bold; line-height: 1.6; position: relative; }}
        .bubble.ai {{ background: #1e1e1e; color: #fff; align-self: flex-start; border-top-right-radius: 5px; border: 2px solid #333; }}
        .bubble.user {{ background: var(--primary); color: #000; align-self: flex-end; border-top-left-radius: 5px; }}
        .bubble img {{ max-width: 250px; max-height: 250px; object-fit: contain; border-radius: 10px; margin-top: 10px; border: 1px solid #444; background: #000; }}
        .audio-wave {{ display: inline-block; width: 30px; height: 15px; background: url('https://i.imgur.com/3vB9V5H.gif') center/cover; }}
        .speak-btn {{ position: absolute; bottom: -15px; left: -15px; background: #00bcd4; color: #000; border: none; border-radius: 50%; width: 45px; height: 45px; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; cursor: pointer; box-shadow: 0 4px 10px rgba(0,0,0,0.5); z-index: 10;}}
        .speak-btn:active {{ transform: scale(0.9); }}
        .speak-btn.playing {{ background: #f44336; color: #fff; animation: pulse-red 1s infinite; }}
        .controls-area {{ background: #111; padding: 20px; display: flex; gap: 15px; border-top: 2px solid #333; align-items: center; }}
        .kiosk-btn {{ flex: 1; border: none; border-radius: 20px; height: 80px; font-size: 2rem; font-weight: 900; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: 0.1s; user-select: none; -webkit-user-select: none; }}
        .kiosk-btn:active {{ transform: scale(0.95); }}
        .btn-mic {{ background: #FF9800; color: #000; touch-action: none; }}
        .btn-camera {{ background: #2196F3; color: #fff; flex: 0.3; }}
        .chat-input {{ flex: 1; display: none; background: #222; border: 2px solid #444; color: #fff; border-radius: 20px; padding: 15px; font-size: 1.5rem; }}
        .btn-keyboard {{ background: transparent; border: none; color: #888; font-size: 2rem; }}
        @keyframes pulse-red {{ 0% {{ box-shadow: 0 0 0 0 rgba(244, 67, 54, 0.8); }} 70% {{ box-shadow: 0 0 0 25px rgba(244, 67, 54, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(244, 67, 54, 0); }} }}
    </style>

    <!-- زر فتح السجل -->
    <button class="toggle-history-btn" onclick="document.getElementById('chat-history-sidebar').classList.toggle('show')">
        <i class="bi bi-layout-sidebar-inset"></i> سجل المحادثات
    </button>

    <!-- القائمة الجانبية للسجل -->
    <div id="chat-history-sidebar" class="chat-history-sidebar">
       <div class="p-3 border-bottom border-secondary d-flex justify-content-between align-items-center bg-dark">
           <h5 class="m-0 text-white"><i class="bi bi-clock-history text-primary me-2"></i> المحادثات</h5>
           <a href="/chat?new=1" class="btn btn-sm btn-primary fw-bold"><i class="bi bi-plus-lg"></i> جديدة</a>
       </div>
       <div style="overflow-y: auto; flex: 1;">
           {sessions_html}
       </div>
       <button class="btn btn-outline-secondary m-3" onclick="document.getElementById('chat-history-sidebar').classList.remove('show')">إغلاق <i class="bi bi-x"></i></button>
    </div>

    <div class="chat-area" id="chatBox">
        <div class="bubble ai mt-2">
            <i class="bi bi-robot text-warning me-2 fs-1"></i> يا هلا بالصنايعية رجالة الورشة! 
            <br>عشان تبعت رسالة صوتية، <strong>اضغط باستمرار</strong> على المايك البرتقالي تحت، اتكلم براحتك ولما تخلص شيل صباعك عشان يتبعت.
            <button class="speak-btn" onclick="speakText(this, 'يا هلا بالصنايعية رجالة الورشة! عشان تبعت رسالة صوتية، اضغط باستمرار على المايك البرتقالي تحت، اتكلم براحتك ولما تخلص شيل صباعك عشان يتبعت.')"><i class="bi bi-volume-up-fill"></i></button>
        </div>
        """ + history_html + """
    </div>
    
    <div id="image-preview-container" style="display:none; padding: 15px 20px; background: #111; text-align: right; border-top: 1px solid #333;">
        <div style="display: inline-block; position: relative;">
            <img id="image-preview" src="" style="width: 80px; height: 80px; object-fit: cover; border-radius: 12px; border: 2px solid #555; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <button class="btn btn-danger btn-sm" onclick="cancelImage()" style="position: absolute; top: -8px; right: -8px; border-radius: 50%; width: 26px; height: 26px; padding: 0; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(0,0,0,0.5);"><i class="bi bi-x"></i></button>
        </div>
    </div>

    <div class="controls-area">
        <button class="btn-keyboard" onclick="toggleKeyboard()"><i class="bi bi-keyboard"></i></button>
        <input type="text" id="chatInput" class="chat-input" placeholder="اكتب سؤالك هنا..." onkeypress="if(event.key === 'Enter') sendMessage()">
        <input type="file" id="hidden-camera-input" accept="image/*" style="display:none;" onchange="handleImageSelect(event)">
        <button class="kiosk-btn btn-camera" onclick="openCamera()"><i class="bi bi-camera-fill"></i></button>
        <button id="micBtn" class="kiosk-btn btn-mic"><i class="bi bi-mic-fill me-2"></i> اضغط باستمرار للتسجيل</button>
        <button id="sendTextBtn" class="kiosk-btn btn-mic" style="display:none; background:#4CAF50; color:#fff;" onclick="sendMessage()"><i class="bi bi-send-fill me-2"></i> إرسال</button>
    </div>
    """
    
    content_js = f"""
    <script>
        const currentSessionUuid = '{current_session_uuid}';

        // دوال التحكم في جلسات المحادثة
        async function renameSession(uuid, currentTitle) {{
            const newTitle = prompt("أدخل الاسم الجديد للمحادثة:", currentTitle);
            if (newTitle && newTitle.trim() !== "" && newTitle !== currentTitle) {{
                const fd = new FormData();
                fd.append("title", newTitle);
                await fetch(`/api/chat/rename/${{uuid}}`, {{ method: 'POST', body: fd }});
                window.location.reload();
            }}
        }}

        async function deleteSession(uuid) {{
            if (confirm("هل أنت متأكد من حذف هذه المحادثة بالكامل؟")) {{
                await fetch(`/api/chat/delete/${{uuid}}`, {{ method: 'POST' }});
                window.location.href = '/chat';
            }}
        }}

        const chatBox = document.getElementById('chatBox');
        
        // Auto-scroll to bottom on load if there's history
        setTimeout(() => chatBox.scrollTop = chatBox.scrollHeight, 100);
        
        const micBtn = document.getElementById('micBtn');
        const chatInput = document.getElementById('chatInput');
        const sendTextBtn = document.getElementById('sendTextBtn');
        const imagePreviewContainer = document.getElementById('image-preview-container');
        const imagePreview = document.getElementById('image-preview');
        const cameraInput = document.getElementById('hidden-camera-input');
        
        let isRecording = false;
        let isStarting = false;
        let mediaRecorder = null;
        let audioChunks = [];
        let currentBase64Image = null;
        let useNativeMic = false;
        let recognition = null;
        
        function openCamera() {{
            const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
            cameraInput.setAttribute('capture', isMobile ? 'environment' : '');
            cameraInput.click();
        }}

        class AudioQueue {{
            constructor() {{ this.queue = []; this.isPlaying = false; }}
            async add(text, btn) {{
                this.queue.push({{ text, btn }});
                if (!this.isPlaying) this.playNext();
            }}
            async playNext() {{
                if (this.queue.length === 0) {{ this.isPlaying = false; return; }}
                this.isPlaying = true;
                const {{ text, btn }} = this.queue.shift();
                await this.processSpeech(btn, text);
                this.playNext();
            }}
            async processSpeech(btnElement, text) {{
                return new Promise(async (resolve) => {{
                    if(btnElement) {{
                        btnElement.classList.add('playing');
                        btnElement.innerHTML = '<i class="bi bi-stop-fill"></i>';
                    }}
                    let cleanText = text.replace(/<[^>]*>?/gm, '').replace(/[*#_]/g, '');
                    
                    try {{
                        const response = await fetch('/api/tts', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ text: cleanText }})
                        }});
                        if (!response.ok) throw new Error('TTS Backend Failed');
                        const blob = await response.blob();
                        const audio = new Audio(URL.createObjectURL(blob));
                        window.currentAudio = audio;
                        audio.onended = () => {{ if(btnElement) {{ btnElement.classList.remove('playing'); btnElement.innerHTML = '<i class="bi bi-volume-up-fill"></i>'; }} resolve(); }};
                        audio.onerror = () => {{ if(btnElement) {{ btnElement.classList.remove('playing'); btnElement.innerHTML = '<i class="bi bi-volume-up-fill"></i>'; }} resolve(); }};
                        await audio.play();
                    }} catch (error) {{
                        if ('speechSynthesis' in window) {{
                            const utterance = new SpeechSynthesisUtterance(cleanText);
                            utterance.lang = 'ar-EG'; utterance.rate = 0.9;
                            utterance.onend = () => {{ if(btnElement) {{ btnElement.classList.remove('playing'); btnElement.innerHTML = '<i class="bi bi-volume-up-fill"></i>'; }} resolve(); }};
                            window.speechSynthesis.speak(utterance);
                        }} else {{
                            resolve();
                        }}
                    }}
                }});
            }}
            stop() {{
                this.queue = []; 
                this.isPlaying = false;
                if (window.currentAudio) {{ 
                    window.currentAudio.pause(); 
                    window.currentAudio.currentTime = 0;
                    window.currentAudio = null; 
                }}
                if ('speechSynthesis' in window) window.speechSynthesis.cancel();
                document.querySelectorAll('.speak-btn').forEach(btn => {{
                    btn.classList.remove('playing');
                    btn.innerHTML = '<i class="bi bi-volume-up-fill"></i>';
                }});
            }}
        }}
        const audioQueue = new AudioQueue();

        function speakText(btnElement, text) {{
            if (btnElement && btnElement.classList.contains('playing')) {{
                audioQueue.stop();
                return;
            }}
            if (audioQueue.isPlaying) {{
                audioQueue.stop();
            }}
            audioQueue.add(text, btnElement);
        }}

        function resetMicBtn() {{
            micBtn.classList.remove('recording', 'bg-danger');
            micBtn.style.transform = 'scale(1)';
            micBtn.innerHTML = '<i class="bi bi-mic-fill me-2"></i> اضغط باستمرار للتسجيل';
        }}

        function startNativeRecording() {{
            if (isRecording) return;
            window.SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!window.SpeechRecognition) {{
                alert("متصفحك لا يدعم المايك الداخلي المجاني، يرجى استخدام متصفح جوجل كروم.");
                return;
            }}
            
            recognition = new window.SpeechRecognition();
            recognition.lang = 'ar-EG';
            recognition.interimResults = true;
            
            recognition.onstart = () => {{
                isRecording = true;
                micBtn.classList.add('recording', 'bg-danger');
                micBtn.style.transform = 'scale(1.05)';
                micBtn.innerHTML = '<i class="bi bi-mic-fill me-2 text-white"></i> جاري الاستماع... ارفع للإرسال';
                chatInput.value = '';
                audioQueue.stop();
            }};
            
            recognition.onresult = (e) => {{
                let text = '';
                for (let i = e.resultIndex; i < e.results.length; ++i) {{ text += e.results[i][0].transcript; }}
                chatInput.value = text;
            }};
            
            recognition.onerror = () => {{
                isRecording = false;
                resetMicBtn();
            }};
            
            recognition.onend = () => {{
                isRecording = false;
                resetMicBtn();
                if (chatInput.value.trim() !== '') {{
                    sendMessage(chatInput.value.trim(), null);
                    chatInput.value = '';
                }}
            }};
            
            recognition.start();
        }}

        function stopNativeRecording() {{
            if (!isRecording) return;
            if(recognition) recognition.stop();
            isRecording = false;
            resetMicBtn();
        }}

        async function startRecording() {{
            if (isRecording || isStarting) return;
            isStarting = true;
            try {{
                const stream = await navigator.mediaDevices.getUserMedia({{ audio: {{ echoCancellation: true, noiseSuppression: true, autoGainControl: true }} }});
                
                // حماية: إذا رفع المستخدم يده قبل أن يجهز المايك
                if (!isStarting) {{
                    stream.getTracks().forEach(track => track.stop());
                    return;
                }}
                
                micBtn.classList.add('recording', 'bg-danger');
                micBtn.style.transform = 'scale(1.05)';
                micBtn.innerHTML = '<i class="bi bi-mic-fill me-2 text-white"></i> جاري التسجيل... ارفع للإرسال';
                
                let options = {{}};
                if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) options = {{ mimeType: 'audio/webm;codecs=opus' }};
                else if (MediaRecorder.isTypeSupported('audio/mp4')) options = {{ mimeType: 'audio/mp4' }};
                
                mediaRecorder = new MediaRecorder(stream, options);
                audioChunks = [];
                mediaRecorder.ondataavailable = e => {{ if (e.data.size > 0) audioChunks.push(e.data); }};
                
                mediaRecorder.onstop = () => {{
                    setTimeout(() => {{
                        const audioBlob = new Blob(audioChunks, {{ type: mediaRecorder.mimeType || 'audio/webm' }});
                        if (audioBlob.size < 1000) {{
                            const aiDiv = document.createElement('div');
                            aiDiv.className = 'bubble ai text-danger';
                            aiDiv.innerHTML = 'الصوت قصير جداً يا هندسة.. دوس باستمرار عشان تسجل';
                            chatBox.appendChild(aiDiv);
                            return;
                        }}
                        const reader = new FileReader();
                        reader.readAsDataURL(audioBlob);
                        reader.onloadend = () => {{ sendMessage(null, reader.result); }};
                    }}, 300);
                    stream.getTracks().forEach(track => track.stop());
                }};
                
                mediaRecorder.start();
                isRecording = true;
                isStarting = false;
                audioQueue.stop();
            }} catch (err) {{ 
                isStarting = false;
                alert('عفواً يا هندسة، المتصفح مش قادر يوصل للمايك.'); 
            }}
        }}

        function stopRecording() {{
            isStarting = false;
            if (!isRecording) return;
            if(mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
            isRecording = false;
            resetMicBtn();
        }}

        // ربط أحداث الضغط والرفع بالزر ليعمل كـ Push-to-Talk (زي واتساب)
        const handleStart = (e) => {{ e.preventDefault(); useNativeMic ? startNativeRecording() : startRecording(); }};
        const handleStop = (e) => {{ e.preventDefault(); useNativeMic ? stopNativeRecording() : stopRecording(); }};

        micBtn.addEventListener('mousedown', handleStart);
        micBtn.addEventListener('mouseup', handleStop);
        micBtn.addEventListener('mouseleave', handleStop); // للإلغاء لو الماوس خرج عن الزر
        
        micBtn.addEventListener('touchstart', handleStart, {{passive: false}});
        micBtn.addEventListener('touchend', handleStop, {{passive: false}});
        micBtn.addEventListener('touchcancel', handleStop, {{passive: false}});


        function handleImageSelect(e) {{
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(event) {{
                currentBase64Image = event.target.result;
                imagePreview.src = currentBase64Image;
                imagePreviewContainer.style.display = 'block';
                if(chatInput.style.display === 'block') chatInput.focus();
            }};
            reader.readAsDataURL(file);
        }}
        function cancelImage() {{ currentBase64Image = null; imagePreview.src = ""; imagePreviewContainer.style.display = 'none'; document.getElementById('hidden-camera-input').value = ""; }}
        function toggleKeyboard() {{
            if (chatInput.style.display === 'none' || chatInput.style.display === '') {{
                chatInput.style.display = 'block'; micBtn.style.display = 'none'; sendTextBtn.style.display = 'flex'; chatInput.focus();
            }} else {{
                chatInput.style.display = 'none'; micBtn.style.display = 'flex'; sendTextBtn.style.display = 'none';
            }}
        }}

        async function sendMessage(textOverride = null, audioData = null) {{
            const text = textOverride !== null ? textOverride : chatInput.value.trim();
            if (!text && !currentBase64Image && !audioData) return; 
            
            let userHtml = '';
            if (audioData) {{
                userHtml = `<div style="display: flex; flex-direction: column; gap: 8px;">
                    <span style="font-size: 1rem; font-weight: bold;"><i class="bi bi-mic-fill text-danger me-2"></i> رسالة صوتية مسجلة</span>
                    <audio controls src="${{audioData}}" style="height: 40px; max-width: 250px; outline: none; border-radius: 10px;"></audio>
                </div>`;
            }} else {{
                userHtml = text;
            }}
            if (currentBase64Image) userHtml += (userHtml ? '<br>' : '') + `<img src="${{currentBase64Image}}">`;
            
            const uDiv = document.createElement('div'); uDiv.className = 'bubble user'; uDiv.innerHTML = userHtml; chatBox.appendChild(uDiv);
            
            // إضافة معرّف الجلسة هنا للـ Payload
            const payload = {{ message: text || "", image_data: currentBase64Image, audio_data: audioData, session_id: currentSessionUuid }};
            
            chatInput.value = ''; cancelImage();
            setTimeout(() => chatBox.scrollTop = chatBox.scrollHeight, 50);
            
            const aiDiv = document.createElement('div'); aiDiv.className = 'bubble ai text-warning'; aiDiv.innerHTML = 'الأسطى بيسمع ويفكر...'; chatBox.appendChild(aiDiv);

            let fullResponseText = "";

            try {{
                const response = await fetch('/api/kiosk_chat', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(payload) }});
                if(response.status === 429) {{ aiDiv.innerHTML = "<span class='text-danger'>راقب سرعتك يا هندسة! استنى شوية وحاول تاني.</span>"; return; }}
                const reader = response.body.getReader(); const decoder = new TextDecoder("utf-8"); aiDiv.innerHTML = ""; aiDiv.classList.remove('text-warning');

                while (true) {{
                    const {{ done, value }} = await reader.read(); if (done) break;
                    const lines = decoder.decode(value, {{ stream: true }}).split('\\n');
                    for (const line of lines) {{
                        if (line.startsWith('data: ')) {{
                            try {{
                                const data = JSON.parse(line.replace('data: ', '').trim());
                                
                                if (data.error === "NO_OPENAI_KEY_AUDIO") {{
                                    useNativeMic = true;
                                    aiDiv.innerHTML = `<span class="text-info fw-bold">⚠️ تم تبديل المايك للنظام الداخلي المجاني لعدم وجود مفتاح OpenAI. اضغط على المايك مرة تانية واتكلم براحتك!</span>`;
                                    return;
                                }}
                                
                                if (data.chunk) {{ 
                                    fullResponseText += data.chunk; 
                                    aiDiv.innerHTML = fullResponseText.replace(/\\n/g, '<br>'); 
                                    chatBox.scrollTop = chatBox.scrollHeight; 
                                }}
                                else if (data.done) {{
                                    if (!fullResponseText.trim()) {{
                                        aiDiv.innerHTML = "<span class='text-muted'>مفيش رد وصل، السيرفر فصل، حاول تاني يا هندسة.</span>";
                                        return;
                                    }}
                                    const safeText = data.full.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\\n/g, ' ');
                                    aiDiv.innerHTML = data.full.replace(/\\n/g, '<br>') + `<button class="speak-btn" onclick="speakText(this, '${{safeText}}')"><i class="bi bi-volume-up-fill"></i></button>`;
                                    speakText(aiDiv.querySelector('.speak-btn'), data.full);
                                    
                                    // إعادة تحميل الصفحة إن كانت هذه أول رسالة لكي يظهر اسم المحادثة الجديد
                                    if(document.querySelectorAll('.bubble').length <= 3) {{
                                        setTimeout(() => window.location.reload(), 2000);
                                    }}
                                }}
                                else if (data.error) {{ aiDiv.innerHTML = `<span class="text-danger fw-bold">${{data.error}}</span>`; }}
                            }} catch (e) {{}}
                        }}
                    }}
                }}
            }} catch (err) {{ aiDiv.innerHTML = "<span class='text-danger'>عطل في الشبكة. جرب تاني يا ريس.</span>"; }}
        }}
    </script>
    """
    return render_html_layout(content_html + content_js, "الأسطى", user)

class ChatRequest(BaseModel):
    message: str = Field("", max_length=2000)
    image_data: Optional[str] = Field(None, max_length=5_000_000)
    audio_data: Optional[str] = Field(None, max_length=10_000_000)
    session_id: str = Field(...)

class TTSRequest(BaseModel):
    text: str

@app.post("/api/tts")
@limiter.limit("5/minute")
async def generate_tts(request: Request, tts_req: TTSRequest, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401, detail="Unauthorized")
    openai_key = decrypt_val(user.tenant.openai_api_key)
    if not openai_key: raise HTTPException(status_code=400, detail="OpenAI Key Required.")
    try:
        response = openai.OpenAI(api_key=openai_key).audio.speech.create(model="tts-1", voice="onyx", input=tts_req.text)
        return Response(content=response.read(), media_type="audio/mpeg")
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_llm_response_stream(llm, messages): return llm.astream(messages)

TECHNICAL_KEYWORDS = ["ضاغط", "مجفف", "فلتر", "أويل", "بيلت", "عطل", "ضغط", "بارد", "حرارة", "زيت", "صيانة", "ماكينة", "موتور", "صوت", "مشكلة", "صورة", "الحل", "خربان", "بايظ", "مكسور"]
def is_technical_query(message: str) -> bool:
    if not message: return True
    return any(kw in message for kw in TECHNICAL_KEYWORDS)

# =====================================================================
# دالة المحادثة الاحترافية بعد دمج فلاتر الأخطاء المرنة والذكية 100%
# =====================================================================
@app.post("/api/kiosk_chat")
@limiter.limit("10/minute")
async def kiosk_chat_api(request: Request, chat_req: ChatRequest, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: 
        return StreamingResponse((f"data: {json.dumps({'error': 'يا هندسة، جلسة الدخول انتهت، يرجى إعادة تسجيل الدخول أولاً.'})}\n\n" for _ in range(1)), media_type="text/event-stream")
    
    tenant = user.tenant
    openai_key = decrypt_val(tenant.openai_api_key)
    google_key = decrypt_val(tenant.google_api_key)
    model_name = tenant.llm_model
    provider = tenant.llm_provider
    base_url = getattr(tenant, 'api_base_url', '')

    transcribed_message = chat_req.message

    if chat_req.audio_data:
        if not openai_key:
            return StreamingResponse((f"data: {json.dumps({'error': 'NO_OPENAI_KEY_AUDIO'})}\n\n" for _ in range(1)), media_type="text/event-stream")
        try:
            header, encoded = chat_req.audio_data.split(",", 1)
            audio_bytes = base64.b64decode(encoded)
            client = openai.OpenAI(api_key=openai_key)
            ext = ".webm"
            if "mp4" in header: ext = ".mp4"
            elif "mpeg" in header or "mp3" in header: ext = ".mp3"
            
            temp_audio_path = ""
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_audio:
                    temp_audio.write(audio_bytes)
                    temp_audio_path = temp_audio.name
                
                with open(temp_audio_path, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file, language="ar")
                    transcribed_message = transcript.text
            finally:
                if temp_audio_path and os.path.exists(temp_audio_path):
                    os.unlink(temp_audio_path)

        except openai.RateLimitError:
            return StreamingResponse((f"data: {json.dumps({'error': '⏳ الخادم مشغول جداً حالياً، اهدى شوية يا هندسة وجرب تسجل تاني.'})}\n\n" for _ in range(1)), media_type="text/event-stream")
        except openai.APIConnectionError:
            return StreamingResponse((f"data: {json.dumps({'error': '🌐 مشكلة في الاتصال بالإنترنت، تأكد من الشبكة وجرب تاني.'})}\n\n" for _ in range(1)), media_type="text/event-stream")
        except openai.AuthenticationError:
            return StreamingResponse((f"data: {json.dumps({'error': '❌ مفتاح OpenAI المستخدَم للصوت غير صحيح أو منتهي الصلاحية. راجع المفتاح في الإعدادات.'})}\n\n" for _ in range(1)), media_type="text/event-stream")
        except Exception:
            if not transcribed_message:
                return StreamingResponse((f"data: {json.dumps({'error': '🎙️ الصوت مكانش واضح بسبب ضوضاء الورشة، جرب تسجل تاني أو اكتب المشكلة الكيبورد.'})}\n\n" for _ in range(1)), media_type="text/event-stream")

    if not transcribed_message and not chat_req.image_data: transcribed_message = "بص على الصورة دي وقولي الحل إيه؟"

    # تحديث اسم المحادثة تلقائياً لو كانت جديدة
    current_session = (await db.execute(select(ChatSession).where(ChatSession.session_uuid == chat_req.session_id))).scalars().first()
    if current_session:
        if current_session.title == "محادثة جديدة":
            new_title = " ".join(transcribed_message.split()[:4])
            if not new_title: new_title = "محادثة صوتية"
            current_session.title = new_title
        current_session.updated_at = datetime.utcnow()
        await db.commit()

    rag_context = ""
    if is_technical_query(transcribed_message) and pc_client_instance and tenant.pinecone_index:
        try:
            embeddings = OpenAIEmbeddings(openai_api_key=openai_key) if openai_key else GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key) if google_key else None
            if embeddings:
                rag_context = "\n".join([d.page_content for d in PineconeVectorStore(index=pc_client_instance.Index(tenant.pinecone_index), embedding=embeddings, namespace=f"tenant_{tenant.id}").similarity_search(transcribed_message, k=2)])
        except Exception: rag_context = ""

    try:
        if provider == "openai":
            if not openai_key: raise ValueError("⚠️ مفتاح OpenAI مفقود! يرجى إدخاله في الإعدادات لتشغيل موديلات ChatGPT.")
            kwargs = {"model_name": model_name, "openai_api_key": openai_key, "temperature": 0.3}
            if base_url: kwargs["base_url"] = base_url
            llm = ChatOpenAI(**kwargs)
            
        elif provider == "anthropic":
            anthropic_key = decrypt_val(tenant.anthropic_api_key)
            if not anthropic_key: raise ValueError("⚠️ مفتاح Anthropic مفقود! يرجى إدخاله في الإعدادات لتشغيل موديلات Claude.")
            kwargs = {"model_name": model_name, "api_key": anthropic_key, "temperature": 0.3}
            if base_url: kwargs["base_url"] = base_url
            llm = ChatAnthropic(**kwargs)
            
        elif provider == "google":
            if not google_key: raise ValueError("⚠️ مفتاح Google Gemini مفقود! يرجى إدخاله في الإعدادات لتشغيل المساعد عبر جيميناي.")
            llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=google_key, temperature=0.3)
            
        elif provider == "custom":
            if not base_url: raise ValueError("⚠️ يجب إدخال الرابط المخصص (Base URL) للمزود الخارجي في الإعدادات.")
            kwargs = {"model_name": model_name, "openai_api_key": openai_key or "sk-custom", "temperature": 0.3, "base_url": base_url}
            llm = ChatOpenAI(**kwargs)
            
        else:
            raise ValueError("⚙️ مزود الخدمة المختار غير مدعوم في النظام حالياً.")
            
    except ValueError as ve: 
        return StreamingResponse((f"data: {json.dumps({'error': str(ve)})}\n\n" for _ in range(1)), media_type="text/event-stream")
    except Exception as e: 
        return StreamingResponse((f"data: {json.dumps({'error': f'حدث خطأ أثناء تهيئة الموديل: {str(e)}'})}\n\n" for _ in range(1)), media_type="text/event-stream")

    history = await get_chat_history(chat_req.session_id, db, limit=3)
    system_instruction = f"{tenant.workshop_prompt}\n\nتاريخ المحادثة السابقة:\n{history}\n\nمعلومات فنية من الكتالوجات:\n{rag_context}"
    messages = [SystemMessage(content=system_instruction), HumanMessage(content=[{"type": "text", "text": transcribed_message}] + ([{"type": "image_url", "image_url": {"url": chat_req.image_data}}] if chat_req.image_data else []))]
    await save_chat_history(chat_req.session_id, "Worker", f"🎙️ {transcribed_message}" if chat_req.audio_data else (transcribed_message or "[صورة]"), db, tenant.id)
    
    logger.info(f"USER_ACTION | user={user.username} | tenant={user.tenant_id} | action=chat | provider={provider} | model={model_name}")

    async def event_generator() -> AsyncGenerator[str, None]:
        full_response = ""
        try:
            async for chunk in (await get_llm_response_stream(llm, messages)):
                if chunk.content:
                    full_response += chunk.content
                    yield f"data: {json.dumps({'chunk': chunk.content})}\n\n"
            await save_chat_history(chat_req.session_id, "AI", full_response, db, tenant.id)
            yield f"data: {json.dumps({'done': True, 'full': full_response})}\n\n"
            
        except Exception as e:
            err_str = str(e)
            yield f"data: {json.dumps({'error': f'❌ خطأ من الخادم ({model_name}): {err_str}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# =====================================================================
# واجهة Streamlit السحرية (تم دمج واجهة الكشك الأصلية هنا بالكامل)
# =====================================================================

API_BASE = "http://127.0.0.1:8000"

def is_server_running(port=8000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

@st.cache_resource
def start_backend_server():
    if not is_server_running(8000):
        def run_server():
            try:
                config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
                server = uvicorn.Server(config)
                # ✅ الحل السحري: منع uvicorn من التلاعب بإشارات النظام لتفادي الانهيار في الخيوط الفرعية
                server.install_signal_handlers = lambda: None
                server.run()
            except Exception as e:
                logger.error(f"Failed to start backend server: {e}")

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        for _ in range(15):
            if is_server_running(8000):
                break
            time.sleep(0.5)
    return True

def login(username, password):
    try:
        response = requests.post(f"{API_BASE}/api/streamlit_login", json={"username": username, "password": password})
        if response.status_code == 200: return response.json()
    except Exception as e:
        st.error(f"خطأ في الاتصال بالسيرفر: {e}")
    return None

def run_streamlit_ui():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if not get_script_run_ctx():
            return  # تخطي تشغيل الواجهة إذا كنا في الـ MainThread لمنع رسائل الخطأ وإيقاف السيرفر
    except ImportError:
        pass

    st.set_page_config(page_title="مساعد الورشة الذكي", page_icon="🔧", layout="wide", initial_sidebar_state="expanded")
    
    # تشغيل الخادم في الخلفية بأمان
    start_backend_server()

    # تنسيقات الواجهة لتشبه واجهة الكشك الأصلية
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;900&display=swap');
        html, body, [class*="css"] { font-family: 'Cairo', sans-serif; direction: rtl; text-align: right; }
        .stChatMessage { border-radius: 15px !important; padding: 15px !important; margin-bottom: 15px !important; font-size: 1.1rem; }
        div[data-testid="stChatMessage"]:nth-child(even) { background-color: rgba(255, 152, 0, 0.1); border-right: 4px solid #FF9800; }
        div[data-testid="stChatMessage"]:nth-child(odd) { background-color: rgba(30, 30, 30, 0.8); border-right: 4px solid #2196F3; }
        /* إخفاء الهيدر الافتراضي لإعطاء شكل التطبيق المستقل */
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

    if "token" not in st.session_state: st.session_state.token = None
    if "user" not in st.session_state: st.session_state.user = None

    if not st.session_state.token:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("<h2 style='text-align: center; color: #FF9800;'><br>🔧 دخول الورشة</h2>", unsafe_allow_html=True)
            username = st.text_input("اسم المستخدم", placeholder="worker أو admin")
            password = st.text_input("كلمة السر", type="password")
            if st.button("دخول المساعد 🚀", use_container_width=True):
                if username and password:
                    result = login(username, password)
                    if result:
                        st.session_state.token = result["access_token"]
                        st.session_state.user = result["user"]
                        st.rerun()
                    else:
                        st.error("❌ بيانات خطأ، جرب تاني يا هندسة")
                else:
                    st.warning("⚠️ أدخل اسم المستخدم وكلمة السر")
    else:
        user = st.session_state.user
        headers = {"Authorization": f"Bearer {st.session_state.token}"}
        
        with st.sidebar:
            st.markdown(f"### 👷 أهلاً يا هندسة: <span style='color:#FF9800;'>{user['username']}</span>", unsafe_allow_html=True)
            st.markdown("---")
            if user["role"] == "admin":
                page = st.radio("القائمة الرئيسية", ["💬 واجهة العمال (Kiosk)", "🔥 مراقبة Firebase", "⚙️ إعدادات النظام"])
            else:
                page = "💬 واجهة العمال (Kiosk)"
                st.info("أنت مسجل كـ 'عامل'. لديك صلاحية المحادثة فقط.")
                
            st.markdown("---")
            if st.button("🚪 تسجيل خروج", use_container_width=True):
                st.session_state.token = None
                st.session_state.user = None
                if "messages" in st.session_state: st.session_state.messages = []
                st.rerun()

        if page == "💬 واجهة العمال (Kiosk)":
            st.markdown("## 🎙️ مساعد الورشة الذكي (الأسطى)")
            st.caption("الأسطى معاك، اكتب مشكلتك أو ارفع صورة العطل أو سجل صوتك بالضغط على (إرفاق وسائط).")
            
            if "messages" not in st.session_state: st.session_state.messages = []
            
            # عرض الرسائل السابقة مع الوسائط
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    if "audio" in msg and msg["audio"]:
                        st.audio(msg["audio"])
                    if "image" in msg and msg["image"]:
                        st.image(msg["image"], width=300)

            # منطقة الإدخال الذكية
            prompt = st.chat_input("اكتب سؤالك للأسطى هنا...")
            
            with st.expander("📸 إرفاق وسائط (صورة أو تسجيل صوتي)", expanded=False):
                with st.form("media_form", clear_on_submit=True):
                    st.info("💡 ملاحظة: يجب إعطاء المتصفح صلاحية استخدام الميكروفون والكاميرا.")
                    c1, c2 = st.columns(2)
                    with c1: audio_val = st.audio_input("🎙️ سجل سؤالك")
                    with c2: cam_val = st.camera_input("📸 صور العطل")
                    text_val = st.text_input("💬 تعليق إضافي مع الصورة/الصوت (اختياري)")
                    submit_media = st.form_submit_button("إرسال الوسائط للأسطى 🚀", use_container_width=True)

            # منطق المعالجة الشامل لدمج الواجهة القديمة
            trigger = False
            final_text = ""
            final_audio = None
            final_cam = None

            if prompt:
                trigger = True
                final_text = prompt
            elif submit_media and (audio_val or cam_val or text_val):
                trigger = True
                final_text = text_val
                final_audio = audio_val
                final_cam = cam_val

            if trigger:
                # تحضير وتشفير البيانات كما يحدث في واجهة الـ Frontend
                aud_b64 = None
                if final_audio:
                    aud_b64 = "data:audio/webm;base64," + base64.b64encode(final_audio.read()).decode()
                
                img_b64 = None
                if final_cam:
                    img_b64 = "data:image/png;base64," + base64.b64encode(final_cam.read()).decode()

                display_text = final_text if final_text else "رسالة وسائط 📸/🎙️"
                st.session_state.messages.append({"role": "user", "content": display_text, "image": final_cam, "audio": final_audio})
                
                with st.chat_message("user"):
                    st.write(display_text)
                    if final_audio: st.audio(final_audio)
                    if final_cam: st.image(final_cam, width=300)

                with st.chat_message("assistant"):
                    response_placeholder = st.empty()
                    audio_placeholder = st.empty()
                    with st.spinner("الأسطى بيفكر وبيجهز الرد..."):
                        full_response = ""
                        payload = {
                            "message": final_text,
                            "image_data": img_b64,
                            "audio_data": aud_b64,
                            "session_id": "streamlit_kiosk_session"
                        }
                        try:
                            # استخدام الـ Streaming API الأصلية بتاعت الـ Kiosk لضمان أقصى سرعة وقوة
                            response = requests.post(f"{API_BASE}/api/kiosk_chat", json=payload, headers=headers, stream=True)
                            if response.status_code == 200:
                                for line in response.iter_lines():
                                    if line:
                                        decoded = line.decode('utf-8').strip()
                                        if decoded.startswith("data: "):
                                            data_str = decoded[6:]
                                            try:
                                                data = json.loads(data_str)
                                                if "chunk" in data:
                                                    full_response += data["chunk"]
                                                    response_placeholder.markdown(full_response + " ▌")
                                                elif "done" in data:
                                                    full_response = data["full"]
                                                    response_placeholder.markdown(full_response)
                                                elif "error" in data:
                                                    st.error(data["error"])
                                            except json.JSONDecodeError: pass
                                
                                # توليد رد صوتي TTS آلياً إذا كان هناك رد
                                if full_response:
                                    try:
                                        tts_res = requests.post(f"{API_BASE}/api/tts", json={"text": full_response}, headers=headers)
                                        if tts_res.status_code == 200:
                                            audio_placeholder.audio(tts_res.content, format="audio/mpeg", autoplay=True)
                                            st.session_state.messages.append({"role": "assistant", "content": full_response, "audio": tts_res.content})
                                        else:
                                            st.session_state.messages.append({"role": "assistant", "content": full_response})
                                    except Exception as tts_e:
                                        st.session_state.messages.append({"role": "assistant", "content": full_response})
                            else:
                                st.error(f"خطأ من الخادم: {response.status_code}")
                        except Exception as e:
                            st.error(f"فشل الاتصال بخادم الذكاء الاصطناعي: {e}")

        elif page == "🔥 مراقبة Firebase":
            st.markdown("## 🔥 مراقبة استخدام Firebase السحابي")
            if st.button("🔄 تحديث البيانات"): pass 
            try:
                r = requests.get(f"{API_BASE}/api/firebase_usage", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("القراءات اليوم", f"{data['reads']:,}", f"من {data['reads_limit']:,} (المجاني)")
                        st.progress(min(data["reads_percent"] / 100, 1.0))
                    with col2:
                        st.metric("الكتابات اليوم", f"{data['writes']:,}", f"من {data['writes_limit']:,} (المجاني)")
                        st.progress(min(data["writes_percent"] / 100, 1.0))
                else:
                    st.error("السيرفر لا يستطيع جلب بيانات الاستخدام.")
            except Exception as e:
                st.error(f"خطأ: {e}")

        elif page == "⚙️ إعدادات النظام":
            st.markdown("## ⚙️ إعدادات الورشة المتقدمة")
            tab1, tab2, tab3 = st.tabs(["🤖 نماذج الذكاء", "🔥 Firebase", "🗄️ قاعدة البيانات"])
            with tab1:
                st.markdown("### مفاتيح ونماذج الـ LLM")
                provider = st.selectbox("المزود", ["google", "openai", "anthropic", "custom"])
                model = st.text_input("اسم الموديل", placeholder="gemini-1.5-flash")
                c1, c2 = st.columns(2)
                with c1:
                    openai_key = st.text_input("مفتاح OpenAI", type="password")
                    google_key = st.text_input("مفتاح Google", type="password")
                with c2:
                    anthropic_key = st.text_input("مفتاح Anthropic", type="password")
                    base_url = st.text_input("رابط الـ API المخصص (Base URL)")
                if st.button("💾 حفظ المفاتيح", use_container_width=True):
                    r = requests.post(f"{API_BASE}/api/settings/save_llm_json", json={
                        "llm_provider": provider, "llm_model": model, "api_base_url": base_url,
                        "openai_key": openai_key, "anthropic_key": anthropic_key, "google_key": google_key
                    }, headers=headers)
                    if r.status_code == 200: st.success("✅ تم الحفظ بنجاح!")
                    else: st.error("❌ فشل الحفظ")
            with tab2:
                st.markdown("### 🔥 ربط Firebase Firestore")
                firebase_json = st.text_area("الصق محتوى ملف JSON هنا:", height=200)
                if st.button("🔗 حفظ وربط Firebase", use_container_width=True):
                    if firebase_json:
                        r = requests.post(f"{API_BASE}/api/settings/save_firebase", json={"firebase_credentials": firebase_json}, headers=headers)
                        if r.status_code == 200: st.success("✅ تم ربط Firebase!")
                        else: st.error("❌ حدث خطأ، تأكد من صحة النص.")
            with tab3:
                st.markdown("### 🗄️ ربط قاعدة بيانات سحابية (PostgreSQL / MySQL)")
                db_url = st.text_input("رابط قاعدة البيانات (Database URL)", type="password")
                if st.button("🔗 حفظ قاعدة البيانات", use_container_width=True):
                    if db_url:
                        r = requests.post(f"{API_BASE}/api/settings/save_database", json={"database_url": db_url}, headers=headers)
                        if r.status_code == 200: st.success("✅ تم الحفظ! سيعمل السيرفر بالرابط الجديد بعد إعادة التشغيل.")
                        else: st.error("❌ فشل الحفظ")

# تشغيل واجهة Streamlit
run_streamlit_ui()
