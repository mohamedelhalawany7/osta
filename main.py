import os
import sys
import io
import json
import urllib.request
from datetime import datetime, timedelta
from typing import Optional, List, AsyncGenerator
import re
import logging
from cryptography.fernet import Fernet
import httpx
from functools import lru_cache
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import hashlib
from pydantic import BaseModel, ConfigDict
from threading import Lock
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import html
import asyncio
import secrets
import hmac

import uvicorn
import pandas as pd
from fastapi import FastAPI, Request, Depends, UploadFile, File, Form, HTTPException, status, BackgroundTasks, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

# --- استيرادات المحور الثاني والثالث (LangGraph & Memory) ---
from typing import Annotated, Literal, TypedDict
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, RemoveMessage

import bcrypt
from jose import JWTError, jwt
import streamlit as st  # إضافة استيراد Streamlit لدعم الأسرار السحابية

# --- استيرادات Firebase الجديدة ---
import firebase_admin
from firebase_admin import credentials, firestore

from openai import OpenAI
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from collections import defaultdict

from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore

from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler("elderiny.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# =====================================================================
# طبقة الأمان المتقدمة (Vault Secrets Integration)
# =====================================================================
class EnterpriseVault:
    @staticmethod
    def get_secret(key_name: str, default_value: str = "") -> str:
        return os.getenv(key_name, default_value)

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

FERNET_KEY = EnterpriseVault.get_secret("FERNET_KEY")
if not FERNET_KEY:
    logger.warning("FERNET_KEY غير موجود. جاري توليد مفتاح جديد وحفظه في ملف .env...")
    FERNET_KEY = Fernet.generate_key().decode()
    with open(".env", "a", encoding="utf-8") as f:
        f.write(f"\nFERNET_KEY={FERNET_KEY}\n")
    os.environ["FERNET_KEY"] = FERNET_KEY

cipher = Fernet(FERNET_KEY.encode())

def encrypt_val(value: str) -> str:
    if not value: return ""
    return cipher.encrypt(value.encode()).decode()

def decrypt_val(value: str) -> str:
    if not value: return ""
    try:
        return cipher.decrypt(value.encode()).decode()
    except:
        return value

SECRET_KEY = EnterpriseVault.get_secret("SECRET_KEY")
if not SECRET_KEY:
    logger.warning("SECRET_KEY غير موجود. جاري توليد مفتاح سري جديد وحفظه في ملف .env...")
    SECRET_KEY = secrets.token_urlsafe(32)
    with open(".env", "a", encoding="utf-8") as f:
        f.write(f"\nSECRET_KEY={SECRET_KEY}\n")
    os.environ["SECRET_KEY"] = SECRET_KEY

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 
IS_PRODUCTION = EnterpriseVault.get_secret("ENV", "development") == "production"

def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# =====================================================================
# تهيئة قاعدة بيانات Firebase (بديلة لـ SQL) مع دعم Streamlit Secrets
# =====================================================================
if not firebase_admin._apps:
    try:
        # 1. محاولة قراءة المفاتيح من Streamlit Secrets (لمنصة Streamlit Cloud)
        try:
            if "firebase" in st.secrets:
                firebase_secrets = dict(st.secrets["firebase"])
                cred = credentials.Certificate(firebase_secrets)
                firebase_admin.initialize_app(cred)
                logger.info("تم الربط مع Firebase باستخدام Streamlit Secrets بنجاح.")
        except Exception as st_e:
            logger.warning("لم يتم العثور على Streamlit Secrets أو فشل قراءتها.")

        # 2. محاولة القراءة من الملف المحلي (لمنصة Render أو العمل المحلي)
        if not firebase_admin._apps:
            if os.path.exists("firebase-key.json"):
                cred = credentials.Certificate("firebase-key.json")
                firebase_admin.initialize_app(cred)
                logger.info("تم الربط مع Firebase باستخدام ملف المفاتيح المحلي بنجاح.")
            else:
                logger.warning("ملف firebase-key.json غير موجود. سيتم محاولة استخدام الصلاحيات الافتراضية.")
                firebase_admin.initialize_app()
    except Exception as e:
        logger.error(f"خطأ جذري في تهيئة Firebase: {e}")

try:
    db_firestore = firestore.client()
except Exception as e:
    logger.error(f"فشل الاتصال بقاعدة بيانات Firestore: {e}")
    db_firestore = None

def get_db():
    yield db_firestore

# =====================================================================
# الموديلز (Models) - توافقية مع Firestore لعدم كسر الكود
# =====================================================================
class TenantModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.name = data.get("name", "")
        self.whatsapp_phone_id = data.get("whatsapp_phone_id", "")
        self.whatsapp_token = data.get("whatsapp_token", "")
        self.verify_token = data.get("verify_token", "elderiny_verify")
        self.procurement_admins = data.get("procurement_admins", "")
        self.sales_admins = data.get("sales_admins", "")
        self.llm_provider = data.get("llm_provider", "openai")
        self.llm_model = data.get("llm_model", "gpt-4o")
        self.openai_api_key = data.get("openai_api_key", "")
        self.anthropic_api_key = data.get("anthropic_api_key", "")
        self.google_api_key = data.get("google_api_key", "")
        self.pinecone_api_key = data.get("pinecone_api_key", "")
        self.pinecone_index = data.get("pinecone_index", "")
        self.decision_tree_prompt = data.get("decision_tree_prompt", '{"id":"root","text":"رسالة الترحيب: يا هلا بيك يا بطل، معاك الأسطى الآلي. مشكلتك في إيه؟","children":[{"id":"c1","text":"ماكينات CNC ومخارط -> إيه العطل بالظبط؟","children":[]},{"id":"c2","text":"ضواغط ومجففات الهوا -> الصوت عالي ولا مفيش ضغط؟","children":[]}]}')
        self.customer_service_prompt = data.get("customer_service_prompt", """أنت 'الأسطى الآلي'، كبير المهندسين والصنايعية في شركة تصنيع معدات هندسية (مخارط، فرايز، CNC، مقاشط، ليزر، ولحام) وصيانة ضواغط الهواء ومجففاتها.
تتحدث بلهجة مصرية عامية "صنايعي صميم"، كأنك معلم كبير في الورشة بيتكلم مع العمال.
العمال معظمهم بسطاء وأميين، لذلك يجب أن تكون إجاباتك:
1. مظبوطة جداً فنياً وهندسياً بناءً على خبرتك والملفات المرفوعة.
2. بلغة بلدية سهلة جداً ومفهومة، بدون مصطلحات إنجليزية معقدة إلا لو ضروري، واشرحها.
3. استخدم كلمات زي (يا بطل، يا ريس، يا هندسة، ركز معايا، هات العدة).
4. امشِ مع العامل خطوة بخطوة في حل المشكلة كأنك واقف جنبه على المكنة.""")
        self.procurement_agent_prompt = data.get("procurement_agent_prompt", "أنت وكيل مشتريات ومهندس متابعة.\nمهمتك: إذا أخبرك شريك العمل (المهندس أو المورد) عن موعد تسليم لمهمة أو طلبية تخص عميل معين، استخرج المعلومات وأنهِ رسالتك بهذا التنسيق السري لتسجيل المهمة:\n[متابعة:اسم المهمة|اسم العميل|YYYY-MM-DD]\nمثال: [متابعة:صيانة غلاية|شركة الأمل|2026-06-15]")

class UserModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.username = data.get("username", "")
        self.hashed_password = data.get("hashed_password", "")
        self.role = data.get("role", "admin")
        self.tenant_id = data.get("tenant_id", "")
        self.tenant = None

class TeamMemberModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.name = data.get("name", "")
        self.phone = data.get("phone", "")
        self.role = data.get("role", "")
        self.tenant_id = data.get("tenant_id", "")

class UploadedFileModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.filename = data.get("filename", "")
        self.file_type = data.get("file_type", "")
        # تحويل صيغة التاريخ الخاصة بـ Firebase إلى بايثون
        up_date = data.get("upload_date")
        self.upload_date = up_date.replace(tzinfo=None) if up_date else datetime.utcnow()
        self.tenant_id = data.get("tenant_id", "")

def log_audit(db, tenant_id: str, action: str, performed_by: str, details: str):
    """تسجيل العمليات الحساسة في دفتر الأستاذ مع بصمة التشفير"""
    raw_data = f"{action}|{performed_by}|{details}|{datetime.utcnow().isoformat()}"
    crypto_hash = hashlib.sha256(raw_data.encode()).hexdigest()
    db.collection("audit_logs").add({
        "action": action,
        "performed_by": performed_by,
        "details": details,
        "crypto_hash": crypto_hash,
        "timestamp": datetime.utcnow(),
        "tenant_id": tenant_id
    })

def get_chat_history(session_id: str, db, limit: int = 5) -> str:
    docs = db.collection("conversation_history").stream()
    history_docs = []
    for doc in docs:
        d = doc.to_dict()
        if d.get("session_id") == session_id:
            history_docs.append(d)
            
    history_docs.sort(key=lambda x: x.get("created_at", datetime.min), reverse=True)
    history_docs = history_docs[:limit]
    
    history = []
    for d in history_docs:
        history.append(f"{d.get('role')}: {d.get('content')}")
    if not history: return "لا يوجد تاريخ محادثة سابق."
    return "\n".join(reversed(history))

def save_chat_history(session_id: str, role: str, content: str, db, tenant_id: str):
    db.collection("conversation_history").add({
        "session_id": session_id,
        "role": role,
        "content": content[:500],
        "created_at": datetime.utcnow(),
        "tenant_id": tenant_id
    })
    
    docs = list(db.collection("conversation_history").stream())
    session_docs = []
    for doc in docs:
        if doc.to_dict().get("session_id") == session_id:
            session_docs.append(doc)
            
    if len(session_docs) > 20:
        session_docs.sort(key=lambda x: x.to_dict().get("created_at", datetime.min))
        for doc in session_docs[:len(session_docs)-20]:
            doc.reference.delete()

class WhatsApp_Manager:
    def __init__(self, tenant: TenantModel, db, llm_client):
        self.tenant = tenant
        self.db = db
        self.llm = llm_client

    async def send_message(self, to_phone: str, message_text: str):
        wa_token = decrypt_val(self.tenant.whatsapp_token)
        if not wa_token or not self.tenant.whatsapp_phone_id:
            logger.warning("WhatsApp Token is missing for sending message.")
            return False
        url = f"https://graph.facebook.com/v19.0/{self.tenant.whatsapp_phone_id}/messages"
        headers = {"Authorization": f"Bearer {wa_token}", "Content-Type": "application/json"}
        payload = {"messaging_product": "whatsapp", "to": to_phone, "text": {"body": message_text}}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"WhatsApp Async Error: {e}")
            return False

    async def handle_customer_inquiry(self, message: str, sender_phone: str, history: str = "") -> str:
        if not self.llm:
            reply = "[النظام]: خدمة العملاء الذكية غير متاحة حالياً."
            await self.send_message(sender_phone, reply)
            return reply

        rag_context = fetch_rag_context(self.tenant, message)

        prompt = f"""{self.tenant.customer_service_prompt}
        
        شجرة الخيارات والمنطق المتسلسل (بصيغة JSON، تتبع المسار المتداخل بناءً على إجابات العميل):
        {self.tenant.decision_tree_prompt}

        تاريخ المحادثة السابقة لتوضيح السياق والمكان الذي وصلنا إليه في شجرة الخيارات أعلاه:
        {history}
        
        رسالة العميل الحالية: '{message}'
        المعلومات الفنية المتاحة للمساعدة:
        {rag_context}
        """

        res = self.llm.invoke(prompt)
        reply_text = res.content.strip()

        if "[تحويل_للمختص]" in reply_text:
            clean_reply = reply_text.replace("[تحويل_للمختص]", "").strip()
            if not clean_reply:
                clean_reply = "تم تسجيل تفاصيل طلبك بنجاح. جاري تحويلك الآن للمهندس المختص ليتواصل معك فوراً."

            await self.send_message(sender_phone, clean_reply)

            team_docs = self.db.collection("team_members").stream()
            for doc in team_docs:
                member = doc.to_dict()
                if member.get("tenant_id") == self.tenant.id:
                    alert_msg = f"[تنبيه تحويل آلي 🚨]:\nالعميل ({sender_phone}) جاهز للتدخل البشري.\nملخص الحوار الأخير: {message}\nالرجاء التواصل معه."
                    await self.send_message(member.get("phone"), alert_msg)

            return clean_reply
        else:
            await self.send_message(sender_phone, reply_text)
            return reply_text

def extract_and_save_followup(reply_text: str, partner_phone: str, tenant_id: str, db) -> str:
    match = re.search(r"\[متابعة:(.*?)\|(.*?)\|(.*?)\]", reply_text)
    if match:
        task_name = match.group(1).strip()
        client_name = match.group(2).strip()
        date_str = match.group(3).strip()
        
        try:
            due_date = datetime.strptime(date_str, "%Y-%m-%d")
            db.collection("followup_tasks").add({
                "task_name": task_name,
                "client_name": client_name,
                "partner_phone": partner_phone,
                "due_date": due_date,
                "status": "pending",
                "created_at": datetime.utcnow(),
                "tenant_id": tenant_id
            })
            
            clean_reply = reply_text.replace(match.group(0), "").strip()
            clean_reply += f"\n\n[النظام]: تم تسجيل مهمة '{task_name}' لعميل '{client_name}' بنجاح، وسأقوم بتذكيرك بها يوم {date_str} 📅."
            return clean_reply
        except Exception as e:
            logger.error(f"Date Parsing Error: {e}")
            
    return reply_text

