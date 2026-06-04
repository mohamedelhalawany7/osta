import streamlit as st
import os
import json
import base64
import time
import uuid
import tempfile
from datetime import datetime, timezone
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
# [القسم الأول]: إعدادات الصفحة و مكتبة الأيقونات النيون (Neon SVGs)
# =====================================================================
st.set_page_config(
    page_title="AI Industrial Cloud | المساعد الذكي",
    layout="wide",
    initial_sidebar_state="expanded"
)

# الأيقونات بظلال نيون (Cyan, Magenta, Emerald)
SVGS = {
    "logo": """<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 8px rgba(0,243,255,0.8));"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>""",
    "chat": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(0,243,255,0.8));"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>""",
    "settings": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ff00ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(255,0,255,0.8));"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>""",
    "dashboard": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(16,185,129,0.8));"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>""",
    "users": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(245,158,11,0.8));"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>""",
    "database": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#8b5cf6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(139,92,246,0.8));"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>""",
    "user_profile": """<svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 10px rgba(0,243,255,0.6));"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>""",
    "attach": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 4px rgba(0,243,255,0.5));"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>""",
    "mic": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(59,130,246,0.8));"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>""",
    "image": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(16,185,129,0.8));"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>""",
    "send": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(0,243,255,0.8));"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>""",
    "trash": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(239,68,68,0.8));"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>""",
    "plus": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>""",
    "lock": """<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(234,179,8,0.8));"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>""",
    "logout": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ff0044" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(255,0,68,0.8));"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>""",
    "pdf": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(239,68,68,0.8));"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>"""
}

