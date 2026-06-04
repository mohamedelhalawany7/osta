import streamlit as st
import os
import json
import base64
import time
import uuid
import tempfile
from datetime import datetime
import bcrypt
from cryptography.fernet import Fernet

import firebase_admin
from firebase_admin import credentials, firestore

import openai
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage

# =====================================================================
# [القسم الأول]: إعدادات الصفحة و مكتبة الأيقونات المبرمجة (SVG Library)
# =====================================================================
st.set_page_config(
    page_title="AI Industrial Cloud | نظام الورشة المتكامل",
    layout="wide",
    initial_sidebar_state="expanded"
)

SVGS = {
    "logo": """<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>""",
    "chat": """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>""",
    "settings": """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>""",
    "dashboard": """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>""",
    "users": """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>""",
    "database": """<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>""",
    "user_profile": """<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#e4e4e7" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>""",
    "attach": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a1a1aa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>""",
    "mic": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>""",
    "image": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>""",
    "send": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fafafa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>""",
    "trash": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>""",
    "plus": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>""",
    "lock": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>""",
    "logout": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>""",
    "pdf": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>"""
}

def inject_enterprise_css():
    st.markdown("""
        <style>
        /* 1. استيراد الخطوط والإعدادات العالمية */
        @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Cairo', sans-serif !important;
        }

        .stApp {
            direction: rtl;
            background-color: #09090b; /* خلفية داكنة جداً مستوحاة من Vercel/Stripe Dark */
            color: #f4f4f5;
        }

        /* 2. تخصيص القائمة الجانبية (Sidebar) لتكون يميناً وبدون حدود مزعجة */
        [data-testid="stSidebar"] {
            left: auto !important;
            right: 0 !important;
            background-color: #111115 !important;
            border-left: 1px solid #27272a !important;
            border-right: none !important;
            padding-top: 2rem;
        }
        
        .stApp > header {
            background: transparent !important;
            box-shadow: none !important;
        }

        /* 3. تخصيص أزرار الراديو للتنقل (Navigation Menu) */
        div[role="radiogroup"] > label > div:first-child {
            display: none !important; /* إخفاء النقاط الدائرية بالكامل */
        }
        div[role="radiogroup"] {
            gap: 8px;
            padding: 10px;
        }
        div[role="radiogroup"] > label {
            background-color: transparent;
            border-radius: 8px;
            padding: 12px 16px;
            border: 1px solid transparent;
            transition: all 0.3s ease;
            cursor: pointer;
            width: 100%;
            display: flex;
            align-items: center;
        }
        div[role="radiogroup"] > label:hover {
            background-color: #18181b;
            border-color: #27272a;
            transform: translateX(-5px); /* حركة خفيفة لليمين عند التحويم */
        }
        /* تصميم الزر النشط */
        div[role="radiogroup"] > label[data-checked="true"] {
            background-color: rgba(59, 130, 246, 0.1);
            border: 1px solid rgba(59, 130, 246, 0.2);
            border-right: 4px solid #3b82f6; /* مؤشر أزرق على اليمين */
        }
        div[role="radiogroup"] label p {
            font-size: 16px !important;
            font-weight: 700 !important;
            color: #a1a1aa !important;
            margin: 0 !important;
        }
        div[role="radiogroup"] label[data-checked="true"] p {
            color: #3b82f6 !important;
        }

        /* 4. تخصيص حقول الإدخال (Inputs & TextAreas) */
        .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div {
            background-color: #18181b !important;
            border: 1px solid #27272a !important;
            color: #e4e4e7 !important;
            border-radius: 10px !important;
            padding: 14px 16px !important;
            font-size: 15px !important;
            transition: all 0.3s ease;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1) inset;
        }
        .stTextInput>div>div>input:focus, .stTextArea>div>div>textarea:focus {
            border-color: #3b82f6 !important;
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
            background-color: #111115 !important;
        }

        /* 5. تخصيص الأزرار (Buttons) */
        .stButton>button {
            background-color: #27272a !important;
            border: 1px solid #3f3f46 !important;
            color: #fafafa !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            font-size: 15px !important;
            padding: 8px 24px !important;
            transition: all 0.2s ease !important;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .stButton>button:hover {
            background-color: #3f3f46 !important;
            border-color: #52525b !important;
            transform: translateY(-2px);
        }
        /* الزر الأساسي (Primary) */
        .stButton>button[kind="primary"] {
            background-color: #3b82f6 !important;
            border: 1px solid #2563eb !important;
            color: #ffffff !important;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3) !important;
        }
        .stButton>button[kind="primary"]:hover {
            background-color: #2563eb !important;
            box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4) !important;
        }

        /* 6. تصميم الشات (WhatsApp / Enterprise Chat) */
        .stChatMessage {
            background-color: #111115 !important;
            border: 1px solid #27272a !important;
            border-radius: 16px !important;
            padding: 20px !important;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        }
        /* رسائل المستخدم (User Bubbles) */
        .stChatMessage:nth-child(even) {
            background-color: #18181b !important;
            border-right: 4px solid #3b82f6 !important; /* خط أزرق للتمييز */
            border-left: 1px solid #27272a !important;
        }
        /* رسائل المساعد (AI Bubbles) */
        .stChatMessage:nth-child(odd) {
            border-right: 4px solid #10b981 !important; /* خط أخضر للتمييز */
        }
        /* تخصيص محتوى الشات */
        .stChatMessage [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
            line-height: 1.6 !important;
            color: #e4e4e7 !important;
        }

        /* 7. تصميم التابات (Tabs) */
        [data-testid="stTabs"] button {
            font-family: 'Cairo', sans-serif !important;
            font-size: 16px !important;
            font-weight: 700 !important;
            color: #a1a1aa !important;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: #3b82f6 !important;
            border-bottom-color: #3b82f6 !important;
        }

        /* 8. تصميم المؤشرات (Metrics) */
        [data-testid="stMetricValue"] {
            font-size: 36px !important;
            font-weight: 800 !important;
            color: #ffffff !important;
        }
        [data-testid="stMetricLabel"] {
            color: #a1a1aa !important;
            font-size: 16px !important;
            font-weight: 600 !important;
        }
        [data-testid="metric-container"] {
            background-color: #111115;
            border: 1px solid #27272a;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }

        /* 9. إخفاء عناصر ستريمليت الافتراضية */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* 10. شريط التمرير المخصص (Scrollbar) */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #09090b; 
        }
        ::-webkit-scrollbar-thumb {
            background: #27272a; 
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #3f3f46; 
        }
        </style>
    """, unsafe_allow_html=True)

inject_enterprise_css()

# =====================================================================
# [القسم الثاني]: التشفير، المصادقة، والاتصال بقواعد البيانات (Firebase)
# =====================================================================
KEY_FILE = "system_secret.key"
def get_or_create_cipher():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    with open(KEY_FILE, "rb") as f:
        return Fernet(f.read())

cipher = get_or_create_cipher()

def encrypt_data(text: str) -> str:
    if not text: return ""
    return cipher.encrypt(text.encode()).decode()

def decrypt_data(encrypted_text: str) -> str:
    if not encrypted_text: return ""
    try:
        return cipher.decrypt(encrypted_text.encode()).decode()
    except Exception as e:
        return ""

FIREBASE_CREDS_FILE = "firebase_credentials.json"
db = None

def init_firebase_connection():
    global db
    if not firebase_admin._apps:
        try:
            # 1. القراءة التلقائية المباشرة من Streamlit Secrets
            if "FIREBASE_CREDENTIALS" in st.secrets:
                cred_dict = json.loads(st.secrets["FIREBASE_CREDENTIALS"])
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            # 2. كبديل: القراءة من ملف محلي إن وجد
            elif os.path.exists(FIREBASE_CREDS_FILE):
                cred = credentials.Certificate(FIREBASE_CREDS_FILE)
                firebase_admin.initialize_app(cred)
            else:
                st.error("لم يتم العثور على بيانات اتصال Firebase. يرجى إضافتها في Streamlit Secrets تحت اسم FIREBASE_CREDENTIALS.")
                st.stop()
        except Exception as e:
            st.error(f"خطأ في التهيئة السحابية: {str(e)}")
            st.stop()
            
    db = firestore.client()
    return True

# تشغيل التهيئة التلقائية الصامتة (بدون واجهة مستخدم للإعداد)
init_firebase_connection()

users_collection = db.collection("users")
if len(list(users_collection.limit(1).stream())) == 0:
    # إنشاء مدير افتراضي
    admin_hash = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
    users_collection.document("admin").set({
        "username": "admin",
        "password": admin_hash,
        "role": "admin",
        "created_at": datetime.utcnow()
    })
    # إنشاء عامل افتراضي
    worker_hash = bcrypt.hashpw("123".encode(), bcrypt.gensalt()).decode()
    users_collection.document("worker").set({
        "username": "worker",
        "password": worker_hash,
        "role": "worker",
        "created_at": datetime.utcnow()
    })

settings_doc = db.collection("system").document("global_settings")
if not settings_doc.get().exists:
    settings_doc.set({
        "llm_provider": "google",
        "llm_model": "gemini-1.5-flash",
        "openai_api_key": "",
        "google_api_key": "",
        "anthropic_api_key": "",
        "pinecone_api_key": "",
        "pinecone_index_name": "",
        "system_prompt": "أنت 'الأسطى سيد'، مهندس وصنايعي محترف في التشغيل المعدني وصيانة الماكينات والضواغط. أجب باختصار وبلهجة مصرية عامية، وقدم خطوات واضحة وعملية بناءً على المعطيات الفنية فقط."
    })

SYSTEM_CONFIG = settings_doc.get().to_dict()

if "current_user" not in st.session_state: st.session_state.current_user = None
if "active_chat_id" not in st.session_state: st.session_state.active_chat_id = None

# =====================================================================
# [القسم الثالث]: محركات الذكاء الاصطناعي والصوتيات (AI, RAG & Audio)
# =====================================================================
def perform_semantic_search(query: str, top_k: int = 3) -> str:
    api_key = decrypt_data(SYSTEM_CONFIG.get("pinecone_api_key", ""))
    index_name = SYSTEM_CONFIG.get("pinecone_index_name", "")
    openai_key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
    google_key = decrypt_data(SYSTEM_CONFIG.get("google_api_key", ""))

    if not api_key or not index_name:
        return "" # إرجاع نص فارغ إذا لم يتم إعداد Pinecone

    try:
        pc_client = PineconeClient(api_key=api_key)
        
        # اختيار نموذج التضمين (Embeddings) بناءً على المفاتيح المتوفرة
        embeddings_model = None
        if openai_key:
            embeddings_model = OpenAIEmbeddings(openai_api_key=openai_key)
        elif google_key:
            embeddings_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key)
        else:
            return ""

        vector_store = PineconeVectorStore(index=pc_client.Index(index_name), embedding=embeddings_model)
        search_results = vector_store.similarity_search(query, k=top_k)
        
        # دمج النصوص المستخرجة
        context_text = "\n---\n".join([doc.page_content for doc in search_results])
        return context_text
    except Exception as e:
        print(f"RAG Error: {e}")
        return ""

def transcribe_audio(audio_bytes: bytes) -> str:
    openai_key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
    if not openai_key:
        return "⚠️ النظام يحتاج إلى إعداد مفتاح OpenAI لتفعيل ميزة تحليل الصوت."
    
    try:
        client = openai.OpenAI(api_key=openai_key)
        # إنشاء ملف مؤقت لحفظ الصوت لمعالجته
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
            
        with open(temp_path, "rb") as af:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=af,
                language="ar" # إجبار التعرف على اللغة العربية بلهجاتها
            )
        os.unlink(temp_path) # حذف الملف المؤقت
        return transcript.text
    except Exception as e:
        return f"حدث خطأ أثناء تحليل الصوت: {str(e)}"

def generate_voice_reply(text: str):
    openai_key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
    if not openai_key: return None
    
    try:
        client = openai.OpenAI(api_key=openai_key)
        # تحديد حجم النص لتقليل تكلفة وسرعة الرد (أول 500 حرف فقط)
        truncated_text = text[:500] 
        response = client.audio.speech.create(
            model="tts-1",
            voice="onyx", # صوت Onyx يميل للعمق والرجولة (مناسب لأسطى الورشة)
            input=truncated_text
        )
        return response.content # إرجاع الـ bytes للصوت
    except Exception as e:
        print(f"TTS Error: {e}")
        return None

# =====================================================================
# [القسم الرابع]: واجهات النظام الشاملة (UI Pages & Modules)
# =====================================================================
def render_login_page():
    st.markdown("<div style='height: 15vh;'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown(f"""
            <div style="display: flex; flex-direction: column; align-items: center; margin-bottom: 30px;">
                <div style="background-color: rgba(59, 130, 246, 0.1); padding: 15px; border-radius: 20px; border: 1px solid rgba(59, 130, 246, 0.2); margin-bottom: 15px;">
                    {SVGS['logo']}
                </div>
                <h1 style="margin: 0; font-size: 28px; font-weight: 800; color: #ffffff;">نظام الورشة الذكي</h1>
                <p style="margin: 5px 0 0 0; font-size: 15px; color: #a1a1aa;">بوابة الدخول للمهندسين والفنيين</p>
            </div>
        """, unsafe_allow_html=True)
        
        with st.container():
            st.markdown("<div style='background-color: #111115; border: 1px solid #27272a; border-radius: 16px; padding: 30px; box-shadow: 0 10px 25px rgba(0,0,0,0.5);'>", unsafe_allow_html=True)
            
            username = st.text_input("معرف المستخدم (Username)", placeholder="أدخل اسم المستخدم...")
            password = st.text_input("كلمة المرور (Password)", type="password", placeholder="••••••••")
            
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
            
            if st.button("مصادقة وتسجيل الدخول", type="primary", use_container_width=True):
                if username and password:
                    with st.spinner("جاري التحقق من الهوية..."):
                        users_ref = db.collection("users").where("username", "==", username).get()
                        if users_ref:
                            user_data = users_ref[0].to_dict()
                            stored_hash = user_data.get("password", "")
                            if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                                st.session_state.current_user = {"id": users_ref[0].id, **user_data}
                                st.rerun()
                            else:
                                st.error("كلمة المرور غير صحيحة.")
                        else:
                            st.error("المستخدم غير موجود بالنظام.")
                else:
                    st.warning("يرجى تعبئة كافة الحقول.")
            st.markdown("</div>", unsafe_allow_html=True)

def render_chat_kiosk():
    # الهيدر المخصص للشات
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; background-color: #111115; border: 1px solid #27272a; padding: 15px 20px; border-radius: 16px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 15px;">
                <div style="background-color: rgba(59, 130, 246, 0.1); padding: 10px; border-radius: 12px; border: 1px solid rgba(59, 130, 246, 0.2);">
                    {SVGS['chat']}
                </div>
                <div>
                    <h2 style="margin: 0; font-size: 20px; font-weight: 800;">الأسطى المساعد (AI Agent)</h2>
                    <p style="margin: 0; font-size: 13px; color: #10b981; font-weight: 600;">● متصل بقاعدة المعرفة (RAG Online)</p>
                </div>
            </div>
            <div style="color: #a1a1aa; font-size: 14px;">
                <span style="background-color: #18181b; padding: 6px 12px; border-radius: 8px; border: 1px solid #27272a;">{SYSTEM_CONFIG.get('llm_model')}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    user_id = st.session_state.current_user["id"]

    # إدارة المحادثات السابقة (Sidebar Logic)
    with st.sidebar:
        st.markdown("<h3 style='margin-bottom: 15px;'>سجل الأعطال والمحادثات</h3>", unsafe_allow_html=True)
        
        if st.button("📝 فتح تذكرة جديدة", type="primary", use_container_width=True):
            new_session = db.collection("chat_sessions").add({
                "user_id": user_id,
                "title": "استفسار فني جديد",
                "updated_at": datetime.utcnow()
            })
            st.session_state.active_chat_id = new_session[1].id
            st.rerun()
            
        st.markdown("<hr style='border-color: #27272a;'>", unsafe_allow_html=True)
        
        # جلب الجلسات السابقة للمستخدم
        sessions = db.collection("chat_sessions").where("user_id", "==", user_id).order_by("updated_at", direction=firestore.Query.DESCENDING).stream()
        for s in sessions:
            s_dict = s.to_dict()
            session_title = s_dict.get("title", "محادثة")
            
            cols = st.columns([5, 1])
            # زر اختيار المحادثة
            if cols[0].button(session_title, key=f"sel_{s.id}", use_container_width=True):
                st.session_state.active_chat_id = s.id
                st.rerun()
            # زر حذف المحادثة
            if cols[1].button("🗑️", key=f"del_{s.id}", help="حذف المحادثة"):
                db.collection("chat_sessions").document(s.id).delete()
                # مسح رسائل الجلسة
                msg_docs = db.collection("chat_history").where("session_id", "==", s.id).stream()
                for m in msg_docs: m.reference.delete()
                
                if st.session_state.active_chat_id == s.id:
                    st.session_state.active_chat_id = None
                st.rerun()

    # إذا لم تكن هناك محادثة نشطة
    if not st.session_state.active_chat_id:
        st.info("الرجاء تحديد محادثة من القائمة أو بدء تذكرة استفسار جديدة.")
        return

    # عرض الرسائل في مساحة مخصصة قابلة للتمرير (Scrollable Container)
    chat_box = st.container(height=500, border=False)
    with chat_box:
        history_query = db.collection("chat_history").where("session_id", "==", st.session_state.active_chat_id).order_by("timestamp")
        messages = [doc.to_dict() for doc in history_query.stream()]
        
        if not messages:
            st.markdown("""
                <div style='text-align: center; color: #a1a1aa; padding-top: 100px;'>
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.5; margin-bottom: 10px;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                    <p>المساعد جاهز لاستقبال استفساراتك الفنية.<br>يمكنك الكتابة، تسجيل الصوت، أو رفع صورة للمشكلة.</p>
                </div>
            """, unsafe_allow_html=True)
            
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("image_base64"):
                    # عرض الصورة المرفقة
                    image_bytes = base64.b64decode(msg["image_base64"])
                    st.image(image_bytes, width=250)
                if msg.get("audio_bytes"):
                    # عرض مشغل الصوت للرد
                    st.audio(msg["audio_bytes"])

    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

    # شريط الإدخال المتقدم (Input Area)
    input_row = st.columns([1, 10])
    
    with input_row[0]:
        # القائمة المنبثقة للمرفقات (WhatsApp Style)
        with st.popover(SVGS["attach"], help="المرفقات"):
            st.markdown("<p style='font-weight: 700; color: #fafafa; border-bottom: 1px solid #27272a; padding-bottom: 10px; margin-bottom: 15px;'>إرفاق وسائط متعددة</p>", unsafe_allow_html=True)
            
            st.markdown(f"<div style='display:flex; align-items:center; gap:8px;'>{SVGS['mic']} <span style='font-weight:600;'>تسجيل صوتي للأسطى</span></div>", unsafe_allow_html=True)
            audio_upload = st.audio_input("", key="mic_input")
            
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
            
            st.markdown(f"<div style='display:flex; align-items:center; gap:8px;'>{SVGS['image']} <span style='font-weight:600;'>إرفاق صورة للعطل</span></div>", unsafe_allow_html=True)
            image_upload = st.file_uploader("", type=["jpg", "png", "jpeg"], key="img_input")

    with input_row[1]:
        text_input = st.chat_input("اشرح المشكلة أو العطل هنا...")

    # معالجة حدث الإرسال (Trigger)
    if text_input or audio_upload or image_upload:
        final_user_text = text_input or ""
        img_b64 = None
        
        # 1. معالجة الصورة
        if image_upload:
            img_bytes = image_upload.read()
            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
            if not final_user_text:
                final_user_text = "الرجاء تحليل المشكلة في هذه الصورة وإعطائي الحل."
                
        # 2. معالجة الصوت
        if audio_upload:
            with st.spinner("جاري تفريغ الصوت وتحويله لنص..."):
                transcribed_text = transcribe_audio(audio_upload.read())
                final_user_text = f"{final_user_text}\n{transcribed_text}".strip()

        # إظهار رسالة المستخدم فوراً
        with st.chat_message("user"):
            st.markdown(final_user_text)
            if img_b64:
                st.image(image_upload, width=200)

        # حفظ رسالة المستخدم في القاعدة
        db.collection("chat_history").add({
            "session_id": st.session_state.active_chat_id,
            "role": "user",
            "content": final_user_text,
            "image_base64": img_b64,
            "timestamp": datetime.utcnow()
        })
        
        # تحديث عنوان الجلسة إذا كانت جديدة
        session_ref = db.collection("chat_sessions").document(st.session_state.active_chat_id)
        current_title = session_ref.get().to_dict().get("title", "")
        if current_title == "استفسار فني جديد" and final_user_text:
            new_title = final_user_text[:40] + "..."
            session_ref.update({"title": new_title, "updated_at": datetime.utcnow()})
        else:
            session_ref.update({"updated_at": datetime.utcnow()})

        # 3. معالجة رد الذكاء الاصطناعي (LLM & RAG)
        with st.chat_message("assistant"):
            with st.spinner("الأسطى يبحث في الكتالوجات ويفكر في الحل..."):
                try:
                    # جلب السياق من Pinecone
                    rag_context = perform_semantic_search(final_user_text, top_k=3)
                    
                    # بناء رسالة النظام (System Prompt)
                    base_prompt = SYSTEM_CONFIG.get("system_prompt", "")
                    full_system_prompt = f"{base_prompt}\n\n=== معلومات مرجعية من الكتالوجات (RAG) ===\n{rag_context}\n==================================\nأجب بناءً على خبرتك وهذه المراجع إن لزم الأمر."
                    
                    # بناء الرسائل للموديل
                    messages = [SystemMessage(content=full_system_prompt)]
                    
                    content_block = [{"type": "text", "text": final_user_text}]
                    if img_b64:
                        content_block.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
                    
                    messages.append(HumanMessage(content=content_block))

                    # تهيئة محرك الـ LLM المختار
                    provider = SYSTEM_CONFIG.get("llm_provider", "google")
                    model_name = SYSTEM_CONFIG.get("llm_model", "gemini-1.5-flash")
                    llm = None
                    
                    if provider == "google":
                        key = decrypt_data(SYSTEM_CONFIG.get("google_api_key", ""))
                        if not key: raise ValueError("مفتاح Google API مفقود في الإعدادات.")
                        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=key, temperature=0.3)
                    elif provider == "openai":
                        key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
                        if not key: raise ValueError("مفتاح OpenAI API مفقود في الإعدادات.")
                        llm = ChatOpenAI(model_name=model_name, openai_api_key=key, temperature=0.3)
                    elif provider == "anthropic":
                        key = decrypt_data(SYSTEM_CONFIG.get("anthropic_api_key", ""))
                        if not key: raise ValueError("مفتاح Anthropic API مفقود في الإعدادات.")
                        llm = ChatAnthropic(model_name=model_name, api_key=key, temperature=0.3)
                    else:
                        raise ValueError("مزود خدمة غير معروف.")

                    # استقبال الرد بالبث المباشر (Streaming)
                    stream_response = llm.stream(messages)
                    final_ai_text = st.write_stream(stream_response)
                    
                    # توليد الصوت للرد (TTS)
                    audio_reply_bytes = generate_voice_reply(final_ai_text)
                    if audio_reply_bytes:
                        st.audio(audio_reply_bytes, format="audio/mp3")
                        
                    # حفظ رد المساعد في القاعدة
                    db.collection("chat_history").add({
                        "session_id": st.session_state.active_chat_id,
                        "role": "assistant",
                        "content": final_ai_text,
                        "audio_bytes": audio_reply_bytes,
                        "timestamp": datetime.utcnow()
                    })

                except Exception as e:
                    error_msg = f"تعذر إكمال العملية بسبب خطأ تقني: {str(e)}"
                    st.error(error_msg)
                    db.collection("chat_history").add({
                        "session_id": st.session_state.active_chat_id,
                        "role": "assistant",
                        "content": error_msg,
                        "timestamp": datetime.utcnow()
                    })

def render_dashboard():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background-color: rgba(16, 185, 129, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(16, 185, 129, 0.2);">
                {SVGS['dashboard']}
            </div>
            <div>
                <h1 style="margin: 0; font-size: 24px;">لوحة المؤشرات والتحكم (Dashboard)</h1>
                <p style="margin: 0; color: #a1a1aa; font-size: 14px;">نظرة عامة على أداء النظام واستخدام الورشة</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # حساب الإحصائيات من Firebase
    total_users = len(list(db.collection("users").stream()))
    total_sessions = len(list(db.collection("chat_sessions").stream()))
    total_docs = len(list(db.collection("knowledge_docs").stream()))
    total_messages = len(list(db.collection("chat_history").stream()))
    
    # عرض الـ Metrics بتصميم مميز
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True)
        st.metric("إجمالي العمال", f"{total_users}")
        st.markdown("</div>", unsafe_allow_html=True)
    with m2:
        st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True)
        st.metric("تذاكر الأعطال", f"{total_sessions}")
        st.markdown("</div>", unsafe_allow_html=True)
    with m3:
        st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True)
        st.metric("الكتالوجات المرفوعة", f"{total_docs}")
        st.markdown("</div>", unsafe_allow_html=True)
    with m4:
        st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True)
        st.metric("عمليات الذكاء الاصطناعي", f"{total_messages}")
        st.markdown("</div>", unsafe_allow_html=True)
        
    st.markdown("<hr style='border-color: #27272a; margin: 40px 0;'>", unsafe_allow_html=True)
    
    # رسم بياني توضيحي (استخدام رسوم ستريمليت المدمجة)
    st.subheader("نشاط النظام")
    chart_data = {"الاستعلامات": [10, 25, 15, 30, 45, 20, 60], "حلول الأعطال": [8, 20, 12, 28, 40, 18, 55]}
    st.line_chart(chart_data, color=["#3b82f6", "#10b981"])

def render_user_management():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background-color: rgba(245, 158, 11, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(245, 158, 11, 0.2);">
                {SVGS['users']}
            </div>
            <div>
                <h1 style="margin: 0; font-size: 24px;">إدارة الأفراد والصلاحيات</h1>
                <p style="margin: 0; color: #a1a1aa; font-size: 14px;">إضافة وحذف حسابات العمال والمهندسين</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("إضافة فرد جديد للمنظومة", expanded=True):
        with st.form("add_user_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            new_username = c1.text_input("معرف الموظف (Username)")
            new_password = c2.text_input("كلمة المرور", type="password")
            new_role = c3.selectbox("مستوى الصلاحية", ["worker", "admin"], format_func=lambda x: "مهندس إداري" if x=="admin" else "صنايعي / عامل")
            
            submit_btn = st.form_submit_button("تسجيل الحساب", type="primary")
            if submit_btn:
                if new_username and new_password:
                    # التحقق من عدم وجود الاسم مسبقاً
                    existing = list(db.collection("users").where("username", "==", new_username).stream())
                    if existing:
                        st.error("هذا المعرف مستخدم بالفعل.")
                    else:
                        hashed_pw = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
                        db.collection("users").add({
                            "username": new_username,
                            "password": hashed_pw,
                            "role": new_role,
                            "created_at": datetime.utcnow()
                        })
                        st.success("تم تسجيل الفرد بنجاح.")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.warning("يجب تعبئة المعرف وكلمة المرور.")

    st.markdown("<h3 style='margin-top: 30px;'>قائمة الأفراد المسجلين</h3>", unsafe_allow_html=True)
    users_list = list(db.collection("users").order_by("created_at").stream())
    
    for u in users_list:
        u_data = u.to_dict()
        with st.container():
            st.markdown("<div style='background-color: #111115; border: 1px solid #27272a; border-radius: 8px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;'>", unsafe_allow_html=True)
            colA, colB, colC = st.columns([3, 2, 1])
            
            with colA:
                icon = SVGS['lock'] if u_data['role'] == 'admin' else SVGS['user_profile']
                st.markdown(f"<div style='display:flex; align-items:center; gap:10px;'><div style='width:24px;'>{icon}</div> <span style='font-weight:700; font-size:16px;'>{u_data['username']}</span></div>", unsafe_allow_html=True)
            with colB:
                role_label = "إدارة عليا" if u_data['role'] == 'admin' else "قسم التشغيل"
                color = "#3b82f6" if u_data['role'] == 'admin' else "#a1a1aa"
                st.markdown(f"<span style='color:{color}; font-weight:600;'>{role_label}</span>", unsafe_allow_html=True)
            with colC:
                if u_data['username'] != "admin": # حماية حساب الأدمن الرئيسي
                    if st.button("حذف الحساب", key=f"del_user_{u.id}", help="إزالة الفرد نهائياً"):
                        db.collection("users").document(u.id).delete()
                        st.toast("تم إزالة الحساب بنجاح.")
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

def render_knowledge_base():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background-color: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(139, 92, 246, 0.2);">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"></path></svg>
            </div>
            <div>
                <h1 style="margin: 0; font-size: 24px;">الكتالوجات والذاكرة الفنية (RAG)</h1>
                <p style="margin: 0; color: #a1a1aa; font-size: 14px;">رفع وتدريب المساعد على كتالوجات الـ CNC والضواغط</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # قسم رفع الملفات ومعالجتها
    st.markdown("<div style='background-color: #111115; border: 1px dashed #3f3f46; border-radius: 16px; padding: 30px; text-align: center;'>", unsafe_allow_html=True)
    st.markdown(f"<div style='display:flex; justify-content:center; margin-bottom:15px;'>{SVGS['pdf']}</div>", unsafe_allow_html=True)
    
    uploaded_files = st.file_uploader("قم بسحب وإفلات ملفات الـ PDF أو النصوص هنا", accept_multiple_files=True, type=['pdf', 'txt'])
    
    if st.button("بدء المعالجة والحقن في قاعدة البيانات السحابية (Pinecone)", type="primary"):
        if not uploaded_files:
            st.warning("يرجى اختيار ملفات أولاً لإتمام العملية.")
            return

        api_key = decrypt_data(SYSTEM_CONFIG.get("pinecone_api_key", ""))
        index_name = SYSTEM_CONFIG.get("pinecone_index_name", "")
        openai_key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
        google_key = decrypt_data(SYSTEM_CONFIG.get("google_api_key", ""))

        if not api_key or not index_name:
            st.error("مفاتيح Pinecone غير معدة! يرجى تكوينها من نافذة الإعدادات أولاً.")
            return

        # تحديد محرك التضمين
        embeddings = None
        if openai_key:
            embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
        elif google_key:
            embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key)
        
        if not embeddings:
            st.error("مفاتيح الـ Embeddings (OpenAI أو Google) غير متوفرة.")
            return

        pc = PineconeClient(api_key=api_key)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"جاري قراءة ومعالجة: {file.name} ...")
            
            text_content = ""
            try:
                if file.name.endswith('.pdf'):
                    pdf_reader = PdfReader(file)
                    for page in pdf_reader.pages:
                        extracted = page.extract_text()
                        if extracted: text_content += extracted + "\n"
                else:
                    text_content = file.read().decode('utf-8')

                if not text_content.strip():
                    st.warning(f"الملف {file.name} فارغ أو لا يمكن قراءة نصوصه.")
                    continue

                status_text.text(f"تقطيع النص (Chunking) للملف: {file.name} ...")
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
                chunks = text_splitter.split_text(text_content)
                
                # إضافة Metadata
                metadatas = [{"source": file.name, "chunk_id": idx} for idx in range(len(chunks))]
                
                status_text.text(f"توليد المتجهات (Embeddings) والرفع لـ Pinecone للملف: {file.name} ...")
                vector_store = PineconeVectorStore(index=pc.Index(index_name), embedding=embeddings)
                vector_store.add_texts(texts=chunks, metadatas=metadatas)
                
                # توثيق العملية في Firebase
                db.collection("knowledge_docs").add({
                    "filename": file.name,
                    "chunks_count": len(chunks),
                    "uploaded_at": datetime.utcnow()
                })
                
                progress_bar.progress((i + 1) / total_files)
                
            except Exception as e:
                st.error(f"فشل في معالجة {file.name}: {str(e)}")
                
        status_text.text("تم اكتمال عملية الفهرسة بنجاح!")
        st.success("أصبحت الكتالوجات الآن في ذاكرة المساعد الذكي.")
    st.markdown("</div>", unsafe_allow_html=True)

    # عرض الملفات المؤرشفة
    st.markdown("<h3 style='margin-top: 40px;'>أرشيف الكتالوجات المحفوظة</h3>", unsafe_allow_html=True)
    docs_ref = db.collection("knowledge_docs").order_by("uploaded_at", direction=firestore.Query.DESCENDING).stream()
    
    for doc in docs_ref:
        d_info = doc.to_dict()
        with st.container():
            st.markdown("<div style='background-color: #18181b; border: 1px solid #27272a; border-radius: 8px; padding: 12px 20px; margin-bottom: 10px;'>", unsafe_allow_html=True)
            colA, colB, colC = st.columns([4, 2, 1])
            colA.markdown(f"<span style='font-weight:700; color:#fafafa;'>{d_info.get('filename')}</span>", unsafe_allow_html=True)
            colB.markdown(f"<span style='color:#a1a1aa; font-size:14px;'>عدد الأجزاء: {d_info.get('chunks_count', 0)}</span>", unsafe_allow_html=True)
            if colC.button("إزالة السجل", key=f"del_doc_{doc.id}"):
                db.collection("knowledge_docs").document(doc.id).delete()
                st.toast("تم حذف السجل من لوحة التحكم (تحتاج لحذف الـ Vectors من منصة Pinecone يدوياً).")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

def render_settings():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background-color: rgba(236, 72, 153, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(236, 72, 153, 0.2);">
                {SVGS['settings']}
            </div>
            <div>
                <h1 style="margin: 0; font-size: 24px;">تكوين النظام الأساسي (Global Config)</h1>
                <p style="margin: 0; color: #a1a1aa; font-size: 14px;">إدارة مفاتيح الـ API، الموديلات، وهندسة الأوامر</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["🤖 إعدادات الذكاء الاصطناعي", "🌲 إعدادات Pinecone (RAG)", "🧠 شخصية המساعد (Prompt)"])

    with st.form("master_settings_form"):
        with tab1:
            st.markdown("### مزودي الخدمة (LLM Providers)")
            col1, col2 = st.columns(2)
            
            provider_options = ["google", "openai", "anthropic"]
            current_provider = SYSTEM_CONFIG.get("llm_provider", "google")
            selected_provider = col1.selectbox("المحرك الأساسي للردود", provider_options, index=provider_options.index(current_provider) if current_provider in provider_options else 0)
            
            model_name = col2.text_input("اسم الموديل المخصص", value=SYSTEM_CONFIG.get("llm_model", "gemini-1.5-flash"))
            
            st.markdown("### مفاتيح التشفير السحابية (API Keys)")
            st.info("يتم تشفير هذه المفاتيح وتخزينها بأمان تام في قاعدة البيانات باستخدام خوارزمية Fernet.")
            
            google_key = st.text_input("Google Gemini API Key", value=decrypt_data(SYSTEM_CONFIG.get("google_api_key", "")), type="password")
            openai_key = st.text_input("OpenAI API Key (إلزامي لميزة الصوت Whisper/TTS)", value=decrypt_data(SYSTEM_CONFIG.get("openai_api_key", "")), type="password")
            anthropic_key = st.text_input("Anthropic Claude API Key", value=decrypt_data(SYSTEM_CONFIG.get("anthropic_api_key", "")), type="password")

        with tab2:
            st.markdown("### قاعدة البيانات الاتجاهية للذاكرة (Vector DB)")
            pinecone_key = st.text_input("Pinecone API Key", value=decrypt_data(SYSTEM_CONFIG.get("pinecone_api_key", "")), type="password")
            pinecone_idx = st.text_input("Pinecone Index Name (اسم الفهرس)", value=SYSTEM_CONFIG.get("pinecone_index_name", ""))

        with tab3:
            st.markdown("### هندسة شخصية المساعد (System Prompt Engineering)")
            st.caption("التعليمات المكتوبة هنا هي التي ستوجه أسلوب الرد، اللهجة، وطريقة التفكير للمساعد.")
            system_prompt = st.text_area("التعليمات الشاملة (System Prompt)", value=SYSTEM_CONFIG.get("system_prompt", ""), height=250)

        st.markdown("<hr style='border-color: #27272a;'>", unsafe_allow_html=True)
        
        if st.form_submit_button("حفظ الإعدادات الشاملة بالسحابة", type="primary"):
            with st.spinner("جاري تشفير البيانات وحفظها..."):
                settings_doc.update({
                    "llm_provider": selected_provider,
                    "llm_model": model_name,
                    "google_api_key": encrypt_data(google_key),
                    "openai_api_key": encrypt_data(openai_key),
                    "anthropic_api_key": encrypt_data(anthropic_key),
                    "pinecone_api_key": encrypt_data(pinecone_key),
                    "pinecone_index_name": pinecone_idx,
                    "system_prompt": system_prompt
                })
            st.success("تم تحديث إعدادات النظام بنجاح وتطبيقها على كافة المستخدمين.")
            time.sleep(1)
            st.rerun()

# =====================================================================
# [القسم الخامس]: موجه الصفحات والهيكل الأساسي (Main Router & Layout)
# =====================================================================
def main_app_router():
    # التحقق من الجلسة
    if not st.session_state.current_user:
        render_login_page()
        return

    user_info = st.session_state.current_user
    is_admin = user_info.get("role") == "admin"

    # بناء القائمة الجانبية المتقدمة (Sidebar Navbar)
    with st.sidebar:
        # User Profile Header
        st.markdown(f"""
            <div style="background-color: #18181b; padding: 20px; border-radius: 16px; border: 1px solid #27272a; margin-bottom: 25px; text-align: center;">
                <div style="margin-bottom: 10px; display: flex; justify-content: center;">
                    {SVGS['user_profile']}
                </div>
                <h3 style="margin: 0; color: #ffffff; font-size: 18px;">{user_info.get('username')}</h3>
                <span style="background-color: {'rgba(59, 130, 246, 0.2)' if is_admin else 'rgba(161, 161, 170, 0.1)'}; color: {'#3b82f6' if is_admin else '#a1a1aa'}; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; margin-top: 8px; display: inline-block;">
                    {'مدير النظام' if is_admin else 'صنايعي تشغيل'}
                </span>
            </div>
            <p style="color: #52525b; font-size: 12px; font-weight: 800; margin-bottom: 5px; padding-right: 10px;">روابط المنظومة</p>
        """, unsafe_allow_html=True)

        # تحديد خيارات القائمة بناءً على الصلاحيات
        nav_options = ["المساعد الفني (Chat)"]
        if is_admin:
            nav_options.extend(["لوحة المؤشرات", "المستخدمين والصلاحيات", "إدارة الكتالوجات (RAG)", "تكوين النظام (Settings)"])

        selected_page = st.radio("Navigation", nav_options, label_visibility="collapsed")
        
        st.markdown("<div style='flex-grow: 1; height: 50px;'></div>", unsafe_allow_html=True)
        st.markdown("<hr style='border-color: #27272a;'>", unsafe_allow_html=True)
        
        # زر تسجيل الخروج المخصص
        if st.button("إنهاء الجلسة الآمنة", use_container_width=True):
            st.session_state.current_user = None
            st.session_state.active_chat_id = None
            st.rerun()

    # محرك عرض الصفحات (Page Renderer)
    if selected_page == "المساعد الفني (Chat)":
        render_chat_kiosk()
    elif selected_page == "لوحة المؤشرات":
        render_dashboard()
    elif selected_page == "المستخدمين والصلاحيات":
        render_user_management()
    elif selected_page == "إدارة الكتالوجات (RAG)":
        render_knowledge_base()
    elif selected_page == "تكوين النظام (Settings)":
        render_settings()

# نقطة إقلاع التطبيق
if __name__ == "__main__":
    main_app_router()