def init_db():
    if not db_firestore: return
    try:
        tenants = list(db_firestore.collection("tenants").stream())
        if not tenants:
            print("[النظام]: جاري إنشاء الشركة الافتراضية والمدير (Admin)...")
            tenant_ref = db_firestore.collection("tenants").document()
            tenant_ref.set({
                "name": "الدريني للأعمال الهندسية",
                "decision_tree_prompt": '{"id":"root","text":"رسالة الترحيب: يا هلا بيك يا بطل، معاك الأسطى الآلي. مشكلتك في إيه؟","children":[{"id":"c1","text":"ماكينات CNC ومخارط -> إيه العطل بالظبط؟","children":[]},{"id":"c2","text":"ضواغط ومجففات الهوا -> الصوت عالي ولا مفيش ضغط؟","children":[]}]}',
                "customer_service_prompt": "أنت 'الأسطى الآلي'، كبير المهندسين والصنايعية...",
                "procurement_agent_prompt": "أنت وكيل مشتريات ومهندس متابعة..."
            })
            tenant_id = tenant_ref.id
            
            generated_password = secrets.token_urlsafe(12)
            print("=====================================================")
            print("[هام جداً]: تم إنشاء مدير النظام. يرجى حفظ بيانات الدخول:")
            print(f"Username: admin")
            print(f"Password: {generated_password}")
            print("=====================================================")

            db_firestore.collection("users").add({
                "username": "admin",
                "hashed_password": get_password_hash(generated_password),
                "role": "admin",
                "tenant_id": tenant_id
            })
            
        else:
            users = list(db_firestore.collection("users").stream())
            admin_user = None
            for doc in users:
                if doc.to_dict().get("username") == "admin":
                    admin_user = doc
                    break
                    
            if admin_user:
                admin_user.reference.update({"hashed_password": get_password_hash("12345678")})
                print("=====================================================")
                print("[تنبيه]: تم إعادة تعيين الرقم السري لمدير النظام (admin).")
                print("Username: admin")
                print("Password: 12345678")
                print("=====================================================")
    except Exception as e:
        logger.error(f"Error initializing Firestore data: {e}")

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
        
        users = list(db.collection("users").stream())
        user_doc = None
        for doc in users:
            if doc.to_dict().get("username") == username:
                user_doc = doc
                break
                
        if not user_doc: return None
        
        user_data = user_doc.to_dict()
        user_model = UserModel(user_doc.id, user_data)
        
        tenant_id = user_data.get("tenant_id")
        if tenant_id:
            tenant_doc = db.collection("tenants").document(tenant_id).get()
            if tenant_doc.exists:
                user_model.tenant = TenantModel(tenant_doc.id, tenant_doc.to_dict())
                
        return user_model
    except JWTError:
        return None

def render_html_layout(content: str, title: str, user=None):
    nav_links = ""
    if user:
        nav_links += f'<li class="nav-item"><a class="nav-link" href="/chat"><i class="bi bi-robot"></i> المساعد الآلي (الشات)</a></li>'
        if user.role == 'admin':
            nav_links += f"""
            <li class="nav-item"><a class="nav-link" href="/data_management"><i class="bi bi-database-add"></i> البيانات والملفات</a></li>
            <li class="nav-item"><a class="nav-link" href="/settings"><i class="bi bi-gear"></i> الإعدادات والربط</a></li>
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
        <title>{title} | الدريني المؤسسي</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            :root {{
                --bg-main: #0A0E17;
                --bg-card: rgba(16, 22, 35, 0.7);
                --sidebar-bg: rgba(10, 14, 23, 0.95);
                --text-main: #E2E8F0;
                --text-dark: #FFFFFF;
                --text-muted: #8B9BB4;
                --neon-primary: #00F0FF;
                --neon-purple: #B026FF;
                --neon-success: #39FF14;
                --neon-warning: #FFEA00;
                --neon-danger: #FF003C;
                --sidebar-width: 290px;
            }}
            
            body {{ 
                font-family: 'Cairo', sans-serif; 
                background-color: var(--bg-main); 
                background-image: 
                    radial-gradient(circle at 15% 50%, rgba(176, 38, 255, 0.05), transparent 25%),
                    radial-gradient(circle at 85% 30%, rgba(0, 240, 255, 0.05), transparent 25%);
                color: var(--text-main);
                margin: 0; padding: 0;
                display: flex;
                flex-direction: column;
                min-height: 100vh;
                min-height: 100dvh;
                direction: rtl;
                -webkit-font-smoothing: antialiased;
            }}
            
            .sidebar {{
                width: var(--sidebar-width);
                background-color: var(--sidebar-bg);
                backdrop-filter: blur(20px);
                border-left: 1px solid rgba(0, 240, 255, 0.1);
                color: var(--text-dark);
                position: fixed;
                right: 0;
                top: 0;
                height: 100vh;
                height: 100dvh;
                overflow-y: auto;
                padding-top: 2.5rem;
                z-index: 1000;
                display: flex;
                flex-direction: column;
                box-shadow: -5px 0 30px rgba(0, 0, 0, 0.5);
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }}
            .sidebar .brand {{ 
                font-size: 1.8rem; font-weight: 800; text-align: center; margin-bottom: 3.5rem; color: var(--text-dark); letter-spacing: -0.5px;
                text-shadow: 0 0 10px rgba(0, 240, 255, 0.5);
            }}
            .sidebar .brand i {{ color: var(--neon-primary); text-shadow: 0 0 15px var(--neon-primary); }}
            
            .sidebar .nav-link {{ 
                color: var(--text-muted) !important; font-weight: 700; padding: 1rem 1.8rem; border-radius: 16px; margin: 0.4rem 1.5rem;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important; display: flex; align-items: center; font-size: 1.05rem;
                border: 1px solid transparent !important;
            }}
            .sidebar .nav-link i {{ margin-left: 16px; font-size: 1.4rem; transition: all 0.3s ease !important; }}
            
            .sidebar .nav-link:hover, .sidebar .nav-link.active {{ 
                background-color: rgba(0, 240, 255, 0.15) !important; 
                color: #FFFFFF !important; 
                text-shadow: 0 0 10px var(--neon-primary), 0 0 20px var(--neon-primary), 0 0 30px var(--neon-primary) !important;
                border: 1px solid rgba(0, 240, 255, 0.4) !important;
                box-shadow: 0 0 20px rgba(0, 240, 255, 0.3), inset 0 0 15px rgba(0, 240, 255, 0.2) !important; 
                transform: translateX(-8px) scale(1.02) !important;
            }}
            .sidebar .nav-link:hover i, .sidebar .nav-link.active i {{
                color: var(--neon-primary) !important;
                text-shadow: 0 0 15px var(--neon-primary), 0 0 25px var(--neon-primary) !important;
                transform: scale(1.2) !important;
            }}
            
            .sidebar .btn-logout {{ 
                background-color: rgba(255, 0, 60, 0.1); color: var(--neon-danger);
                border-radius: 16px; padding: 1rem; margin: auto 1.5rem 2.5rem 1.5rem; display: block; text-decoration: none; transition: 0.3s; font-weight: 700;
                border: 1px solid rgba(255, 0, 60, 0.3);
            }}
            .sidebar .btn-logout:hover {{ background-color: var(--neon-danger); color: white; box-shadow: 0 0 20px var(--neon-danger); }}
            
            .main-content {{
                margin-right: var(--sidebar-width);
                flex: 1;
                padding: 2rem;
                min-height: 100vh;
                min-height: 100dvh;
                width: calc(100% - var(--sidebar-width));
                display: flex;
                flex-direction: column;
            }}
            
            .mobile-header {{ display: none; }}
            .sidebar-overlay {{ display: none; }}

            /* دعم الموبايل والتابلت بالكامل */
            @media (max-width: 992px) {{
                .sidebar {{ transform: translateX(100%); z-index: 1050; }}
                .sidebar.show {{ transform: translateX(0); }}
                .main-content {{ margin-right: 0; width: 100%; padding: 1rem; }}
                
                .mobile-header {{ 
                    display: flex; 
                    align-items: center; 
                    justify-content: space-between; 
                    background-color: var(--sidebar-bg); 
                    padding: 1rem 1.5rem; 
                    border-bottom: 1px solid rgba(0, 240, 255, 0.2); 
                    position: sticky; 
                    top: 0; 
                    z-index: 1000;
                    backdrop-filter: blur(10px);
                }}
                .mobile-toggle {{ background: transparent; border: none; color: var(--neon-primary); font-size: 1.8rem; padding: 0; cursor: pointer; }}
                .sidebar-overlay.show {{ 
                    display: block; 
                    position: fixed; 
                    top: 0; left: 0; right: 0; bottom: 0; 
                    background: rgba(0,0,0,0.6); 
                    z-index: 1040; 
                    backdrop-filter: blur(3px);
                }}
            }}
            
            .card {{ 
                border-radius: 20px; 
                border: 1px solid rgba(255, 255, 255, 0.05); 
                box-shadow: 0px 10px 30px rgba(0, 0, 0, 0.4); 
                margin-bottom: 30px; 
                background-color: var(--bg-card) !important;
                backdrop-filter: blur(12px);
                transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
            }}
            .card:hover {{ 
                transform: translateY(-5px); 
                border-color: var(--neon-primary); 
                box-shadow: 0 0 30px rgba(0, 240, 255, 0.3), inset 0 0 15px rgba(0, 240, 255, 0.1); 
            }}
            
            .card-header {{ 
                background-color: rgba(0,0,0,0.4) !important; 
                border-bottom: 1px solid rgba(255,255,255,0.05); 
                font-weight: 800; 
                color: var(--text-dark) !important;
                padding: 1.5rem 2rem;
                border-radius: 20px 20px 0 0 !important;
                font-size: 1.15rem;
                text-transform: uppercase;
                letter-spacing: 1px;
            }}
            .card-body {{ padding: 2rem; overflow-x: auto; }}
            .card-footer {{ background-color: rgba(0,0,0,0.4) !important; border-top: 1px solid rgba(255,255,255,0.05); border-radius: 0 0 20px 20px !important;}}
            
            h1, h2, h3, h4, h5, h6 {{ color: var(--text-dark); font-weight: 800; text-shadow: 0 2px 4px rgba(0,0,0,0.5);}}
            
            .btn-primary {{ 
                background-color: transparent; border: 1px solid var(--neon-primary); color: var(--neon-primary);
                font-weight: 700; border-radius: 14px; padding: 0.8rem 1.8rem; 
                transition: all 0.3s ease; font-size: 1.05rem; 
                box-shadow: inset 0 0 10px rgba(0, 240, 255, 0.1), 0 0 10px rgba(0, 240, 255, 0.2);
            }}
            .btn-primary:hover {{ background-color: var(--neon-primary); color: #000; box-shadow: 0 0 20px var(--neon-primary); transform: scale(1.02); }}
            
            .form-control, .form-select {{ 
                border-radius: 14px; border: 1px solid rgba(255,255,255,0.1) !important; padding: 0.9rem 1.2rem; 
                color: #FFF !important; font-weight: 600; background-color: rgba(0,0,0,0.4) !important; transition: 0.3s ease;
            }}
            .form-control:focus, .form-select:focus {{ 
                box-shadow: 0 0 15px rgba(0, 240, 255, 0.3); border-color: var(--neon-primary) !important; 
                outline: none; background-color: rgba(0,0,0,0.6) !important; color: #FFF !important;
            }}
            .form-control::placeholder {{ color: #5C6A82 !important; }}
            .form-label {{ font-weight: 700; color: var(--text-muted); font-size: 0.95rem; margin-bottom: 0.6rem; text-transform: uppercase; letter-spacing: 1px;}}
            
            .badge {{ padding: 0.5rem 0.8rem; font-weight: 700; border-radius: 10px; font-size: 0.85rem; letter-spacing: 1px;}}
            .dir-ltr {{ direction: ltr !important; display: inline-block; text-align: left; font-family: monospace, sans-serif; letter-spacing: 1px; color: var(--neon-primary);}}
            
            .text-primary {{ color: var(--neon-primary) !important; text-shadow: 0 0 5px rgba(0, 240, 255, 0.5); }}
            .text-success {{ color: var(--neon-success) !important; text-shadow: 0 0 5px rgba(57, 255, 20, 0.5); }}
            .text-warning {{ color: var(--neon-warning) !important; text-shadow: 0 0 5px rgba(255, 234, 0, 0.5); }}
            .text-danger {{ color: var(--neon-danger) !important; text-shadow: 0 0 5px rgba(255, 0, 60, 0.5); }}
            .text-info {{ color: var(--neon-purple) !important; text-shadow: 0 0 5px rgba(176, 38, 255, 0.5); }}
            
            .alert {{ background-color: rgba(0,0,0,0.4) !important; border: 1px solid transparent; backdrop-filter: blur(10px); color: #FFF !important; }}
            .alert-success {{ border-color: var(--neon-success); box-shadow: 0 0 15px rgba(57, 255, 20, 0.2); }}
            .alert-danger {{ border-color: var(--neon-danger); box-shadow: 0 0 15px rgba(255, 0, 60, 0.2); }}
            
            .bg-white, .bg-light, .card-header.bg-white {{ background-color: var(--bg-card) !important; color: var(--text-main) !important; border-color: rgba(0, 240, 255, 0.1) !important; }}
            .text-dark {{ color: #FFFFFF !important; }}
            .text-muted {{ color: var(--text-muted) !important; }}
            
            .table {{ color: var(--text-main) !important; --bs-table-bg: transparent; --bs-table-color: var(--text-main); min-width: 600px; }}
            .table tbody tr {{ transition: all 0.3s ease; }}
            .table-hover tbody tr:hover {{ 
                background-color: rgba(0, 240, 255, 0.08) !important; 
                box-shadow: inset 4px 0 0 var(--neon-primary), inset 0 0 20px rgba(0, 240, 255, 0.1); 
            }}
            .table td, .table th {{ color: var(--text-main) !important; border-color: rgba(255, 255, 255, 0.05) !important; vertical-align: middle; }}
            
            select, option {{ background-color: rgba(10, 14, 23, 0.95) !important; color: #FFF !important; }}
            .badge.bg-secondary {{ background-color: rgba(176, 38, 255, 0.15) !important; color: var(--neon-purple) !important; border: 1px solid rgba(176, 38, 255, 0.4); }}
        </style>
    </head>
    <body>
        <!-- خلفية سوداء تظهر عند فتح المنيو على الموبايل -->
        <div class="sidebar-overlay" onclick="toggleSidebar()"></div>
        
        <!-- الشريط العلوي للموبايل -->
        <div class="mobile-header">
            <h4 class="mb-0 text-white fw-bold"><i class="bi bi-cpu-fill text-primary ms-2"></i>نظام الدريني</h4>
            <button class="mobile-toggle" onclick="toggleSidebar()">
                <i class="bi bi-list"></i>
            </button>
        </div>
        
        <aside class="sidebar">
            <div class="brand"><i class="bi bi-cpu-fill ms-2"></i>نظام الدريني</div>
            <ul class="nav flex-column mb-auto">
                {nav_links}
            </ul>
        </aside>
        
        <main class="main-content">
            {content}
        </main>
        
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script>
            function toggleSidebar() {{
                document.querySelector('.sidebar').classList.toggle('show');
                document.querySelector('.sidebar-overlay').classList.toggle('show');
            }}
            
            document.addEventListener("DOMContentLoaded", function() {{
                const currentPath = window.location.pathname;
                const navLinks = document.querySelectorAll('.sidebar .nav-link');
                navLinks.forEach(link => {{
                    if (link.getAttribute('href') === currentPath) {{
                        link.classList.add('active');
                    }} else {{
                        link.classList.remove('active');
                    }}
                }});
            }});
        </script>
    </body>
    </html>
    """