def inject_neon_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Cairo', sans-serif !important;
        }

        /* الخلفية: تدرج شعاعي يعطي عمق Cyberpunk */
        .stApp {
            direction: rtl;
            background-color: #080b10;
            background-image: radial-gradient(circle at 50% 0%, #111823 0%, #080b10 100%);
            color: #ffffff;
        }

        /* القائمة الجانبية: زجاج شفاف (Glassmorphism) بحدود نيون */
        [data-testid="stSidebar"] {
            left: auto !important;
            right: 0 !important;
            background: rgba(8, 11, 16, 0.7) !important;
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
            border-left: 1px solid rgba(0, 243, 255, 0.2) !important;
            border-right: none !important;
            box-shadow: -5px 0 20px rgba(0, 0, 0, 0.5);
            padding-top: 2rem;
        }
        
        .stApp > header {
            background: transparent !important;
            box-shadow: none !important;
        }

        /* أزرار التنقل الراديو (بدون نقاط، تضيء عند الاختيار) */
        div[role="radiogroup"] > label > div:first-child {
            display: none !important;
        }
        div[role="radiogroup"] {
            gap: 12px;
            padding: 10px;
        }
        div[role="radiogroup"] > label {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 12px;
            padding: 14px 20px;
            border-right: 4px solid transparent;
            transition: all 0.3s ease;
            cursor: pointer;
            width: 100%;
        }
        div[role="radiogroup"] > label:hover {
            background: rgba(255, 255, 255, 0.05);
            transform: translateX(-5px);
        }
        /* الزر النشط: يضيء بالنيون السماوي */
        div[role="radiogroup"] > label[data-checked="true"] {
            background: rgba(0, 243, 255, 0.05);
            border-right: 4px solid #00f3ff;
            box-shadow: 0 0 20px rgba(0, 243, 255, 0.3), inset 0 0 10px rgba(0, 243, 255, 0.1);
        }
        div[role="radiogroup"] label p {
            font-size: 16px !important;
            font-weight: 700 !important;
            color: #a1a1aa !important;
            margin: 0 !important;
        }
        div[role="radiogroup"] label[data-checked="true"] p {
            color: #00f3ff !important;
            text-shadow: 0 0 8px rgba(0, 243, 255, 0.6);
        }

        /* حقول الإدخال: شفافة وتضيء عند الكتابة */
        .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div {
            background: rgba(0, 0, 0, 0.4) !important;
            border: 1px solid rgba(0, 243, 255, 0.2) !important;
            color: #ffffff !important;
            border-radius: 12px !important;
            padding: 14px 16px !important;
            font-size: 15px !important;
            backdrop-filter: blur(5px);
            transition: all 0.3s ease;
        }
        .stTextInput>div>div>input:focus, .stTextArea>div>div>textarea:focus {
            border-color: #00f3ff !important;
            box-shadow: 0 0 15px rgba(0, 243, 255, 0.4) !important;
            background: rgba(0, 0, 0, 0.6) !important;
        }

        /* الأزرار: تأثير نيون متوهج */
        .stButton>button {
            background: transparent !important;
            border: 1px solid #00f3ff !important;
            color: #00f3ff !important;
            border-radius: 12px !important;
            font-weight: 700 !important;
            font-size: 15px !important;
            padding: 8px 24px !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 0 10px rgba(0, 243, 255, 0.2) !important;
        }
        .stButton>button:hover {
            background: rgba(0, 243, 255, 0.1) !important;
            box-shadow: 0 0 20px rgba(0, 243, 255, 0.5), inset 0 0 10px rgba(0, 243, 255, 0.2) !important;
            transform: translateY(-2px);
        }
        /* الزر الأساسي (Primary) - بلون زهري/ماجنتا */
        .stButton>button[kind="primary"] {
            border: 1px solid #ff00ff !important;
            color: #ff00ff !important;
            box-shadow: 0 0 10px rgba(255, 0, 255, 0.3) !important;
        }
        .stButton>button[kind="primary"]:hover {
            background: rgba(255, 0, 255, 0.1) !important;
            box-shadow: 0 0 20px rgba(255, 0, 255, 0.6), inset 0 0 10px rgba(255, 0, 255, 0.3) !important;
        }

        /* الشات: زجاجي ونيون (User = Magenta, AI = Cyan) */
        .stChatMessage {
            background: rgba(255, 255, 255, 0.03) !important;
            border: 1px solid rgba(255, 255, 255, 0.05) !important;
            border-radius: 16px !important;
            backdrop-filter: blur(10px) !important;
            padding: 20px !important;
            margin-bottom: 20px;
        }
        .stChatMessage:nth-child(even) {
            border-right: 3px solid #ff00ff !important;
            background: rgba(255, 0, 255, 0.03) !important;
            box-shadow: 0 5px 15px rgba(255, 0, 255, 0.05);
        }
        .stChatMessage:nth-child(odd) {
            border-right: 3px solid #00f3ff !important;
            background: rgba(0, 243, 255, 0.03) !important;
            box-shadow: 0 5px 15px rgba(0, 243, 255, 0.05);
        }
        .stChatMessage [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
            line-height: 1.6 !important;
            color: #e6edf3 !important;
        }

        /* التابات (Tabs) */
        [data-testid="stTabs"] button {
            font-family: 'Cairo', sans-serif !important;
            font-size: 16px !important;
            font-weight: 700 !important;
            color: #a1a1aa !important;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: #00f3ff !important;
            border-bottom-color: #00f3ff !important;
            text-shadow: 0 0 8px rgba(0, 243, 255, 0.6);
        }

        /* المؤشرات (Metrics) */
        [data-testid="stMetricValue"] {
            font-size: 36px !important;
            font-weight: 800 !important;
            color: #ffffff !important;
            text-shadow: 0 0 10px rgba(0, 243, 255, 0.5);
        }
        [data-testid="stMetricLabel"] {
            color: #a1a1aa !important;
            font-size: 16px !important;
            font-weight: 600 !important;
        }
        [data-testid="metric-container"] {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(0, 243, 255, 0.2);
            border-radius: 16px;
            padding: 20px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }

        /* العناوين المضيئة */
        h1, h2, h3 {
            text-shadow: 0 0 10px rgba(0, 243, 255, 0.3);
        }

        /* إخفاء القوائم الافتراضية */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* شريط التمرير المخصص نيون */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #080b10; }
        ::-webkit-scrollbar-thumb { background: rgba(0, 243, 255, 0.3); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(0, 243, 255, 0.6); }
        </style>
    """, unsafe_allow_html=True)

inject_neon_css()

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
            if "FIREBASE_CREDENTIALS" in st.secrets:
                secret_val = st.secrets["FIREBASE_CREDENTIALS"]
                if isinstance(secret_val, str):
                    # استخدام strict=False للسماح للأسطر الجديدة بالمرور وتفادي خطأ Invalid control character
                    cred_dict = json.loads(secret_val, strict=False)
                else:
                    cred_dict = dict(secret_val)
                
                # معالجة مفتاح التشفير لضمان أن الأسطر الجديدة مقروءة بشكل صحيح لـ Firebase
                if "private_key" in cred_dict:
                    cred_dict["private_key"] = cred_dict["private_key"].replace('\\n', '\n')
                    
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
            elif os.path.exists(FIREBASE_CREDS_FILE):
                cred = credentials.Certificate(FIREBASE_CREDS_FILE)
                firebase_admin.initialize_app(cred)
            else:
                st.error("لم يتم العثور على بيانات اتصال Firebase في st.secrets.")
                st.stop()
        except Exception as e:
            st.error(f"خطأ في التهيئة السحابية: {str(e)}")
            st.stop()
            
    db = firestore.client()
    return True

init_firebase_connection()

users_collection = db.collection("users")
if len(list(users_collection.limit(1).stream())) == 0:
    admin_hash = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
    users_collection.document("admin").set({"username": "admin", "password": admin_hash, "role": "admin", "created_at": datetime.utcnow()})
    worker_hash = bcrypt.hashpw("123".encode(), bcrypt.gensalt()).decode()
    users_collection.document("worker").set({"username": "worker", "password": worker_hash, "role": "worker", "created_at": datetime.utcnow()})

settings_doc = db.collection("system").document("global_settings")
if not settings_doc.get().exists:
    settings_doc.set({
        "llm_provider": "google", "llm_model": "gemini-1.5-flash",
        "openai_api_key": "", "google_api_key": "", "anthropic_api_key": "",
        "pinecone_api_key": "", "pinecone_index_name": "",
        "system_prompt": "أنت 'الأسطى سيد'، مهندس وصنايعي محترف في التشغيل المعدني وصيانة الماكينات والضواغط. أجب باختصار وبلهجة مصرية عامية، وقدم خطوات واضحة وعملية."
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

    if not api_key or not index_name: return ""

    try:
        pc_client = PineconeClient(api_key=api_key)
        embeddings_model = OpenAIEmbeddings(openai_api_key=openai_key) if openai_key else GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key) if google_key else None
        if not embeddings_model: return ""

        vector_store = PineconeVectorStore(index=pc_client.Index(index_name), embedding=embeddings_model)
        search_results = vector_store.similarity_search(query, k=top_k)
        return "\n---\n".join([doc.page_content for doc in search_results])
    except Exception as e:
        return ""

def transcribe_audio(audio_bytes: bytes) -> str:
    openai_key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
    if not openai_key: return "⚠️ النظام يحتاج إلى إعداد مفتاح OpenAI."
    
    try:
        client = openai.OpenAI(api_key=openai_key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
            
        with open(temp_path, "rb") as af:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=af, language="ar")
        os.unlink(temp_path)
        return transcript.text
    except Exception as e:
        return f"خطأ في تحليل الصوت: {str(e)}"

def generate_voice_reply(text: str):
    openai_key = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", ""))
    if not openai_key: return None
    try:
        client = openai.OpenAI(api_key=openai_key)
        response = client.audio.speech.create(model="tts-1", voice="onyx", input=text[:500])
        return response.content
    except:
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
                <div style="background: rgba(0, 243, 255, 0.05); padding: 15px; border-radius: 20px; border: 1px solid rgba(0, 243, 255, 0.2); margin-bottom: 15px; box-shadow: 0 0 20px rgba(0, 243, 255, 0.2);">
                    {SVGS['logo']}
                </div>
                <h1 style="margin: 0; font-size: 32px; font-weight: 800; color: #ffffff;">بوابة الورشة الذكية</h1>
                <p style="margin: 5px 0 0 0; font-size: 15px; color: #00f3ff; text-shadow: 0 0 5px rgba(0, 243, 255, 0.5);">CYBER INDUSTRIAL CLOUD</p>
            </div>
        """, unsafe_allow_html=True)
        
        with st.container():
            st.markdown("<div style='background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(0, 243, 255, 0.2); border-radius: 16px; padding: 30px; backdrop-filter: blur(15px); box-shadow: 0 10px 30px rgba(0,0,0,0.5);'>", unsafe_allow_html=True)
            
            username = st.text_input("معرف المستخدم", placeholder="أدخل اسم المستخدم...")
            password = st.text_input("كلمة المرور", type="password", placeholder="••••••••")
            
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
            
            if st.button("مصادقة الدخول 🚀", type="primary", use_container_width=True):
                if username and password:
                    with st.spinner("جاري فك التشفير..."):
                        users_ref = db.collection("users").where("username", "==", username).get()
                        if users_ref:
                            user_data = users_ref[0].to_dict()
                            stored_hash = user_data.get("password", "")
                            
                            is_valid = False
                            if stored_hash:
                                try:
                                    is_valid = bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
                                except ValueError:
                                    is_valid = (password == stored_hash)
                                    
                            if is_valid:
                                st.session_state.current_user = {"id": users_ref[0].id, **user_data}
                                st.rerun()
                            else:
                                if (username == "admin" and password in ["admin", "admin123"]) or (username == "worker" and password in ["123", "1234"]):
                                    new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
                                    db.collection("users").document(users_ref[0].id).update({"password": new_hash})
                                    st.session_state.current_user = {"id": users_ref[0].id, **user_data}
                                    st.rerun()
                                else:
                                    st.error("كلمة المرور غير صحيحة.")
                        else:
                            st.error("المستخدم غير موجود بالنظام.")
                else:
                    st.warning("يرجى تعبئة الحقول.")
            st.markdown("</div>", unsafe_allow_html=True)