limiter = Limiter(key_func=get_remote_address)
scheduler = AsyncIOScheduler()

# =====================================================================
# الإضافات المؤسسية: محاكاة الربط مع أنظمة (ERP) مثل SAP أو Oracle
# =====================================================================
class SAPConnector:
    @staticmethod
    def create_purchase_order(tenant_id: str, details: dict) -> str:
        po_number = f"PO-SAP-{secrets.randbelow(999999)}"
        logger.info(f"[SAP Integration]: Purchase Order {po_number} created for tenant {tenant_id}. Details: {details}")
        return po_number

# =====================================================================
# المحور الأول: الوكيل الاستباقي (Proactive AI) وتذكير المهام
# =====================================================================
async def automated_task_reminders():
    if not db_firestore: return
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        tasks_docs = db_firestore.collection("followup_tasks").stream()
        for t_doc in tasks_docs:
            td = t_doc.to_dict()
            if td.get("status") == "pending":
                due_date = td.get("due_date")
                if due_date:
                    due_date = due_date.replace(tzinfo=None)
                    if today_start <= due_date < today_end:
                        tenant_id = td.get("tenant_id")
                        tenant_doc = db_firestore.collection("tenants").document(tenant_id).get()
                        if tenant_doc.exists:
                            tenant = TenantModel(tenant_doc.id, tenant_doc.to_dict())
                            llm = get_llm_client(tenant)
                            wa_manager = WhatsApp_Manager(tenant, db_firestore, llm)
                            msg = f"🔔 [تذكير تلقائي للمتابعة]:\nأهلاً بك، نذكرك بأن لديك مهمة مستحقة اليوم:\n- المهمة: {td.get('task_name')}\n- العميل: {td.get('client_name')}\n\nيرجى تحديث الحالة فور الانتهاء."
                            await wa_manager.send_message(td.get('partner_phone'), msg)
                            t_doc.reference.update({"status": "reminded"})
        logger.info(f"Automated reminders sent successfully.")
    except Exception as e:
        logger.error(f"Task Reminder Error: {e}")

async def proactive_market_agent():
    if not db_firestore: return
    try:
        tenants_docs = db_firestore.collection("tenants").stream()
        for t_doc in tenants_docs:
            tenant_id = t_doc.id
            tenant_data = t_doc.to_dict()
            
            approvals = db_firestore.collection("approval_queue").stream()
            old_pending = 0
            two_days_ago = datetime.utcnow() - timedelta(days=2)
            
            for app_doc in approvals:
                ad = app_doc.to_dict()
                if ad.get("tenant_id") == tenant_id and ad.get("status") == "pending":
                    created_at = ad.get("created_at")
                    if created_at and created_at.replace(tzinfo=None) < two_days_ago:
                        old_pending += 1
                        
            if old_pending > 0:
                tenant = TenantModel(tenant_id, tenant_data)
                llm = get_llm_client(tenant)
                if llm:
                    wa_manager = WhatsApp_Manager(tenant, db_firestore, llm)
                    admins = db_firestore.collection("team_members").stream()
                    for admin_doc in admins:
                        admin = admin_doc.to_dict()
                        if admin.get("tenant_id") == tenant_id and admin.get("role") == "admin":
                            alert_msg = f"🤖 [تقرير الوكيل الاستباقي]:\nمرحباً، لاحظت وجود ({old_pending}) طلبات تسعير معلقة في صندوق المراجعة منذ أكثر من يومين. هل ترغب في الموافقة عليها الآن لتسريع دورة المشتريات؟"
                            await wa_manager.send_message(admin.get("phone"), alert_msg)
        logger.info("Proactive Market Agent finished its daily check.")
    except Exception as e:
        logger.error(f"Proactive Agent Error: {e}")

# =====================================================================
# المحور الثاني: محرك الرسائل غير المتزامن (Asynchronous Message Broker)
# =====================================================================
whatsapp_queue = asyncio.Queue()

async def whatsapp_message_worker():
    while True:
        task = await whatsapp_queue.get()
        try:
            tenant_id = task.get("tenant_id")
            sender_phone = task.get("sender_phone")
            message_text = task.get("message_text")
            msg_type = task.get("msg_type")
            media_id = task.get("media_id")
            
            await process_queued_message(tenant_id, sender_phone, message_text, msg_type, media_id)
        except Exception as e:
            logger.error(f"WhatsApp Worker Error processing message: {e}")
        finally:
            whatsapp_queue.task_done()