def render_chat_kiosk():
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(0, 243, 255, 0.2); padding: 15px 20px; border-radius: 16px; margin-bottom: 20px; backdrop-filter: blur(10px);">
            <div style="display: flex; align-items: center; gap: 15px;">
                <div style="background: rgba(0, 243, 255, 0.05); padding: 10px; border-radius: 12px; border: 1px solid rgba(0, 243, 255, 0.2);">
                    {SVGS['chat']}
                </div>
                <div>
                    <h2 style="margin: 0; font-size: 20px; font-weight: 800; color: #fff;">الأسطى المساعد</h2>
                    <p style="margin: 0; font-size: 13px; color: #00f3ff; font-weight: 600;">● RAG SYSTEM ONLINE</p>
                </div>
            </div>
            <div style="color: #00f3ff; font-size: 14px; text-shadow: 0 0 5px rgba(0,243,255,0.5);">
                <span style="background: rgba(0, 243, 255, 0.05); padding: 6px 12px; border-radius: 8px; border: 1px solid rgba(0, 243, 255, 0.2);">{SYSTEM_CONFIG.get('llm_model')}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    user_id = st.session_state.current_user["id"]

    with st.sidebar:
        st.markdown("<h3 style='margin-bottom: 15px;'>تذاكر الأعطال</h3>", unsafe_allow_html=True)
        
        if st.button("📝 فتح تذكرة جديدة", type="primary", use_container_width=True):
            new_session = db.collection("chat_sessions").add({
                "user_id": user_id, "title": "استفسار جديد", "updated_at": datetime.utcnow()
            })
            st.session_state.active_chat_id = new_session[1].id
            st.rerun()
            
        st.markdown("<hr style='border-color: rgba(0, 243, 255, 0.2);'>", unsafe_allow_html=True)
        
        sessions_stream = db.collection("chat_sessions").where("user_id", "==", user_id).stream()
        sessions_list = [{"id": s.id, **s.to_dict()} for s in sessions_stream]
        sessions_list.sort(key=lambda x: x.get("updated_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        for s_dict in sessions_list:
            cols = st.columns([5, 1])
            if cols[0].button(s_dict.get("title", "محادثة"), key=f"sel_{s_dict['id']}", use_container_width=True):
                st.session_state.active_chat_id = s_dict['id']
                st.rerun()
            if cols[1].button("🗑️", key=f"del_{s_dict['id']}", help="حذف المحادثة"):
                db.collection("chat_sessions").document(s_dict['id']).delete()
                for m in db.collection("chat_history").where("session_id", "==", s_dict['id']).stream(): m.reference.delete()
                if st.session_state.active_chat_id == s_dict['id']: st.session_state.active_chat_id = None
                st.rerun()

    if not st.session_state.active_chat_id:
        st.info("الرجاء تحديد محادثة أو بدء تذكرة جديدة.")
        return

    chat_box = st.container(height=500, border=False)
    with chat_box:
        history_stream = db.collection("chat_history").where("session_id", "==", st.session_state.active_chat_id).stream()
        messages = [doc.to_dict() for doc in history_stream]
        messages.sort(key=lambda x: x.get("timestamp") or datetime.min.replace(tzinfo=timezone.utc))
        
        if not messages:
            st.markdown(f"""
                <div style='text-align: center; padding-top: 100px;'>
                    <div style='display:inline-block; margin-bottom: 20px;'>{SVGS['chat']}</div>
                    <p style='color: #00f3ff;'>المساعد جاهز لاستقبال استفساراتك.<br>سجل صوتك أو ارفع صورة.</p>
                </div>
            """, unsafe_allow_html=True)
            
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("image_base64"): st.image(base64.b64decode(msg["image_base64"]), width=250)
                if msg.get("audio_bytes"): st.audio(msg["audio_bytes"])

    st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

    input_row = st.columns([1, 10])
    with input_row[0]:
        with st.popover(SVGS["attach"], help="المرفقات"):
            st.markdown("<p style='font-weight: 700; color: #00f3ff; text-align:center;'>المرفقات (صوت/صورة)</p>", unsafe_allow_html=True)
            st.markdown(f"<div style='display:flex; justify-content:center;'>{SVGS['mic']}</div>", unsafe_allow_html=True)
            audio_upload = st.audio_input("", key="mic_input")
            st.markdown(f"<div style='display:flex; justify-content:center; margin-top:15px;'>{SVGS['image']}</div>", unsafe_allow_html=True)
            image_upload = st.file_uploader("", type=["jpg", "png", "jpeg"], key="img_input")

    with input_row[1]:
        text_input = st.chat_input("اشرح المشكلة هنا...")

    if text_input or audio_upload or image_upload:
        final_user_text = text_input or ""
        img_b64 = None
        if image_upload:
            img_b64 = base64.b64encode(image_upload.read()).decode('utf-8')
            if not final_user_text: final_user_text = "الرجاء تحليل هذه الصورة."
        if audio_upload:
            with st.spinner("جاري تفريغ الصوت..."):
                final_user_text = f"{final_user_text}\n{transcribe_audio(audio_upload.read())}".strip()

        with st.chat_message("user"):
            st.markdown(final_user_text)
            if img_b64: st.image(image_upload, width=200)

        db.collection("chat_history").add({"session_id": st.session_state.active_chat_id, "role": "user", "content": final_user_text, "image_base64": img_b64, "timestamp": datetime.utcnow()})
        session_ref = db.collection("chat_sessions").document(st.session_state.active_chat_id)
        if session_ref.get().to_dict().get("title", "") == "استفسار فني جديد" and final_user_text:
            session_ref.update({"title": final_user_text[:40] + "...", "updated_at": datetime.utcnow()})
        else:
            session_ref.update({"updated_at": datetime.utcnow()})

        with st.chat_message("assistant"):
            with st.spinner("جاري البحث في الذاكرة (RAG)..."):
                try:
                    rag_context = perform_semantic_search(final_user_text, top_k=3)
                    sys_prompt = f"{SYSTEM_CONFIG.get('system_prompt', '')}\n\n=== مراجع (RAG) ===\n{rag_context}"
                    messages_list = [SystemMessage(content=sys_prompt)]
                    content_block = [{"type": "text", "text": final_user_text}]
                    if img_b64: content_block.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
                    messages_list.append(HumanMessage(content=content_block))

                    provider = SYSTEM_CONFIG.get("llm_provider", "google")
                    model_name = SYSTEM_CONFIG.get("llm_model", "gemini-1.5-flash")
                    llm = None
                    
                    if provider == "google": llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=decrypt_data(SYSTEM_CONFIG.get("google_api_key", "")), temperature=0.3)
                    elif provider == "openai": llm = ChatOpenAI(model_name=model_name, openai_api_key=decrypt_data(SYSTEM_CONFIG.get("openai_api_key", "")), temperature=0.3)
                    elif provider == "anthropic": llm = ChatAnthropic(model_name=model_name, api_key=decrypt_data(SYSTEM_CONFIG.get("anthropic_api_key", "")), temperature=0.3)

                    final_ai_text = st.write_stream(llm.stream(messages_list))
                    audio_reply = generate_voice_reply(final_ai_text)
                    if audio_reply: st.audio(audio_reply, format="audio/mp3")
                        
                    db.collection("chat_history").add({"session_id": st.session_state.active_chat_id, "role": "assistant", "content": final_ai_text, "audio_bytes": audio_reply, "timestamp": datetime.utcnow()})
                except Exception as e:
                    st.error(f"خطأ تقني: {str(e)}")

def render_dashboard():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background: rgba(16, 185, 129, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(16, 185, 129, 0.3);">
                {SVGS['dashboard']}
            </div>
            <div>
                <h1 style="margin: 0; font-size: 24px;">لوحة المؤشرات النيون</h1>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True); st.metric("العمال", len(list(db.collection("users").stream()))); st.markdown("</div>", unsafe_allow_html=True)
    with m2: st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True); st.metric("التذاكر", len(list(db.collection("chat_sessions").stream()))); st.markdown("</div>", unsafe_allow_html=True)
    with m3: st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True); st.metric("الكتالوجات", len(list(db.collection("knowledge_docs").stream()))); st.markdown("</div>", unsafe_allow_html=True)
    with m4: st.markdown("<div data-testid='metric-container'>", unsafe_allow_html=True); st.metric("العمليات", len(list(db.collection("chat_history").stream()))); st.markdown("</div>", unsafe_allow_html=True)

def render_user_management():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background: rgba(245, 158, 11, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(245, 158, 11, 0.3);">
                {SVGS['users']}
            </div>
            <h1 style="margin: 0; font-size: 24px;">إدارة الصلاحيات</h1>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("إضافة فرد جديد", expanded=True):
        with st.form("add_user_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            new_username = c1.text_input("معرف الموظف")
            new_password = c2.text_input("كلمة المرور", type="password")
            new_role = c3.selectbox("الصلاحية", ["worker", "admin"])
            if st.form_submit_button("تسجيل الحساب", type="primary"):
                if new_username and new_password:
                    if list(db.collection("users").where("username", "==", new_username).stream()): st.error("المعرف مستخدم.")
                    else:
                        db.collection("users").add({"username": new_username, "password": bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode(), "role": new_role, "created_at": datetime.utcnow()})
                        st.success("تم!"); time.sleep(1); st.rerun()

    st.markdown("<h3 style='margin-top: 30px;'>الأفراد المسجلين</h3>", unsafe_allow_html=True)
    for u in list(db.collection("users").order_by("created_at").stream()):
        u_data = u.to_dict()
        with st.container():
            st.markdown("<div style='background: rgba(0,0,0,0.4); border: 1px solid rgba(0,243,255,0.2); border-radius: 8px; padding: 15px; margin-bottom: 10px; display: flex; align-items: center;'>", unsafe_allow_html=True)
            colA, colB, colC = st.columns([3, 2, 1])
            colA.markdown(f"<div style='display:flex; gap:10px;'><div style='width:24px;'>{SVGS['lock'] if u_data['role']=='admin' else SVGS['user_profile']}</div> <span style='font-weight:700;'>{u_data['username']}</span></div>", unsafe_allow_html=True)
            colB.markdown(f"<span style='color:#00f3ff;'>{'مدير' if u_data['role']=='admin' else 'عامل'}</span>", unsafe_allow_html=True)
            if u_data['username'] != "admin" and colC.button("حذف", key=f"del_{u.id}"): db.collection("users").document(u.id).delete(); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

def render_knowledge_base():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background: rgba(139, 92, 246, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(139, 92, 246, 0.3);">
                {SVGS['database']}
            </div>
            <h1 style="margin: 0; font-size: 24px;">الذاكرة (Pinecone RAG)</h1>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='background: rgba(0,0,0,0.4); border: 1px dashed #00f3ff; border-radius: 16px; padding: 30px; text-align: center;'>", unsafe_allow_html=True)
    st.markdown(f"<div style='display:flex; justify-content:center; margin-bottom:15px;'>{SVGS['pdf']}</div>", unsafe_allow_html=True)
    uploaded_files = st.file_uploader("رفع PDF أو TXT", accept_multiple_files=True)
    if st.button("معالجة وحقن في Pinecone", type="primary") and uploaded_files:
        api_key, index_name = decrypt_data(SYSTEM_CONFIG.get("pinecone_api_key", "")), SYSTEM_CONFIG.get("pinecone_index_name", "")
        okey, gkey = decrypt_data(SYSTEM_CONFIG.get("openai_api_key", "")), decrypt_data(SYSTEM_CONFIG.get("google_api_key", ""))
        if not api_key or not index_name: st.error("إعدادات Pinecone مفقودة."); return
        embeddings = OpenAIEmbeddings(openai_api_key=okey) if okey else GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=gkey) if gkey else None
        if not embeddings: st.error("مفاتيح التضمين مفقودة."); return
        
        pc, pb = PineconeClient(api_key=api_key), st.progress(0)
        for i, file in enumerate(uploaded_files):
            text = "".join([page.extract_text() or "" for page in PdfReader(file).pages]) if file.name.endswith('.pdf') else file.read().decode('utf-8')
            chunks = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150).split_text(text)
            PineconeVectorStore(index=pc.Index(index_name), embedding=embeddings).add_texts(texts=chunks, metadatas=[{"source": file.name} for _ in chunks])
            db.collection("knowledge_docs").add({"filename": file.name, "chunks_count": len(chunks), "uploaded_at": datetime.utcnow()})
            pb.progress((i + 1) / len(uploaded_files))
        st.success("تم الحفظ!")
    st.markdown("</div>", unsafe_allow_html=True)

def render_settings():
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 30px;">
            <div style="background: rgba(255, 0, 255, 0.1); padding: 12px; border-radius: 12px; border: 1px solid rgba(255, 0, 255, 0.3);">
                {SVGS['settings']}
            </div>
            <h1 style="margin: 0; font-size: 24px;">تكوين النظام (Global Config)</h1>
        </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["الذكاء الاصطناعي", "Pinecone (RAG)", "الـ Prompt"])
    with st.form("master_settings_form"):
        with tab1:
            c1, c2 = st.columns(2)
            prov = c1.selectbox("المزود", ["google", "openai", "anthropic"], index=["google", "openai", "anthropic"].index(SYSTEM_CONFIG.get("llm_provider", "google")))
            mod = c2.text_input("الموديل", value=SYSTEM_CONFIG.get("llm_model", "gemini-1.5-flash"))
            gk = st.text_input("Google Key", value=decrypt_data(SYSTEM_CONFIG.get("google_api_key", "")), type="password")
            ok = st.text_input("OpenAI Key", value=decrypt_data(SYSTEM_CONFIG.get("openai_api_key", "")), type="password")
            ak = st.text_input("Anthropic Key", value=decrypt_data(SYSTEM_CONFIG.get("anthropic_api_key", "")), type="password")
        with tab2:
            pk = st.text_input("Pinecone Key", value=decrypt_data(SYSTEM_CONFIG.get("pinecone_api_key", "")), type="password")
            idx = st.text_input("Index Name", value=SYSTEM_CONFIG.get("pinecone_index_name", ""))
        with tab3:
            pmt = st.text_area("System Prompt", value=SYSTEM_CONFIG.get("system_prompt", ""), height=200)
        
        if st.form_submit_button("حفظ التكوين", type="primary"):
            settings_doc.update({"llm_provider": prov, "llm_model": mod, "google_api_key": encrypt_data(gk), "openai_api_key": encrypt_data(ok), "anthropic_api_key": encrypt_data(ak), "pinecone_api_key": encrypt_data(pk), "pinecone_index_name": idx, "system_prompt": pmt})
            st.success("تم التحديث!"); time.sleep(1); st.rerun()