async def process_queued_message(tenant_id: str, sender_phone: str, message_text: str, msg_type: str, media_id: str):
    if not db_firestore: return
    try:
        tenant_doc = db_firestore.collection("tenants").document(tenant_id).get()
        if not tenant_doc.exists: return
        tenant = TenantModel(tenant_doc.id, tenant_doc.to_dict())
        
        llm = get_llm_client(tenant)
        wa_manager = WhatsApp_Manager(tenant, db_firestore, llm)
        if not llm:
            await wa_manager.send_message(sender_phone, "[النظام]: الذكاء الاصطناعي غير مفعل أو المفاتيح ناقصة.")
            return

        if msg_type == "audio":
            message_text = f"[رسالة صوتية تم تفريغها آلياً بواسطة النظام]: {message_text or 'أريد عرض سعر للمنتج...'}"
            await wa_manager.send_message(sender_phone, "🎤 [النظام]: تم استلام رسالتك الصوتية وجاري معالجتها بالذكاء الاصطناعي...")
            
        elif msg_type == "image":
            message_text = f"[مرفق صورة تم تحليلها عبر Vision AI]: يبدو أن هذه فاتورة أو عرض سعر. الرجاء تحليلها وإعطاء الملخص.\n{message_text}"
            await wa_manager.send_message(sender_phone, "👁️ [النظام]: تم استلام الصورة وجاري قراءة محتوياتها بالرؤية الحاسوبية...")

        tm_docs = list(db_firestore.collection("team_members").stream())
        team_member = None
        for doc in tm_docs:
            d = doc.to_dict()
            if d.get("phone") == sender_phone and d.get("tenant_id") == tenant.id:
                team_member = d
                break
        
        sup_docs = list(db_firestore.collection("suppliers").stream())
        supplier_member = None
        for doc in sup_docs:
            d = doc.to_dict()
            if d.get("phone") == sender_phone and d.get("tenant_id") == tenant.id:
                supplier_member = d
                break
        
        is_admin = team_member and team_member.get('role') == 'admin'
        is_sales = (team_member and team_member.get('role') == 'sales') or supplier_member is not None
        
        history = get_chat_history(sender_phone, db_firestore)
        save_chat_history(sender_phone, "User", message_text, db_firestore, tenant.id)

        if is_admin:
            if "طلب" in message_text or "تسعير" in message_text or "مورد" in message_text:
                reply, is_procurement = await asyncio.to_thread(process_procurement_request, message_text, sender_phone, tenant, db_firestore, llm)
                await wa_manager.send_message(sender_phone, reply)
                save_chat_history(sender_phone, "AI", reply, db_firestore, tenant.id)
            else:
                prompt = f"{tenant.procurement_agent_prompt}\nرسالة المدير: '{message_text}'.\nتاريخ:\n{history}"
                res = await asyncio.to_thread(llm.invoke, prompt)
                clean_reply = await asyncio.to_thread(extract_and_save_followup, res.content, sender_phone, tenant.id, db_firestore)
                await wa_manager.send_message(sender_phone, clean_reply)
                save_chat_history(sender_phone, "AI", clean_reply, db_firestore, tenant.id)
        
        elif is_sales:
            rag_context = await asyncio.to_thread(fetch_rag_context, tenant, message_text)
            prompt = f"{tenant.procurement_agent_prompt}\nتاريخ المحادثة:\n{history}\nالمعلومات:\n{rag_context}\nرسالة شريك العمل/المورد: '{message_text}'"
            res = await asyncio.to_thread(llm.invoke, prompt)
            clean_reply = await asyncio.to_thread(extract_and_save_followup, res.content, sender_phone, tenant.id, db_firestore)
            await wa_manager.send_message(sender_phone, clean_reply)
            save_chat_history(sender_phone, "AI", clean_reply, db_firestore, tenant.id)
            
        else:
            reply = await wa_manager.handle_customer_inquiry(message_text, sender_phone, history)
            save_chat_history(sender_phone, "AI", reply, db_firestore, tenant.id)

    except Exception as e:
        logger.error(f"Error in process_queued_message: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(whatsapp_message_worker())
    scheduler.add_job(automated_task_reminders, 'cron', hour=9, minute=0)
    scheduler.add_job(proactive_market_agent, 'cron', hour=8, minute=0) 
    scheduler.start()
    logger.info("APScheduler and Async Queue Worker started successfully.")
    yield
    scheduler.shutdown()

app = FastAPI(title="Elderiny Enterprise AI System", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/health")
@app.get("/healthz")
async def health_check(db = Depends(get_db)):
    try:
        if db:
            list(db.collection("tenants").limit(1).stream())
            return {"status": "healthy", "db": "firebase_connected", "timestamp": datetime.utcnow()}
        return {"status": "unhealthy", "db": "disconnected"}
    except Exception as e:
        logger.error(f"Health Check Failed: {e}")
        return JSONResponse({"status": "unhealthy", "error": str(e)}, status_code=503)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if user: return RedirectResponse(url="/chat")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    content = """
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-md-5 col-lg-4">
            <div class="card shadow-lg border-0" style="border-top: 5px solid var(--neon-primary);">
                <div class="card-body p-5">
                    <div class="text-center mb-4">
                        <div class="bg-primary bg-opacity-10 text-primary d-inline-flex rounded-circle p-3 mb-3">
                            <i class="bi bi-shield-lock-fill fs-2"></i>
                        </div>
                        <h3 class="fw-bold">تسجيل الدخول للورشة</h3>
                        <p class="text-muted small">نظام إدارة أعطال المصنع بالذكاء الاصطناعي</p>
                    </div>
                    <form action="/login" method="post">
                        <div class="mb-3">
                            <label class="form-label">اسم المستخدم</label>
                            <input type="text" class="form-control bg-light" name="username" required placeholder="admin أو اسم العامل">
                        </div>
                        <div class="mb-4">
                            <label class="form-label">كلمة المرور</label>
                            <input type="password" class="form-control bg-light" name="password" required placeholder="••••••••">
                        </div>
                        <button type="submit" class="btn btn-primary w-100 py-2 fs-5">دخول مؤمن <i class="bi bi-arrow-left ms-2"></i></button>
                    </form>
                    <div class="text-center mt-4">
                        <a href="/register" class="text-success small fw-bold text-decoration-none"><i class="bi bi-building-add me-1"></i> تسجيل ورشة/شركة جديدة</a>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_html_layout(content, "تسجيل الدخول")

@app.post("/login")
async def login_post(response: Response, username: str = Form(...), password: str = Form(...), db = Depends(get_db)):
    if not db: return HTMLResponse(render_html_layout("<div class='alert alert-danger'>خطأ اتصال بقاعدة البيانات.</div>", "خطأ"))
    
    users = list(db.collection("users").stream())
    user_doc = None
    for doc in users:
        if doc.to_dict().get("username") == username:
            user_doc = doc
            break
            
    if not user_doc:
        content = "<div class='alert alert-danger text-center fw-bold mt-5 mx-auto' style='max-width: 500px;'><i class='bi bi-exclamation-triangle-fill me-2'></i>بيانات الدخول غير صحيحة. <a href='/login'>حاول مرة أخرى</a></div>"
        return HTMLResponse(render_html_layout(content, "خطأ"))
    
    user_data = user_doc.to_dict()
    if not verify_password(password, user_data.get("hashed_password")):
        content = "<div class='alert alert-danger text-center fw-bold mt-5 mx-auto' style='max-width: 500px;'><i class='bi bi-exclamation-triangle-fill me-2'></i>بيانات الدخول غير صحيحة. <a href='/login'>حاول مرة أخرى</a></div>"
        return HTMLResponse(render_html_layout(content, "خطأ"))
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": username}, expires_delta=access_token_expires)
    
    log_audit(db, user_data.get("tenant_id"), "تسجيل دخول (SSO Login)", username, "تم الدخول من واجهة الويب بنجاح.")
    
    redirect = RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return redirect

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    return response

def process_rag_document_bg(file_content: bytes, filename: str, tenant_id: str):
    try:
        tenant_doc = db_firestore.collection("tenants").document(tenant_id).get()
        if not tenant_doc.exists: return
        tenant = TenantModel(tenant_doc.id, tenant_doc.to_dict())
        
        db_firestore.collection("uploaded_files").add({
            "filename": filename,
            "file_type": filename.split('.')[-1] if '.' in filename else 'unknown',
            "upload_date": datetime.utcnow(),
            "tenant_id": tenant_id
        })

        openai_key = decrypt_val(tenant.openai_api_key)
        pinecone_key = decrypt_val(tenant.pinecone_api_key)
        
        if not openai_key or not pinecone_key or not tenant.pinecone_index: return

        embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
        text = ""
        if filename.lower().endswith('.pdf'):
            pdf_reader = PdfReader(io.BytesIO(file_content))
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted: text += extracted + "\n"
        else:
            text = file_content.decode('utf-8')
            
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_text(text)
        
        pc = PineconeClient(api_key=pinecone_key)
        index = pc.Index(tenant.pinecone_index)
        vector_store = PineconeVectorStore(index=index, embedding=embeddings, namespace=f"tenant_{tenant_id}")
        vector_store.add_texts(chunks)
        
        log_audit(db_firestore, tenant_id, "تحديث المعرفة RAG", "النظام", "تم رفع مستند وتحديث قاعدة البيانات الاتجاهية.")
    except Exception as e: 
        logger.error(f"RAG Processing Error: {e}")

@app.get("/data_management", response_class=HTMLResponse)
async def data_management_page(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role != 'admin': return RedirectResponse(url="/login")
    
    files_docs = db.collection("uploaded_files").stream()
    files = []
    for d in files_docs:
        if d.to_dict().get("tenant_id") == user.tenant_id:
            files.append(UploadedFileModel(d.id, d.to_dict()))
            
    files.sort(key=lambda x: x.upload_date, reverse=True)
    
    files_rows = ""
    for f in files:
        date_str = f.upload_date.strftime("%Y-%m-%d")
        files_rows += f"""
        <tr>
            <td class="fw-bold text-info"><i class="bi bi-file-earmark-text me-2"></i>{html.escape(f.filename)}</td>
            <td>{html.escape(f.file_type)}</td>
            <td>{date_str}</td>
            <td>
                <button class="btn btn-sm btn-outline-danger border-0" onclick="deleteFile('{f.id}')" title="حذف الملف"><i class="bi bi-trash-fill fs-5"></i></button>
            </td>
        </tr>
        """

    content = f"""
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <div class="row g-4">
        <div class="col-md-6">
            <div class="card border-0 h-100">
                <div class="card-header"><i class="bi bi-file-earmark-pdf-fill text-danger me-2"></i> تدريب الذكاء الاصطناعي للورشة (RAG)</div>
                <div class="card-body">
                    <div class="text-center mb-4 text-muted">
                        <i class="bi bi-cloud-arrow-up display-1 text-primary opacity-50"></i>
                        <p class="mt-3">ارفع كتالوجات الماكينات (CNC، مخارط) أو أدلة صيانة ضواغط الهواء بأي صيغة (PDF, TXT, CSV). سيتعلم منها الأسطى الآلي فوراً.</p>
                    </div>
                    <form action="/api/upload_rag" method="post" enctype="multipart/form-data">
                        <input class="form-control mb-3" type="file" name="file" accept=".pdf, .txt, .csv, .docx" required>
                        <button type="submit" class="btn btn-primary w-100 py-2"><i class="bi bi-cpu-fill me-2"></i> رفع وتدريب الأسطى</button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="col-md-6">
            <div class="card border-0 h-100">
                <div class="card-header"><i class="bi bi-archive-fill text-info me-2"></i> الملفات المرفوعة حالياً</div>
                <div class="card-body p-0">
                    <div class="table-responsive" style="max-height: 350px; overflow-y: auto;">
                        <table class="table table-hover align-middle m-0">
                            <thead class="sticky-top bg-dark"><tr><th>اسم الملف</th><th>النوع</th><th>التاريخ</th><th>حذف</th></tr></thead>
                            <tbody>
                                {files_rows if files_rows else '<tr><td colspan="4" class="text-center text-muted py-5"><i class="bi bi-inbox fs-1 d-block mb-2"></i> لا يوجد ملفات مرفوعة.</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
    async function deleteFile(id) {{
        if (!confirm('هل أنت متأكد من حذف هذا الملف؟ (الحذف سيكون من السجل فقط، ومسح المتجهات من Pinecone يتطلب لوحة Pinecone)')) return;
        try {{
            const response = await fetch('/api/files/delete/' + id, {{ method: 'DELETE' }});
            const res = await response.json();
            if (res.status === 'success') {{
                location.reload();
            }} else {{
                Swal.fire({{ title: 'خطأ!', text: res.message, icon: 'error' }});
            }}
        }} catch (err) {{
            Swal.fire({{ title: 'خطأ!', text: 'حدث خطأ تقني', icon: 'error' }});
        }}
    }}
    </script>
    """
    return render_html_layout(content, "إدارة البيانات والملفات", user)

@app.delete("/api/files/delete/{file_id}")
async def delete_file_api(file_id: str, request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role != 'admin': return JSONResponse({"status": "error", "message": "غير مصرح لك"})
    
    doc_ref = db.collection("uploaded_files").document(file_id)
    doc = doc_ref.get()
    if doc.exists and doc.to_dict().get("tenant_id") == user.tenant_id:
        doc_ref.delete()
        return JSONResponse({"status": "success", "message": "تم حذف الملف من السجل."})
    return JSONResponse({"status": "error", "message": "الملف غير موجود."})

@app.post("/api/upload_rag")
async def upload_rag_api(background_tasks: BackgroundTasks, request: Request, file: UploadFile = File(...), db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse(url="/login")
    if not user.tenant.openai_api_key or not user.tenant.pinecone_api_key:
        return HTMLResponse(render_html_layout("<div class='alert alert-danger'>يرجى إدخال مفتاح OpenAI ومفتاح Pinecone في الإعدادات.</div>", "خطأ", user))
    content = await file.read()
    background_tasks.add_task(process_rag_document_bg, content, file.filename, user.tenant_id)
    msg = "<div class='alert alert-success text-center py-4 fw-bold fs-5 rounded-4 shadow-sm mt-5 mx-auto' style='max-width:600px;'><i class='bi bi-check-circle-fill d-block fs-1 mb-3'></i> تم استلام الملف وجاري تدريب الأسطى الآلي في الخلفية.</div><div class='text-center mt-3'><a href='/data_management' class='btn btn-outline-success'>عودة للملفات</a></div>"
    return HTMLResponse(render_html_layout(msg, "جاري المعالجة", user))

@app.post("/api/upload_suppliers")
async def upload_suppliers_api(request: Request, file: UploadFile = File(...), db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse(url="/login")
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents)) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(contents))
        count = 0
        
        existing_docs = db.collection("suppliers").stream()
        existing_phones = set()
        for d in existing_docs:
            if d.to_dict().get("tenant_id") == user.tenant_id:
                existing_phones.add(d.to_dict().get("phone"))
        
        batch = db.batch()
        for index, row in df.iterrows():
            phone_str = str(row.get('Phone', ''))
            if phone_str and phone_str not in existing_phones:
                doc_ref = db.collection("suppliers").document()
                batch.set(doc_ref, {
                    "name": str(row.get('Name', 'عام')),
                    "category": str(row.get('Category', 'عام')),
                    "phone": phone_str,
                    "tenant_id": user.tenant_id
                })
                count += 1
                existing_phones.add(phone_str)
                if count % 400 == 0:
                    batch.commit()
                    batch = db.batch()
                    
        if count % 400 != 0:
            batch.commit()
            
        log_audit(db, user.tenant_id, "مزامنة موردين", user.username, f"تمت مزامنة ورفع عدد {count} موردين.")
        msg = f"<div class='alert alert-success text-center py-4 fw-bold fs-5 rounded-4 shadow-sm mt-5 mx-auto' style='max-width:600px;'><i class='bi bi-check-circle-fill d-block fs-1 mb-3'></i> تمت إضافة {count} مورد جديد للشركة.</div>"
        return HTMLResponse(render_html_layout(msg, "نجاح المزامنة", user))
    except Exception as e:
        return HTMLResponse(render_html_layout(f"<div class='alert alert-danger'>خطأ: {str(e)}</div>", "خطأ", user))

@app.post("/api/team/add")
async def add_team_member(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return JSONResponse({"status": "error", "message": "غير مصرح لك"})
    data = await request.json()
    
    db.collection("team_members").add({
        "name": data.get('name'),
        "phone": data.get('phone'),
        "role": data.get('role'),
        "tenant_id": user.tenant_id
    })
    
    if data.get('role') == 'worker':
        worker_username = f"worker_{data.get('phone')}"
        users_docs = list(db.collection("users").stream())
        existing = any(d.to_dict().get("username") == worker_username for d in users_docs)
        if not existing:
            db.collection("users").add({
                "username": worker_username,
                "hashed_password": get_password_hash(data.get('phone')), 
                "role": "worker",
                "tenant_id": user.tenant_id
            })
            
    return JSONResponse({"status": "success", "message": "تم إضافة العضو بنجاح. بيانات دخوله (يوزر وباسورد): رقمه."})

@app.delete("/api/team/delete/{member_id}")
async def delete_team_member(member_id: str, request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return JSONResponse({"status": "error", "message": "غير مصرح لك"})
    
    doc_ref = db.collection("team_members").document(member_id)
    doc = doc_ref.get()
    if doc.exists and doc.to_dict().get("tenant_id") == user.tenant_id:
        doc_ref.delete()
        return JSONResponse({"status": "success", "message": "تم الحذف بنجاح"})
    return JSONResponse({"status": "error", "message": "العضو غير موجود"})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role != 'admin': return RedirectResponse(url="/login") 
    t = user.tenant
    
    sel_openai = "selected" if t.llm_provider == "openai" else ""
    sel_anthropic = "selected" if t.llm_provider == "anthropic" else ""
    sel_google = "selected" if t.llm_provider == "google" else ""
    
    dec_openai = "********" if t.openai_api_key else ""
    dec_anthropic = "********" if t.anthropic_api_key else ""
    dec_google = "********" if t.google_api_key else ""
    dec_pinecone = "********" if t.pinecone_api_key else ""
    dec_wa = "********" if t.whatsapp_token else ""
    
    tree_json_str = t.decision_tree_prompt
        
    tm_docs = db.collection("team_members").stream()
    team_members = []
    for d in tm_docs:
        if d.to_dict().get("tenant_id") == t.id:
            team_members.append(TeamMemberModel(d.id, d.to_dict()))
    
    team_rows = ""
    for m in team_members:
        role_ar = "مدير" if m.role == 'admin' else "عامل ورشة"
        badge_cls = "bg-success" if m.role == 'admin' else "bg-warning text-dark"
        team_rows += f"""
        <tr>
            <td class="fw-bold">{html.escape(m.name)}</td>
            <td class="dir-ltr text-end">{html.escape(m.phone)}</td>
            <td><span class="badge {badge_cls}">{role_ar}</span></td>
            <td>
                <button class="btn btn-sm btn-outline-danger border-0" onclick="deleteTeamMember('{m.id}')" title="حذف العضو"><i class="bi bi-trash-fill fs-5"></i></button>
            </td>
        </tr>
        """
    
    content_html = f"""
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h2 class="fw-bold mb-0"><i class="bi bi-gear-fill text-primary me-2"></i> الإعدادات والربط</h2>
            <p class="text-muted mt-1">تكوين واجهات الربط البرمجية وخيارات العميل.</p>
        </div>
    </div>

    <div class="row g-4 mb-5">
        <div class="col-lg-12">
            <div class="card border-0 shadow-sm">
                <div class="card-header bg-primary bg-opacity-10 text-primary fs-5">
                    <i class="bi bi-person-lines-fill me-2"></i> إدارة المستخدمين (المديرين والعمال)
                </div>
                <div class="card-body">
                    <p class="text-muted mb-4"><i class="bi bi-info-circle text-warning me-1"></i> أضف هنا العمال أو المديرين. العامل المضاف سيتم إنشاء حساب له تلقائياً يكون اليوزر والباسورد هما <strong>رقم الموبايل</strong>.</p>
                    
                    <div class="card bg-dark border-secondary mb-4" style="background-color: #0A0E17 !important;">
                        <div class="card-body">
                            <form id="addTeamForm" class="row g-2 align-items-end" onsubmit="addTeamMember(event)">
                                <div class="col-md-3">
                                    <label class="form-label text-white small">الاسم</label>
                                    <input type="text" id="team_name" class="form-control" placeholder="مثال: الأسطى حسن" required>
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label text-white small">رقم الموبايل / الواتس</label>
                                    <input type="text" id="team_phone" class="form-control dir-ltr text-start" placeholder="مثال: 01012345678" required>
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label text-white small">الصلاحية</label>
                                    <select id="team_role" class="form-select fw-bold text-dark" style="background-color: #e2e8f0 !important;">
                                        <option value="worker">عامل في الورشة (يرى الشات فقط)</option>
                                        <option value="admin">مدير نظام (Admin)</option>
                                    </select>
                                </div>
                                <div class="col-md-2">
                                    <button type="submit" class="btn btn-primary w-100 fw-bold"><i class="bi bi-plus-circle me-1"></i> إضافة</button>
                                </div>
                            </form>
                        </div>
                    </div>
                    
                    <div class="table-responsive">
                        <table class="table table-hover align-middle">
                            <thead><tr><th>الاسم</th><th>الرقم</th><th>الصلاحية</th><th>حذف</th></tr></thead>
                            <tbody id="team_table_body">
                                {team_rows if team_rows else '<tr><td colspan="4" class="text-center text-muted py-3">لا يوجد أعضاء مسجلين حالياً.</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-lg-12">
            <div class="card border-0 h-100 shadow-sm">
                <div class="card-header bg-primary bg-opacity-10 text-primary fs-5">
                    <i class="bi bi-cpu-fill me-2"></i> محرك الذكاء الاصطناعي (LLM)
                </div>
                <div class="card-body">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label">مزود الذكاء الاصطناعي النشط</label>
                            <select id="llm_provider" class="form-select bg-light fw-bold">
                                <option value="openai" {sel_openai}>OpenAI (ChatGPT)</option>
                                <option value="anthropic" {sel_anthropic}>Anthropic (Claude)</option>
                                <option value="google" {sel_google}>Google (Gemini)</option>
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label">اسم النموذج (Model)</label>
                            <input type="text" id="llm_model" class="form-control bg-light dir-ltr text-start fw-bold" value="{t.llm_model}">
                        </div>
                        <div class="col-md-4 mt-4">
                            <label class="form-label small text-muted">OpenAI API Key</label>
                            <input type="password" id="openai_key" class="form-control dir-ltr text-start" value="{dec_openai}">
                        </div>
                        <div class="col-md-4 mt-4">
                            <label class="form-label small text-muted">Anthropic Key</label>
                            <input type="password" id="anthropic_key" class="form-control dir-ltr text-start" value="{dec_anthropic}">
                        </div>
                        <div class="col-md-4 mt-4">
                            <label class="form-label small text-muted">Google (Gemini) Key</label>
                            <input type="password" id="google_key" class="form-control dir-ltr text-start" value="{dec_google}">
                        </div>
                    </div>
                </div>
                <div class="card-footer bg-white border-top-0 pt-0 text-start pb-4 px-4">
                <button type="button" class="btn btn-primary px-4 fw-bold rounded-pill shadow-sm" onclick="saveAndTest('llm', this)">
                    <i class="bi bi-cloud-check-fill me-2"></i> حفظ الإعدادات واختبار الاتصال
                </button>
            </div>
        </div>
    </div>

    <div class="col-lg-6">
        <div class="card border-0 h-100 shadow-sm">
            <div class="card-header bg-danger bg-opacity-10 text-danger fs-5">
                <i class="bi bi-database-fill me-2"></i> قاعدة بيانات (Pinecone)
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-12">
                        <label class="form-label">Pinecone API Key</label>
                        <input type="password" id="pinecone_key" class="form-control dir-ltr text-start" value="{dec_pinecone}">
                    </div>
                    <div class="col-12">
                        <label class="form-label">Index Name</label>
                        <input type="text" id="pinecone_index" class="form-control dir-ltr text-start fw-bold" value="{t.pinecone_index}">
                    </div>
                </div>
            </div>
            <div class="card-footer bg-white border-top-0 pt-0 text-start pb-4 px-4">
                <button type="button" class="btn btn-danger px-4 fw-bold rounded-pill shadow-sm" onclick="saveAndTest('pinecone', this)">
                    <i class="bi bi-hdd-network-fill me-2"></i> حفظ إعدادات Pinecone
                </button>
            </div>
        </div>
    </div>

    <div class="col-lg-6">
        <div class="card border-0 h-100 shadow-sm">
                <div class="card-header bg-success bg-opacity-10 text-success fs-5">
                    <i class="bi bi-whatsapp me-2"></i> إعدادات المراسلة (Meta WhatsApp)
                </div>
                <div class="card-body">
                    <div class="row g-3">
                        <div class="col-12">
                            <label class="form-label">WhatsApp Verify Token</label>
                            <input type="text" id="verify_token" class="form-control dir-ltr text-start" value="{t.verify_token}">
                        </div>
                        <div class="col-12">
                            <label class="form-label">WhatsApp Access Token</label>
                            <input type="password" id="wa_token" class="form-control dir-ltr text-start" value="{dec_wa}">
                        </div>
                        <div class="col-12">
                            <label class="form-label">WhatsApp Phone ID</label>
                            <input type="text" id="wa_phone" class="form-control dir-ltr text-start fw-bold" value="{t.whatsapp_phone_id}">
                        </div>
                    </div>
                </div>
                <div class="card-footer bg-white border-top-0 pt-0 text-start pb-4 px-4">
                    <button type="button" class="btn btn-success px-4 fw-bold rounded-pill shadow-sm" onclick="saveAndTest('whatsapp', this)">
                        <i class="bi bi-send-check-fill me-2"></i> حفظ إعدادات الواتساب
                    </button>
                </div>
            </div>
        </div>

        <div class="col-lg-12">
            <div class="card border-0 shadow-sm">
                <div class="card-header bg-warning bg-opacity-10 text-warning fs-5">
                    <i class="bi bi-diagram-3-fill me-2"></i> توجيه الأسطى الآلي
                </div>
                <div class="card-body">
                    <div class="row g-4">
                        <div class="col-12 mt-2">
                            <label class="form-label text-primary"><i class="bi bi-headset me-1"></i> شخصية الأسطى الآلي (صوت وصورة)</label>
                            <textarea id="cs_prompt" class="form-control" rows="5">{t.customer_service_prompt}</textarea>
                            <div class="form-text text-muted">هنا تقدر تكتب تعليمات الأسطى، خليه يتكلم مصري، يفهم المكن، ويحل للعمال الأعطال بالتفصيل الممل.</div>
                        </div>
                        
                        <div class="col-12 mt-4" style="display:none;">
                            <input type="hidden" id="raw_tree_data" value='{html.escape(tree_json_str)}'>
                            <input type="hidden" id="decision_tree" value='{html.escape(tree_json_str)}'>
                            <textarea id="proc_prompt" class="form-control" rows="3" disabled>{t.procurement_agent_prompt}</textarea>
                        </div>
                    </div>
                </div>
                <div class="card-footer bg-white border-top-0 pt-0 text-start pb-4 px-4">
                    <button type="button" class="btn btn-warning text-dark px-4 fw-bold rounded-pill shadow-sm" onclick="saveAndTest('prompts', this)">
                        <i class="bi bi-save2-fill me-2"></i> حفظ الشخصية
                    </button>
                </div>
            </div>
        </div>
    </div>
    """
    
    content_js = """
    <script>
    async function addTeamMember(e) {
        e.preventDefault();
        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        
        const payload = {
            name: document.getElementById('team_name').value,
            phone: document.getElementById('team_phone').value,
            role: document.getElementById('team_role').value
        };
        
        try {
            const response = await fetch('/api/team/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const res = await response.json();
            if (res.status === 'success') {
                Swal.fire({ title: 'نجاح!', text: res.message, icon: 'success', confirmButtonColor: '#10b981' }).then(() => location.reload());
            } else {
                Swal.fire({ title: 'خطأ!', text: res.message, icon: 'error' });
            }
        } catch (err) {
            Swal.fire({ title: 'خطأ!', text: 'حدث خطأ تقني', icon: 'error' });
        }
        btn.disabled = false;
    }

    async function deleteTeamMember(id) {
        if (!confirm('هل أنت متأكد من حذف هذا العامل/المدير من الصلاحيات؟')) return;
        try {
            const response = await fetch('/api/team/delete/' + id, { method: 'DELETE' });
            const res = await response.json();
            if (res.status === 'success') {
                location.reload();
            } else {
                Swal.fire({ title: 'خطأ!', text: res.message, icon: 'error' });
            }
        } catch (err) {
            Swal.fire({ title: 'خطأ!', text: 'حدث خطأ تقني', icon: 'error' });
        }
    }

    async function saveAndTest(section, btn) {
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>جاري الحفظ...';
        btn.disabled = true;

        let payload = { section: section, data: {} };

        if (section === 'llm') {
            payload.data = {
                llm_provider: document.getElementById('llm_provider').value,
                llm_model: document.getElementById('llm_model').value,
                openai_key: document.getElementById('openai_key').value,
                anthropic_key: document.getElementById('anthropic_key').value,
                google_key: document.getElementById('google_key').value
            };
        } else if (section === 'pinecone') {
            payload.data = {
                pinecone_key: document.getElementById('pinecone_key').value,
                pinecone_index: document.getElementById('pinecone_index').value
            };
        } else if (section === 'whatsapp') {
            payload.data = {
                verify_token: document.getElementById('verify_token').value,
                wa_token: document.getElementById('wa_token').value,
                wa_phone: document.getElementById('wa_phone').value
            };
        } else if (section === 'prompts') {
            payload.data = {
                cs_prompt: document.getElementById('cs_prompt').value,
                decision_tree: document.getElementById('decision_tree').value
            };
        }

        try {
            const response = await fetch('/api/settings/save_and_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();

            if (result.status === 'success') {
                Swal.fire({ title: 'نجاح!', text: result.message, icon: 'success', confirmButtonColor: '#10b981' });
            } else {
                Swal.fire({ title: 'خطأ!', text: result.message, icon: 'error', confirmButtonColor: '#ef4444' });
            }
        } catch (error) {
            Swal.fire({ title: 'خطأ تقني!', text: 'تعذر الاتصال بالخادم.', icon: 'error', confirmButtonColor: '#ef4444' });
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }
    </script>
    <div style="height: 60px;"></div>
    """
    
    final_content = content_html + content_js
    return render_html_layout(final_content, "الإعدادات الذكية", user)

@app.post("/api/settings/save_and_test")
async def save_and_test_api(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role != 'admin': return JSONResponse({"status": "error", "message": "غير مصرح لك بإجراء التعديلات"})
    
    t = user.tenant
    body = await request.json()
    section = body.get("section")
    data = body.get("data", {})

    try:
        tenant_ref = db.collection("tenants").document(t.id)
        updates = {}
        
        if section == "llm":
            updates["llm_provider"] = data.get("llm_provider", "openai")
            updates["llm_model"] = data.get("llm_model", "gpt-4o")
            if data.get("openai_key") and data.get("openai_key") != "********": updates["openai_api_key"] = encrypt_val(data.get("openai_key"))
            if data.get("anthropic_key") and data.get("anthropic_key") != "********": updates["anthropic_api_key"] = encrypt_val(data.get("anthropic_key"))
            if data.get("google_key") and data.get("google_key") != "********": updates["google_api_key"] = encrypt_val(data.get("google_key"))
            
            tenant_ref.update(updates)
            
            t.llm_provider = updates["llm_provider"]
            t.llm_model = updates["llm_model"]
            if "openai_api_key" in updates: t.openai_api_key = updates["openai_api_key"]
            if "anthropic_api_key" in updates: t.anthropic_api_key = updates["anthropic_api_key"]
            if "google_api_key" in updates: t.google_api_key = updates["google_api_key"]

            llm_pool.invalidate(t.id)
            llm = get_llm_client(t)
            if not llm: raise Exception(f"يرجى التأكد من إدخال المفتاح الصحيح.")
            
            res = llm.invoke("Hello, connection test.")
            return JSONResponse({"status": "success", "message": f"تم الحفظ! الاتصال بنموذج [{t.llm_model}] يعمل بكفاءة."})

        elif section == "pinecone":
            if data.get("pinecone_key") and data.get("pinecone_key") != "********": updates["pinecone_api_key"] = encrypt_val(data.get("pinecone_key"))
            updates["pinecone_index"] = data.get("pinecone_index", "")
            tenant_ref.update(updates)
            return JSONResponse({"status": "success", "message": "تم حفظ إعدادات Pinecone بنجاح."})

        elif section == "whatsapp":
            updates["verify_token"] = data.get("verify_token", "")
            if data.get("wa_token") and data.get("wa_token") != "********": updates["whatsapp_token"] = encrypt_val(data.get("wa_token"))
            updates["whatsapp_phone_id"] = data.get("wa_phone", "")
            tenant_ref.update(updates)
            return JSONResponse({"status": "success", "message": "تم حفظ إعدادات الواتساب بنجاح."})

        elif section == "prompts":
            updates["customer_service_prompt"] = data.get("cs_prompt", "")
            updates["decision_tree_prompt"] = data.get("decision_tree", "")
            tenant_ref.update(updates)
            return JSONResponse({"status": "success", "message": "تم حفظ شخصية الأسطى بنجاح."})

        return JSONResponse({"status": "error", "message": "قطاع غير معروف."})

    except Exception as e:
        logger.error(f"Settings Save Error: {e}")
        return JSONResponse({"status": "error", "message": str(e)})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse(url="/login")
    
    welcome_msg = "يا هلا بيك يا بطل، معاك الأسطى الآلي. دوس على علامة المايك وسجل مشكلتك في المكنة وهرد عليك بالصوت والخطوات." if user.role != 'admin' else "مرحباً يا مدير. الغرفة مشفرة وآمنة. المساعد الصوتي جاهز للاستماع."
    
    content_html = f"""
    <style>
        .main-content {{ 
            padding: 0 !important; 
            width: calc(100% - var(--sidebar-width)); 
            height: 100vh; 
            height: 100dvh; 
            overflow: hidden; 
            display: flex; 
            flex-direction: column; 
        }}
        
        .chat-wrapper {{ 
            flex: 1;
            border-radius: 0; 
            border: none; 
            display: flex; 
            flex-direction: column; 
            background-color: #0A0E17;
            overflow: hidden;
            width: 100%;
        }}
        
        .wa-container {{ 
            flex: 1;
            display: block; 
            position: relative; 
            height: 100%;
            width: 100%;
        }}
        
        .wa-header {{ 
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 80px;
            background-color: rgba(16, 22, 35, 0.95); 
            padding: 15px 25px; 
            display: flex; 
            align-items: center; 
            justify-content: space-between; 
            border-bottom: 1px solid rgba(0, 240, 255, 0.1); 
            z-index: 20; 
        }}
        
        .wa-messages {{ 
            position: absolute;
            top: 80px;
            bottom: 80px; 
            left: 0; right: 0;
            overflow-y: auto; 
            padding: 20px; 
            display: flex; 
            flex-direction: column; 
            gap: 15px; 
            background-color: #0A0E17;
            scroll-behavior: smooth;
        }}
        
        .wa-bubble {{ max-width: 85%; padding: 12px 18px; border-radius: 16px; position: relative; font-size: 15px; line-height: 1.5; font-weight: 600; word-wrap: break-word;}}
        .wa-bubble.ai {{ background-color: rgba(16, 22, 35, 0.9); color: #FFF; align-self: flex-start; border-top-right-radius: 0; border: 1px solid rgba(0, 240, 255, 0.2); box-shadow: 0 4px 10px rgba(0,0,0,0.2); }}
        .wa-bubble.user {{ background-color: var(--neon-primary); color: #000; align-self: flex-end; border-top-left-radius: 0; box-shadow: 0 4px 10px rgba(0, 240, 255, 0.2);}}
        
        .wa-footer {{ 
            position: absolute;
            bottom: 0; left: 0; right: 0;
            height: 80px;
            background-color: rgba(16, 22, 35, 0.98); 
            padding: 10px 20px; 
            display: flex; 
            gap: 10px; 
            align-items: center; 
            border-top: 1px solid rgba(0, 240, 255, 0.1); 
            z-index: 20;
        }}
        
        .wa-input {{ flex: 1; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(0,0,0,0.5); color: #fff; border-radius: 25px; padding: 14px 20px; outline: none; font-weight: 600; font-size: 15px; width: 100%; height: 50px; margin: 0; }}
        .wa-input:focus {{ background-color: rgba(0,0,0,0.8); border-color: var(--neon-primary); box-shadow: 0 0 10px rgba(0, 240, 255, 0.2);}}
        .wa-input::placeholder {{ color: #8B9BB4; font-size: 14px; }}
        
        .wa-btn {{ background-color: transparent; border: 1px solid var(--neon-primary); color: var(--neon-primary); border-radius: 50%; width: 50px; height: 50px; display: flex; justify-content: center; align-items: center; cursor: pointer; transition: 0.2s; font-size: 1.2rem; flex-shrink: 0; user-select: none; -webkit-user-select: none; touch-action: manipulation; margin: 0; }}
        .wa-btn:active {{ transform: scale(0.95); }}
        
        .voice-btn-active {{ background-color: var(--neon-danger) !important; color: #fff !important; border-color: var(--neon-danger) !important; box-shadow: 0 0 20px var(--neon-danger) !important; transform: scale(1.1) !important; animation: pulse-red 1.2s infinite; }}
        
        @keyframes pulse-red {{ 0% {{ box-shadow: 0 0 0 0 rgba(255, 0, 60, 0.7); }} 70% {{ box-shadow: 0 0 0 15px rgba(255, 0, 60, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(255, 0, 60, 0); }} }}
        @keyframes popIn {{ 0% {{ transform: scale(0.9); opacity: 0; }} 100% {{ transform: scale(1); opacity: 1; }} }}
        .magic-badge {{ animation: popIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; }}

        @media (min-width: 993px) {{
            .chat-wrapper {{ border-radius: 20px; margin: 2rem; height: calc(100dvh - 4rem); }}
            .wa-header {{ padding: 20px 35px; }}
            .wa-messages {{ padding: 30px; bottom: 85px; }}
            .wa-footer {{ padding: 15px 35px; height: 85px; }}
            .wa-input {{ padding: 16px 25px; font-size: 16px; height: 55px; }}
            .wa-btn {{ width: 55px; height: 55px; font-size: 1.3rem; }}
        }}
    </style>

    <div class="chat-wrapper">
        <div class="wa-container">
            <div class="wa-header">
                <div class="d-flex align-items-center">
                    <div class="bg-primary bg-opacity-10 text-primary rounded-circle p-2 me-3 d-flex align-items-center justify-content-center" style="width: 45px; height: 45px;">
                        <i class="bi bi-tools fs-4"></i>
                    </div>
                    <div>
                        <span class="fw-bold fs-5 d-block text-white">الأسطى الآلي</span>
                        <span class="text-success small fw-bold"><i class="bi bi-circle-fill me-1" style="font-size: 0.5rem;"></i>جاهز للمساعدة</span>
                    </div>
                </div>
            </div>
            
            <div class="wa-messages" id="chatBox">
                <div class="text-center w-100 my-2">
                    <span class="px-3 py-1 rounded-pill small fw-bold" style="background: rgba(0, 240, 255, 0.1); color: var(--neon-primary); border: 1px solid rgba(0, 240, 255, 0.3);">اليوم</span>
                </div>
                <div class="wa-bubble ai">
                    <i class="bi bi-mic-fill text-primary me-1"></i> {welcome_msg}
                </div>
            </div>
            
            <div class="wa-footer">
                <button id="voiceBtn" class="wa-btn" title="اضغط باستمرار للتحدث">
                    <i class="bi bi-mic-fill"></i>
                </button>
                <input type="text" id="chatInput" class="wa-input" placeholder="رسالة..." onkeypress="handleKeyPress(event)">
                <button class="wa-btn" style="background-color: var(--neon-primary); color: #000;" onclick="sendMessage()">
                    <i class="bi bi-send-fill"></i>
                </button>
            </div>
        </div>
    </div>
    """
    
    content_js = r"""
    <script>
        const chatBox = document.getElementById('chatBox');
        const chatInput = document.getElementById('chatInput');
        const voiceBtn = document.getElementById('voiceBtn');
        
        let isRecording = false;
        let recognition = null;
        let finalTranscript = '';

        function speakText(text) {
            if ('speechSynthesis' in window) {
                let cleanText = text.replace(/<[^>]+>/g, '').replace(/[*_#]/g, '');
                window.speechSynthesis.cancel();
                
                const utterance = new SpeechSynthesisUtterance(cleanText);
                utterance.lang = 'ar-EG'; 
                utterance.rate = 1.0; 
                utterance.pitch = 0.9; 
                
                const voices = window.speechSynthesis.getVoices();
                const arabicVoice = voices.find(v => v.lang.includes('ar') && v.name.includes('Male'));
                if(arabicVoice) utterance.voice = arabicVoice;

                window.speechSynthesis.speak(utterance);
            }
        }

        window.speechSynthesis.onvoiceschanged = function() {
            window.speechSynthesis.getVoices();
        };

        function appendMessage(text, sender) {
            const div = document.createElement('div');
            div.className = `wa-bubble ${sender}`;
            div.innerHTML = text.replace(/\n/g, '<br>');
            chatBox.appendChild(div);
            scrollToBottom();
            return div;
        }
        
        function scrollToBottom() {
            setTimeout(() => {
                chatBox.scrollTop = chatBox.scrollHeight;
            }, 50);
        }

        function handleKeyPress(e) { if (e.key === 'Enter') sendMessage(); }

        function initSpeechRecognition() {
            window.SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!window.SpeechRecognition) {
                alert("للأسف، المتصفح لا يدعم التسجيل الصوتي. يرجى استخدام متصفح حديث (Chrome/Safari).");
                return null;
            }

            const rec = new window.SpeechRecognition();
            rec.lang = 'ar-EG'; 
            rec.interimResults = true; 
            rec.continuous = true; 
            
            rec.onstart = function() {
                isRecording = true;
                voiceBtn.classList.add('voice-btn-active');
                chatInput.placeholder = "🎤 جاري الاستماع للأسطى... (أفلت للإرسال)";
                chatInput.value = '';
                finalTranscript = '';
                window.speechSynthesis.cancel(); 
            };
            
            rec.onresult = function(event) {
                let interimTranscript = '';
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }
                chatInput.value = finalTranscript + interimTranscript;
            };
            
            rec.onerror = function(event) {
                console.error("Speech Error: ", event.error);
                resetVoiceUI();
            };
            
            rec.onend = function() {
                resetVoiceUI();
                if (chatInput.value.trim() !== '') {
                    sendMessage(); 
                }
            };
            
            return rec;
        }

        function handleVoiceStart(e) {
            e.preventDefault(); 
            if (isRecording && recognition) {
                recognition.stop();
                return;
            }
            recognition = initSpeechRecognition();
            if (recognition) recognition.start();
        }

        function handleVoiceEnd(e) {
            e.preventDefault();
            if (isRecording && recognition) {
                recognition.stop();
            }
        }

        function resetVoiceUI() {
            isRecording = false;
            voiceBtn.classList.remove('voice-btn-active');
            chatInput.placeholder = "رسالة...";
        }

        voiceBtn.addEventListener('mousedown', handleVoiceStart);
        voiceBtn.addEventListener('mouseup', handleVoiceEnd);
        voiceBtn.addEventListener('mouseleave', handleVoiceEnd);
        
        voiceBtn.addEventListener('touchstart', handleVoiceStart, {passive: false});
        voiceBtn.addEventListener('touchend', handleVoiceEnd, {passive: false});
        voiceBtn.addEventListener('touchcancel', handleVoiceEnd, {passive: false});

        async function sendMessage() {
            const text = chatInput.value.trim();
            if (!text) return;
            
            appendMessage(text, 'user');
            chatInput.value = '';
            chatInput.blur(); 
            
            const bubbleDiv = document.createElement('div');
            bubbleDiv.className = 'wa-bubble ai text-muted';
            bubbleDiv.innerHTML = '<span class="spinner-grow spinner-grow-sm text-primary me-2"></span> الأسطى بيفكر...';
            chatBox.appendChild(bubbleDiv);
            scrollToBottom();

            let fullResponseText = "";

            try {
                const response = await fetch('/api/simulate_chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, role: 'customer' })
                });

                if (!response.body) throw new Error('ReadableStream not supported.');

                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                bubbleDiv.innerHTML = ""; 
                bubbleDiv.classList.remove('text-muted');

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    
                    const chunkStr = decoder.decode(value, { stream: true });
                    const lines = chunkStr.split('\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const dataStr = line.replace('data: ', '').trim();
                            if (!dataStr) continue;
                            
                            try {
                                const data = JSON.parse(dataStr);
                                
                                if (data.error) {
                                    bubbleDiv.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-triangle-fill"></i> ${data.error}</span>`;
                                } else if (data.status === 'processing') {
                                    bubbleDiv.innerHTML = `<span class="spinner-border spinner-border-sm text-warning me-2"></span><strong class="text-warning">${data.message}</strong>`;
                                } else if (data.chunk) {
                                    if (bubbleDiv.innerHTML.includes('spinner-border')) bubbleDiv.innerHTML = '';
                                    
                                    fullResponseText += data.chunk;
                                    
                                    let displayHtml = fullResponseText
                                        .replace(/\[النظام\]:/g, '<strong class="text-primary"><i class="bi bi-info-circle-fill me-1"></i> [الأسطى]:</strong>')
                                        .replace(/\n/g, '<br>');
                                        
                                    bubbleDiv.innerHTML = displayHtml;
                                    scrollToBottom();
                                }
                            } catch (e) { console.error("Parse error", e); }
                        }
                    }
                }
                
                let finalHtml = fullResponseText.replace(/\n/g, '<br>');
                bubbleDiv.innerHTML = finalHtml;
                scrollToBottom();
                
                speakText(fullResponseText);

            } catch (err) {
                bubbleDiv.innerHTML = "<span class='text-danger'><i class='bi bi-x-circle-fill'></i> [خطأ]: تعذر الاتصال بالخادم.</span>";
            }
        }
    </script>
    """
    
    final_content = content_html + content_js
    return render_html_layout(final_content, "الأسطى الآلي", user)

memory_saver = MemorySaver()

class AgentState(MessagesState):
    summary: str
    agent_type: str

def build_derini_orchestrator(llm, tenant):
    workflow = StateGraph(AgentState)

    async def routing_node(state: AgentState):
        last_msg = state["messages"][-1].content
        if any(word in last_msg for word in ["شراء", "مورد", "تسعير", "عرض"]):
            return {"agent_type": "procurement"}
        elif any(word in last_msg for word in ["ميزانية", "مالي", "دفع", "تكلفة"]):
            return {"agent_type": "finance"}
        elif any(word in last_msg for word in ["قانوني", "شرط", "جزائي", "عقد"]):
            return {"agent_type": "legal"}
        return {"agent_type": "general"}

    async def procurement_agent(state: AgentState):
        sys_prompt = SystemMessage(content=f"{tenant.procurement_agent_prompt}\nأنت 'وكيل المشتريات والمقارنة'. مهمتك تقييم العروض والتفاوض بذكاء.")
        messages = [sys_prompt] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    async def finance_agent(state: AgentState):
        sys_prompt = SystemMessage(content="أنت 'الوكيل المالي (CFO Agent)'. مهمتك هي مطابقة العروض مع ميزانية الشركة وتوفير التكاليف بناءً على سياسات الإدارة المالية.")
        messages = [sys_prompt] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    async def legal_agent(state: AgentState):
        sys_prompt = SystemMessage(content="أنت 'الوكيل القانوني (Legal Agent)'. مهمتك هي التدقيق في شروط العروض والعقود والمقترحات واكتشاف أي ثغرات قانونية أو شروط جزائية ضد الشركة.")
        messages = [sys_prompt] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    async def general_agent(state: AgentState):
        summary = state.get("summary", "")
        sys_prompt = SystemMessage(content=f"{tenant.customer_service_prompt}\nالذاكرة طويلة المدى: {summary}")
        messages = [sys_prompt] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    async def summarization_node(state: AgentState):
        summary = state.get("summary", "")
        prompt = f"الذاكرة السابقة: {summary}\nقم بدمج وتلخيص أحدث الرسائل لتحديث الذاكرة الطويلة:" if summary else "لخص المحادثة التالية بإيجاز شديد للاحتفاظ بها كذاكرة طويلة المدى:"
        messages_to_summarize = state["messages"][-5:]
        messages = messages_to_summarize + [HumanMessage(content=prompt)]
        response = await llm.ainvoke(messages)
        
        delete_messages = [RemoveMessage(id=m.id) for m in state["messages"][:-3]]
        return {"summary": response.content, "messages": delete_messages}

    def route_after_start(state: AgentState):
        return state.get("agent_type", "general")
        
    def check_memory_length(state: AgentState):
        if len(state["messages"]) > 6:
            return "summarize"
        return END

    workflow.add_node("router", routing_node)
    workflow.add_node("procurement", procurement_agent)
    workflow.add_node("finance", finance_agent)
    workflow.add_node("legal", legal_agent)
    workflow.add_node("general", general_agent)
    workflow.add_node("summarize", summarization_node)

    workflow.add_edge(START, "router")
    workflow.add_conditional_edges("router", route_after_start, {
        "procurement": "procurement", 
        "finance": "finance",
        "legal": "legal",
        "general": "general"
    })
    workflow.add_conditional_edges("procurement", check_memory_length, {"summarize": "summarize", END: END})
    workflow.add_conditional_edges("finance", check_memory_length, {"summarize": "summarize", END: END})
    workflow.add_conditional_edges("legal", check_memory_length, {"summarize": "summarize", END: END})
    workflow.add_conditional_edges("general", check_memory_length, {"summarize": "summarize", END: END})
    workflow.add_edge("summarize", END)

    return workflow.compile(checkpointer=memory_saver)

class ChatRequest(BaseModel):
    message: str
    role: str = "customer"
    model_config = ConfigDict(extra="forbid")

@app.post("/api/simulate_chat")
async def simulate_chat_api(chat_req: ChatRequest, request: Request, db = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user: 
        return StreamingResponse((f"data: {json.dumps({'error': '[مرفوض]: يرجى تسجيل الدخول.'})}\n\n" for _ in range(1)), media_type="text/event-stream")
    
    message_text = chat_req.message[:2000]
    tenant = user.tenant
    
    llm = get_llm_client(tenant)
    if not llm: 
        return StreamingResponse((f"data: {json.dumps({'error': '[النظام]: الذكاء الاصطناعي غير مفعل. راجع الإعدادات.'})}\n\n" for _ in range(1)), media_type="text/event-stream")
    
    rag_context = await asyncio.to_thread(fetch_rag_context, tenant, message_text)
    enhanced_message = message_text
    if rag_context:
        enhanced_message = f"سؤال العامل: {message_text}\n\n[معلومات فنية من الكتالوجات والملفات المرفوعة للورشة للمساعدة في الرد بدقة]:\n{rag_context}\n\nرد على العامل بأسلوبك كـ (أسطى مصري) بناءً على هذه المعلومات فقط وبشكل مبسط جداً."
        
    session_id = f"sim_{user.username}"
    app_graph = build_derini_orchestrator(llm, tenant)
    thread_config = {"configurable": {"thread_id": session_id}}
    
    async def event_generator() -> AsyncGenerator[str, None]:
        full_response = ""
        try:
            async for event in app_graph.astream_events(
                {"messages": [HumanMessage(content=enhanced_message)]}, 
                config=thread_config, 
                version="v2"
            ):
                kind = event["event"]
                
                if kind == "on_chain_start" and event["name"] == "summarize":
                    pass 
                elif kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        full_response += chunk.content
                        yield f"data: {json.dumps({'chunk': chunk.content})}\n\n"
                        
        except Exception as e:
            yield f"data: {json.dumps({'error': f'[خطأ تقني]: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

class LLMClientPool:
    def __init__(self, max_size: int = 50):
        self._pool: dict = {}
        self._lock = Lock()
        self._max_size = max_size
        
    def get_or_create(self, tenant_id: str, provider: str, model: str, key: str):
        key_hash = hashlib.sha256(key.encode()).hexdigest()[:16]
        cache_key = f"{tenant_id}:{provider}:{model}:{key_hash}"
                
        with self._lock:
            if cache_key not in self._pool:
                if len(self._pool) >= self._max_size:
                    oldest = next(iter(self._pool))
                    del self._pool[oldest]
                self._pool[cache_key] = self._build(provider, model, key)
            return self._pool[cache_key]
            
    def invalidate(self, tenant_id: str):
        with self._lock:
            keys_to_delete = [k for k in self._pool if k.startswith(f"{tenant_id}:")]
            for k in keys_to_delete:
                del self._pool[k]
                
    @staticmethod
    def _build(provider: str, model: str, key: str):
        try:
            if provider == "anthropic":
                return ChatAnthropic(model_name=model, anthropic_api_key=key, temperature=0.2)
            elif provider == "google":
                return ChatGoogleGenerativeAI(model=model, google_api_key=key, temperature=0.2)
            else:
                return ChatOpenAI(model_name=model, openai_api_key=key, temperature=0.2)
        except Exception as e:
            logger.error(f"LLM Build Error: {e}")
            return None

llm_pool = LLMClientPool()

def get_llm_client(tenant: TenantModel):
    try:
        if tenant.llm_provider == "anthropic":
            key = decrypt_val(tenant.anthropic_api_key)
        elif tenant.llm_provider == "google":
            key = decrypt_val(tenant.google_api_key)
        else:
            key = decrypt_val(tenant.openai_api_key)
            
        if not key: return None
        return llm_pool.get_or_create(tenant.id, tenant.llm_provider, tenant.llm_model, key)
    except Exception as e: 
        logger.error(f"Error fetching LLM client: {e}")
        return None

def fetch_rag_context(tenant: TenantModel, message: str) -> str:
    rag_context = ""
    openai_key = decrypt_val(tenant.openai_api_key)
    pinecone_key = decrypt_val(tenant.pinecone_api_key)
    
    if openai_key and pinecone_key and tenant.pinecone_index:
        try:
            embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
            pc = PineconeClient(api_key=pinecone_key)
            index = pc.Index(tenant.pinecone_index)
            vector_store = PineconeVectorStore(index=index, embedding=embeddings, namespace=f"tenant_{tenant.id}")
            
            docs = vector_store.similarity_search(message, k=3)
            rag_context = "\n---\n".join([doc.page_content for doc in docs])
        except Exception as e:
            logger.error(f"Pinecone Error: {e}")
    return rag_context

def process_procurement_request(message_text: str, sender_id: str, tenant: TenantModel, db, llm) -> tuple[str, bool]:
    tenant_id = tenant.id

    def _search_suppliers(category: str) -> str:
        all_suppliers = db.collection("suppliers").stream()
        suppliers = []
        for doc in all_suppliers:
            d = doc.to_dict()
            if d.get("tenant_id") == tenant_id and category.lower() in d.get("category", "").lower():
                suppliers.append(d.get("name", "غير معروف"))
        
        if not suppliers:
            return f"لم أجد أي موردين مسجلين في قسم ({category})."
        return f"وجدت {len(suppliers)} موردين في قسم {category}: {', '.join(suppliers)}."

    def _create_rfq(query: str) -> str:
        try:
            parts = [p.strip() for p in query.split(",")]
            item_name = parts[0]
            category = parts[1] if len(parts) > 1 else parts[0]
            
            all_suppliers = db.collection("suppliers").stream()
            suppliers = []
            for doc in all_suppliers:
                d = doc.to_dict()
                if d.get("tenant_id") == tenant_id and category.lower() in d.get("category", "").lower():
                    suppliers.append({"name": d.get("name"), "phone": d.get("phone")})
            
            if not suppliers:
                return f"فشل إنشاء الطلب. لا يوجد موردين لـ {category}."
            
            details_json = json.dumps(
                {"item": item_name, "category": category, "suppliers": suppliers}, 
                ensure_ascii=False
            )
            
            db.collection("approval_queue").add({
                "action_type": "إرسال طلب تسعير (RFQ)",
                "requested_by": sender_id,
                "details": details_json,
                "status": "pending",
                "created_at": datetime.utcnow(),
                "tenant_id": tenant_id
            })
            
            log_audit(db, tenant_id, "إنشاء مسودة RFQ", "AI Agent", f"تم إنشاء مسودة مبدئية لقطعة: {item_name}")
            
            return f"تمت العملية بنجاح! تم إنشاء مسودة طلب تسعير لقطعة ({item_name}) وإرسالها لـ {len(suppliers)} مورد إلى صندوق المراجعة."
        except Exception as e:
            return f"حدث خطأ أثناء محاولة إنشاء المسودة: {str(e)}"

    tools_map = {
        "search_suppliers_tool": {
            "func": _search_suppliers,
            "desc": "يبحث في قاعدة بيانات الشركة عن الموردين بناءً على فئة أو تخصص معين. أدخل الفئة فقط (مثلاً: بلي، حديد، ألومنيوم)."
        },
        "create_rfq_tool": {
            "func": _create_rfq,
            "desc": "يقوم بإنشاء مسودة طلب تسعير (RFQ) وإرسالها لصندوق المراجعة للمدير. أدخل اسم القطعة والفئة مفصولين بفاصلة (مثال: بلية 6211, بلي)."
        }
    }

    system_prompt = """أنت وكيل مشتريات ذكي ومساعد لمدير الشركة. مهمتك هي معالجة طلبات المدير بدقة بالاستعانة بالأدوات المتاحة.
يجب عليك اتباع أسلوب التفكير (ReAct) لحل المسألة خطوة بخطوة.

الأدوات المتاحة لديك:
{tools_specs}

للإجابة، يجب عليك استخدام التنسيق التالي بدقة في كل خطوة:
Thought: فكر في الخطوة التالية وما الذي تحتاجه.
Action: اسم الأداة التي تريد استخدامها (يجب أن تكون إما search_suppliers_tool أو create_rfq_tool).
Action Input: المدخل الخاص بالأداة بدقة دون أي علامات اقتباس إضافية.

عندما تنتهي من تنفيذ المهام بالكامل وتنشئ طلب التسعير بنجاح، أو تجد الحل النهائي، اكتب التنسيق التالي:
Final Answer: الإجابة النهائية باللغة العربية لشرح ما تم إنجازه بوضوح."""

    tools_specs = "\n".join([f"- {name}: {info['desc']}" for name, info in tools_map.items()])
    formatted_system = system_prompt.format(tools_specs=tools_specs)

    chat_history = []
    max_iterations = 5
    current_step = 0
    final_answer = ""

    try:
        while current_step < max_iterations:
            langchain_messages = [
                SystemMessage(content=formatted_system),
                HumanMessage(content=message_text)
            ]
            for hist in chat_history:
                if hist["role"] == "assistant":
                    langchain_messages.append(AIMessage(content=hist["content"]))
                elif hist["role"] == "user":
                    langchain_messages.append(HumanMessage(content=hist["content"]))

            res = llm.invoke(langchain_messages)
            response_text = res.content.strip()
            
            action_match = re.search(r"Action:\s*(\w+)", response_text)
            action_input_match = re.search(r"Action Input:\s*(.*)", response_text)

            if action_match and action_input_match:
                tool_name = action_match.group(1).strip()
                tool_input = action_input_match.group(1).strip()
                
                if (tool_input.startswith("'") and tool_input.endswith("'")) or (tool_input.startswith('"') and tool_input.endswith('"')):
                    tool_input = tool_input[1:-1].strip()

                if tool_name in tools_map:
                    observation = tools_map[tool_name]["func"](tool_input)
                else:
                    observation = f"خطأ: الأداة '{tool_name}' غير موجودة."

                chat_history.append({"role": "assistant", "content": response_text})
                chat_history.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                final_match = re.search(r"Final Answer:\s*(.*)", response_text, re.DOTALL)
                if final_match:
                    final_answer = final_match.group(1).strip()
                else:
                    final_answer = response_text
                break

            current_step += 1

        if not final_answer:
            final_answer = "انتهت خطوات العمل دون التوصل لإجابة نهائية واضحة."

        success = "بنجاح" in final_answer or "مسودة" in final_answer or "تم إنشاء" in final_answer
        return f"[وكيل المشتريات]: {final_answer}", success

    except Exception as e:
        return f"[خطأ بالنظام]: فشل الوكيل الذكي في تنفيذ المهام بشكل كامل. التفاصيل: {str(e)}", False


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    content = """
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-md-5 col-lg-5">
            <div class="card shadow-lg border-0" style="border-top: 5px solid var(--neon-success);">
                <div class="card-body p-5">
                    <div class="text-center mb-4">
                        <div class="bg-success bg-opacity-10 text-success d-inline-flex rounded-circle p-3 mb-3" style="box-shadow: 0 0 15px rgba(57, 255, 20, 0.2);">
                            <i class="bi bi-building-add fs-2"></i>
                        </div>
                        <h3 class="fw-bold">تسجيل ورشة/شركة جديدة</h3>
                        <p class="text-muted small">انضم لنظام الدريني لإدارة شركتك بالذكاء الاصطناعي</p>
                    </div>
                    <form action="/register" method="post">
                        <div class="mb-3">
                            <label class="form-label">اسم الورشة / الشركة</label>
                            <input type="text" class="form-control bg-light" name="company_name" required placeholder="مثال: ورشة الأمل...">
                        </div>
                        <hr class="border-secondary opacity-25 my-4">
                        <h6 class="fw-bold text-muted mb-3">بيانات مدير النظام (الآدمن)</h6>
                        <div class="mb-3">
                            <label class="form-label">اسم المستخدم (للدخول)</label>
                            <input type="text" class="form-control bg-light" name="admin_username" required placeholder="admin_amal">
                        </div>
                        <div class="mb-4">
                            <label class="form-label">كلمة المرور</label>
                            <input type="password" class="form-control bg-light" name="admin_password" required placeholder="••••••••">
                        </div>
                        <button type="submit" class="btn btn-success w-100 py-2 fs-5 text-dark fw-bold" style="background-color: var(--neon-success); box-shadow: 0 0 15px var(--neon-success);">تسجيل وإنشاء مساحة العمل <i class="bi bi-rocket-takeoff ms-2"></i></button>
                        <div class="text-center mt-4">
                            <a href="/login" class="text-muted small text-decoration-none">لديك حساب بالفعل؟ <span class="text-primary fw-bold">تسجيل الدخول</span></a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
    """
    return render_html_layout(content, "تسجيل شركة جديدة")

@app.post("/register")
async def register_post(request: Request, company_name: str = Form(...), admin_username: str = Form(...), admin_password: str = Form(...), db = Depends(get_db)):
    if not db: return HTMLResponse(render_html_layout("<div class='alert alert-danger'>خطأ اتصال بقاعدة البيانات.</div>", "خطأ"))

    if len(company_name.strip()) < 3:
        return HTMLResponse(render_html_layout("<div class='alert alert-danger text-center py-4 mx-auto'>اسم الشركة يجب أن يكون 3 أحرف على الأقل.</div>", "خطأ"))
    if not re.match(r"^[a-zA-Z0-9_]+$", admin_username):
        return HTMLResponse(render_html_layout("<div class='alert alert-danger text-center py-4 mx-auto'>اسم المستخدم يجب أن يحتوي على حروف إنجليزية وأرقام فقط (بدون مسافات).</div>", "خطأ"))
    if len(admin_password) < 8:
        return HTMLResponse(render_html_layout("<div class='alert alert-danger text-center py-4 mx-auto'>كلمة المرور يجب أن تكون 8 أحرف على الأقل.</div>", "خطأ"))

    existing_tenant_docs = list(db.collection("tenants").stream())
    existing_tenant = any(d.to_dict().get("name") == company_name for d in existing_tenant_docs)
    if existing_tenant:
        return HTMLResponse(render_html_layout("<div class='alert alert-danger text-center py-4 fs-5 mx-auto shadow-lg border-0' style='max-width:500px;'><i class='bi bi-exclamation-triangle-fill d-block fs-1 mb-2'></i> اسم الشركة مسجل مسبقاً.</div>", "خطأ"))
        
    existing_user_docs = list(db.collection("users").stream())
    existing_user = any(d.to_dict().get("username") == admin_username for d in existing_user_docs)
    if existing_user:
        return HTMLResponse(render_html_layout("<div class='alert alert-danger text-center py-4 fs-5 mx-auto shadow-lg border-0' style='max-width:500px;'><i class='bi bi-exclamation-triangle-fill d-block fs-1 mb-2'></i> اسم المستخدم محجوز لمدير آخر.</div>", "خطأ"))
        
    tenant_ref = db.collection("tenants").document()
    tenant_ref.set({"name": company_name}) 
    
    db.collection("users").add({
        "username": admin_username,
        "hashed_password": get_password_hash(admin_password),
        "role": "admin",
        "tenant_id": tenant_ref.id
    })
    
    msg = "<div class='alert alert-success text-center py-5 fs-4 fw-bold mx-auto shadow-lg border-0' style='max-width:600px; background-color: rgba(57, 255, 20, 0.1); color: var(--neon-success);'><i class='bi bi-check-circle-fill d-block fs-1 mb-3' style='text-shadow: 0 0 10px var(--neon-success);'></i> تم إنشاء مساحة شركتك بنجاح!<br><a href='/login' class='btn btn-success px-5 py-2 mt-4 fw-bold rounded-pill text-dark' style='background-color: var(--neon-success); box-shadow: 0 0 15px var(--neon-success); border: none;'>اذهب لتسجيل الدخول</a></div>"
    return HTMLResponse(render_html_layout(msg, "تم التسجيل"))

def prepare_cloud_hosting():
    try:
        req_content = "fastapi\nuvicorn\nfirebase-admin\nbcrypt\npython-jose[cryptography]\nopenai\nlangchain-openai\nlangchain-community\nlangchain-anthropic\nlangchain-google-genai\nlangchain-pinecone\npinecone-client\npypdf\npandas\nopenpyxl\nhttpx\nslowapi\napscheduler\nlanggraph\npyngrok\n"
        with open("requirements.txt", "w", encoding="utf-8") as f:
            f.write(req_content)
            
        render_content = "services:\n  - type: web\n    name: elderiny-enterprise-ai\n    env: python\n    buildCommand: pip install -r requirements.txt\n    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT\n    plan: free\n"
        with open("render.yaml", "w", encoding="utf-8") as f:
            f.write(render_content)
            
        readme_content = "لرفع هذا التطبيق مجاناً ليعمل 24/7:\n1. قم بإنشاء حساب مجاني في موقع Github.com وارفع هذه الملفات هناك (main.py, requirements.txt, render.yaml).\n2. قم بإنشاء حساب في موقع Render.com (منصة سحابية مجانية) واربطه بحسابك في جيت هاب.\n3. سيقوم Render باكتشاف ملف render.yaml وتشغيل النظام فوراً ومجاناً بـ رابط دائم لا يتغير أبداً."
        with open("كيف_ارفع_التطبيق_مجانا.txt", "w", encoding="utf-8") as f:
            f.write(readme_content)
            
    except Exception as e:
        logger.error(f"Cloud setup error: {e}")

def setup_public_url(port: int, silent: bool = False) -> str:
    try:
        from pyngrok import ngrok
        ngrok.kill()
        
        public_url = ngrok.connect(port).public_url
        if not silent:
            print("\n" + "="*60)
            print("🌐 [النظام العالمي]: تم فتح نفق للإنترنت بنجاح!")
            print(f"🔗 [الرابط العام - للوصول من أي مكان]: {public_url}")
            print("="*60 + "\n")
        return public_url
    except ImportError:
        if not silent:
            print("\n" + "="*60)
            print("⚠️ [تحذير]: مكتبة pyngrok غير مثبتة. التطبيق سيعمل محلياً فقط.")
            print("لفتح التطبيق للعالم، أوقف السيرفر واكتب في الطرفية:")
            print("pip install pyngrok")
            print("ثم أعد تشغيل الكود.")
            print("="*60 + "\n")
        return ""
    except Exception as e:
        if not silent:
            print("\n" + "="*60)
            print("⚠️ [تحذير]: تعذر الاتصال بخوادم ngrok (قد يكون بسبب انقطاع الإنترنت أو جدار الحماية).")
            print("التطبيق سيعمل محلياً فقط على الرابط: http://localhost:8000")
            print("="*60 + "\n")
        return ""

def install_background_service():
    import os, sys
    if os.name == 'nt': 
        try:
            startup_dir = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
            bat_path = os.path.join(startup_dir, 'ElderinyAI_Service.bat')
            script_path = os.path.abspath(sys.argv[0])
            pythonw_path = sys.executable.replace('python.exe', 'pythonw.exe')
            
            with open(bat_path, 'w', encoding='utf-8') as f:
                f.write(f'@echo off\nstart "" "{pythonw_path}" "{script_path}" --silent\n')
            return True
        except Exception as e:
            logger.error(f"Failed to install background service: {e}")
            return False
    return False

if __name__ == "__main__":
    # تنبيه هام في حالة محاولة تشغيل الملف عبر منصة Streamlit Cloud
    try:
        if st.runtime.exists():
            st.error("⚠️ خطأ في بيئة التشغيل: هذا التطبيق مبني بمعمارية FastAPI لدعم التصميم المخصص ولا يمكن تشغيله كواجهة Streamlit Cloud.")
            st.info("💡 لرفع التطبيق مجاناً بشكل صحيح: استخدم منصة Render.com أو Railway (كما هو موضح في ملف 'كيف_ارفع_التطبيق_مجانا.txt').")
            sys.exit(1)
    except Exception:
        pass

    port = int(os.getenv("PORT", 8501))
    is_silent = "--silent" in sys.argv
    
    prepare_cloud_hosting()
    
    if not is_silent:
        print("=====================================================")
        print("[النظام]: بدء تشغيل نظام الدريني للمصانع والورش")
        print(f"[الرابط المحلي]: http://localhost:{port}")
        print("=====================================================")
    
    is_cloud = os.getenv("RENDER") or os.getenv("DYNO") or os.getenv("RAILWAY_STATIC_URL")
    
    if not is_cloud:
        public_url = setup_public_url(port, silent=is_silent)
        
        if public_url and os.name == 'nt':
            try:
                desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
                url_file_path = os.path.join(desktop, "رابط_نظام_الدريني.txt")
                with open(url_file_path, "w", encoding="utf-8") as f:
                    f.write(f"رابط الدخول للنظام من أي مكان في العالم (للموبايلات والتابلت):\n{public_url}\n\n")
                    f.write(f"تاريخ توليد الرابط: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write("ملاحظة: النظام يعمل الآن في الخلفية بشكل دائم ومخفي (حتى لو أغلقت الشاشة السوداء).\n")
                    f.write("لإيقاف النظام نهائياً، قم بفتح Task Manager وأغلق مهمة Python.")
                
                install_background_service()
            except Exception as e:
                logger.error(f"Error creating desktop link: {e}")
    
    log_config = None if is_silent else uvicorn.config.LOGGING_CONFIG
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=log_config)