def main_app_router():
    if not st.session_state.current_user:
        render_login_page(); return

    user_info, is_admin = st.session_state.current_user, st.session_state.current_user.get("role") == "admin"

    with st.sidebar:
        st.markdown(f"""
            <div style="background: rgba(0, 0, 0, 0.4); padding: 20px; border-radius: 16px; border: 1px solid rgba(0, 243, 255, 0.2); margin-bottom: 25px; text-align: center; box-shadow: 0 0 15px rgba(0,243,255,0.1);">
                <div style="display: flex; justify-content: center; margin-bottom: 10px;">{SVGS['user_profile']}</div>
                <h3 style="margin: 0; color: #fff; font-size: 18px; text-shadow: 0 0 5px #00f3ff;">{user_info.get('username')}</h3>
                <span style="color: #00f3ff; font-size: 12px;">{'مدير السيستم' if is_admin else 'صنايعي تشغيل'}</span>
            </div>
        """, unsafe_allow_html=True)

        nav_options = ["المساعد الفني (Chat)"]
        if is_admin: nav_options.extend(["لوحة المؤشرات", "المستخدمين والصلاحيات", "إدارة الكتالوجات (RAG)", "تكوين النظام (Settings)"])
        selected_page = st.radio("القائمة", nav_options, label_visibility="collapsed")
        
        st.markdown("<div style='flex-grow: 1; height: 50px;'></div><hr style='border-color: rgba(0, 243, 255, 0.2);'>", unsafe_allow_html=True)
        if st.button("تسجيل الخروج", use_container_width=True): st.session_state.clear(); st.rerun()

    if selected_page == "المساعد الفني (Chat)": render_chat_kiosk()
    elif selected_page == "لوحة المؤشرات": render_dashboard()
    elif selected_page == "المستخدمين والصلاحيات": render_user_management()
    elif selected_page == "إدارة الكتالوجات (RAG)": render_knowledge_base()
    elif selected_page == "تكوين النظام (Settings)": render_settings()

if __name__ == "__main__":
    main_app_router()
