import os
import io
import json
import base64
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
import logging
from cryptography.fernet import Fernet
import bcrypt
import threading
import tempfile

import streamlit as st
import openai
from apscheduler.schedulers.background import BackgroundScheduler

# --- Firebase ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- Langchain ---
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage

# =====================================================================
# الإعدادات الأولية وتهيئة الصفحة (يجب أن تكون في بداية الملف)
# =====================================================================
st.set_page_config(page_title="مساعد الورشة الذكي", page_icon="🛠️", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    :root {
        --primary: #FF9800;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    .stButton>button {
        background-color: var(--primary);
        color: black;
        font-weight: bold;
        border-radius: 10px;
        border: none;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #e68a00;
        color: black;
        transform: translateY(-2px);
    }
    
    .custom-card {
        background-color: #1e1e1e;
        padding: 20px;
        border-radius: 15px;
        border: 1px solid #333;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .text-primary-custom { color: #FF9800 !important; }
    .text-success-custom { color: #4CAF50 !important; }
    .text-danger-custom { color: #F44336 !important; }
    .text-info-custom { color: #2196F3 !important; }
</style>
""", unsafe_allow_html=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# =====================================================================
# الأمان والمفاتيح
# =====================================================================
def get_secret(key_name: str, default_value: str = "") -> str:
    if key_name in st.secrets: return st.secrets[key_name]
    return os.getenv(key_name, default_value)

FERNET_KEY = get_secret("FERNET_KEY", Fernet.generate_key().decode())
cipher = Fernet(FERNET_KEY.encode())

def encrypt_val(value: str) -> str: return cipher.encrypt(value.encode()).decode() if value else ""
def decrypt_val(value: str) -> str:
    if not value: return ""
    try: return cipher.decrypt(value.encode()).decode()
    except: return value

def verify_password(plain_password, hashed_password): return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
def get_password_hash(password): return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def get_iso_now(): return datetime.utcnow().isoformat()

# =====================================================================
# قاعدة البيانات (Firebase Firestore)
# =====================================================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        firebase_cred_json = get_secret("FIREBASE_CREDENTIALS")
        if firebase_cred_json:
            try:
                cred_dict = json.loads(firebase_cred_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase initialized using provided JSON credentials.")
            except Exception as e:
                logger.error(f"Error parsing Firebase JSON: {e}")
                st.error("خطأ في قراءة ملف إعدادات Firebase JSON.")
        else:
            try:
                # محاولة استخدام الإعدادات الافتراضية للسحابة أو لو تم وضعها كمتغير بيئة
                firebase_admin.initialize_app()
                logger.info("Firebase initialized using default application credentials.")
            except Exception as e:
                logger.error("No Firebase credentials found.")
                return None
    return firestore.client()

db = init_firebase()

if db is None:
    st.error("⚠️ لم يتم العثور على إعدادات Firebase. يرجى إضافة 'FIREBASE_CREDENTIALS' كـ JSON نصي في إعدادات Secrets.")
    st.stop()

# =====================================================================
# نماذج البيانات (Wrappers to simulate ORM)
# =====================================================================
class TenantModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.name = data.get('name', 'ورشة الصيانة والتصنيع')
        self.llm_provider = data.get('llm_provider', 'google')
        self.llm_model = data.get('llm_model', 'gemini-1.5-flash')
        self.api_base_url = data.get('api_base_url', '')
        self.openai_api_key = data.get('openai_api_key', '')
        self.anthropic_api_key = data.get('anthropic_api_key', '')
        self.google_api_key = data.get('google_api_key', '')
        self.pinecone_api_key = data.get('pinecone_api_key', '')
        self.pinecone_index = data.get('pinecone_index', '')
        self.workshop_prompt = data.get('workshop_prompt', "أنت 'الأسطى بلية'، أقدم وأشطر صنايعي ومهندس في ورشة ميكانيكا وصيانة ضواغط هواء ومجففات في مصر.\nالعمال اللي بيكلموك صنايعية على قدهم ومابيعرفوش يقرأوا ويكتبوا، عشان كده:\n1. اتكلم معاهم بلهجة مصرية بلدي صميمة.\n2. اشرح المشكلة وحلها ببساطة.\n3. خليك جدع ومشجع وبتحل المشاكل بخطوات عملية.\n4. لو بعتولك صورة، ركز فيها وقولهم فيها إيه بالظبط وكيفية صيانته.\n5. اعتمد في إجاباتك على معلومات الكتالوجات المرفقة.")
    
    def to_dict(self):
        d = self.__dict__.copy()
        d.pop('id', None)
        return d
    
    def save(self):
        db.collection('tenants').document(self.id).set(self.to_dict())

class UserModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.username = data.get('username')
        self.hashed_password = data.get('hashed_password')
        self.role = data.get('role', 'admin')
        self.tenant_id = data.get('tenant_id')
        self.tenant = None # Will be populated if needed

class ChatSessionModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.session_uuid = data.get('session_uuid', doc_id)
        self.title = data.get('title', 'محادثة جديدة')
        self.user_id = data.get('user_id')
        self.tenant_id = data.get('tenant_id')
        self.created_at = data.get('created_at', get_iso_now())
        self.updated_at = data.get('updated_at', get_iso_now())
    
    def save(self):
        d = self.__dict__.copy()
        d.pop('id', None)
        db.collection('chat_sessions').document(self.session_uuid).set(d)

class HistoryModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.session_id = data.get('session_id')
        self.role = data.get('role')
        self.content = data.get('content')
        self.created_at = data.get('created_at', get_iso_now())
        self.tenant_id = data.get('tenant_id')

class DocModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.filename = data.get('filename')
        self.tenant_id = data.get('tenant_id')

class AlertModel:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self.message = data.get('message')
        self.created_at = data.get('created_at', get_iso_now())
        self.tenant_id = data.get('tenant_id')

# =====================================================================
# تهيئة البيانات الأولية والجدولة
# =====================================================================
def analyze_machine_issues_job():
    logger.info("Starting Daily Cron Job: Analyzing machine issues...")
    try:
        tenants_ref = db.collection('tenants').stream()
        for t_doc in tenants_ref:
            tenant = TenantModel(t_doc.id, t_doc.to_dict())
            if not tenant.openai_api_key: continue
            
            openai_key = decrypt_val(tenant.openai_api_key)
            thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            
            # جلب آخر المحادثات وفرزها في البايثون لتفادي مشكلة Composite Indexes في Firebase
            history_ref = db.collection('conversation_history').where('tenant_id', '==', tenant.id).stream()
            histories = [HistoryModel(h.id, h.to_dict()) for h in history_ref]
            recent_histories = [h for h in histories if h.created_at >= thirty_days_ago]
            recent_histories.sort(key=lambda x: x.created_at, reverse=True)
            recent_histories = recent_histories[:500]
            
            if len(recent_histories) < 10: continue
            
            text_log = "\n".join([f"{h.role}: {h.content}" for h in recent_histories])
            prompt = """بصفتك مهندس صيانة ذكي، قم بتحليل سجلات محادثات العمال التالية خلال الشهر الماضي. 
هل تلاحظ وجود عطل في ماكينة معينة يتكرر السؤال عنه؟ إذا وجدت تكراراً يعطي مؤشراً على مشكلة مزمنة، اكتب تنبيهاً واحداً. إذا كانت الأمور طبيعية اكتب فقط 'لا يوجد'."""
            
            try:
                llm = ChatOpenAI(model_name="gpt-4o-mini", openai_api_key=openai_key, temperature=0.0)
                res = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=text_log)])
                if "لا يوجد" not in res.content:
                    db.collection('alerts').add({
                        'message': f"⚠️ تنبيه ذكي: {res.content}",
                        'created_at': get_iso_now(),
                        'tenant_id': tenant.id
                    })
            except Exception as e:
                logger.error(f"Cron LLM error: {e}")
    except Exception as e:
        logger.error(f"Cron overall error: {e}")

@st.cache_resource
def init_system():
    # التأكد من وجود Tenant أولي واسم مستخدم للبدء
    tenants = list(db.collection('tenants').limit(1).stream())
    if not tenants:
        tenant_id = str(uuid.uuid4())
        default_tenant = TenantModel(tenant_id, {'name': 'ورشة الصيانة والتصنيع'})
        default_tenant.save()
        
        db.collection('users').add({
            'username': 'admin',
            'hashed_password': get_password_hash('admin123'),
            'role': 'admin',
            'tenant_id': tenant_id
        })
        db.collection('users').add({
            'username': 'worker',
            'hashed_password': get_password_hash('1234'),
            'role': 'worker',
            'tenant_id': tenant_id
        })
    
    # تشغيل المجدول (Scheduler) في الخلفية
    scheduler = BackgroundScheduler()
    scheduler.add_job(analyze_machine_issues_job, 'cron', hour=2, minute=0)
    scheduler.start()
    return True

init_system()

# =====================================================================
# دوال المساعدة للـ LLM والـ RAG
# =====================================================================
def get_pinecone_client(api_key):
    if api_key:
        try: return PineconeClient(api_key=api_key)
        except: return None
    return None

def process_document(file_bytes, filename, tenant):
    openai_key = decrypt_val(tenant.openai_api_key)
    google_key = decrypt_val(tenant.google_api_key)
    pinecone_key = decrypt_val(tenant.pinecone_api_key)
    
    pc_client = get_pinecone_client(pinecone_key)
    if not pc_client or not tenant.pinecone_index:
        return False, "إعدادات Pinecone غير مكتملة."

    embeddings = None
    if openai_key: embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
    elif google_key: embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key)
    
    if not embeddings: return False, "مفتاح OpenAI أو Google غير متوفر للتضمين (Embeddings)."

    try:
        text_data = ""
        if filename.lower().endswith('.pdf'):
            pdf_reader = PdfReader(io.BytesIO(file_bytes))
            for page in pdf_reader.pages: text_data += (page.extract_text() or "") + "\n"
        else:
            text_data = file_bytes.decode('utf-8')
            
        chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_text(text_data)
        metadatas = [{"filename": filename} for _ in chunks]
        vector_store = PineconeVectorStore(index=pc_client.Index(tenant.pinecone_index), embedding=embeddings, namespace=f"tenant_{tenant.id}")
        vector_store.add_texts(texts=chunks, metadatas=metadatas)
        return True, "تم المعالجة والحفظ بنجاح."
    except Exception as e:
        return False, f"خطأ أثناء المعالجة: {str(e)}"

# =====================================================================
# إدارة الجلسات (Session State)
# =====================================================================
if "user_id" not in st.session_state: st.session_state.user_id = None
if "current_view" not in st.session_state: st.session_state.current_view = "chat"
if "chat_session_id" not in st.session_state: st.session_state.chat_session_id = None

def get_current_user():
    if st.session_state.user_id:
        user_doc = db.collection('users').document(st.session_state.user_id).get()
        if user_doc.exists:
            u = UserModel(user_doc.id, user_doc.to_dict())
            t_doc = db.collection('tenants').document(u.tenant_id).get()
            u.tenant = TenantModel(t_doc.id, t_doc.to_dict()) if t_doc.exists else None
            return u
    return None

def logout():
    st.session_state.user_id = None
    st.session_state.chat_session_id = None
    st.session_state.current_view = "chat"
    st.rerun()

# =====================================================================
# واجهات النظام
# =====================================================================

# 1. شاشة تسجيل الدخول
def login_view():
    st.markdown("<h1 style='text-align: center; color: var(--primary);'>🛠️ دخول ورشة الصيانة</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("اسم المستخدم", placeholder="worker / admin")
            password = st.text_input("كلمة السر", type="password")
            submit = st.form_submit_button("دخول", use_container_width=True)
            
            if submit:
                users_ref = db.collection('users').where('username', '==', username).stream()
                users_list = list(users_ref)
                if users_list:
                    user_data = users_list[0].to_dict()
                    if verify_password(password, user_data.get('hashed_password', '')):
                        st.session_state.user_id = users_list[0].id
                        st.rerun()
                    else: st.error("كلمة السر غير صحيحة.")
                else:
                    st.error("المستخدم غير موجود.")

# 2. واجهة المحادثة (Kiosk)
def chat_view(user):
    tenant = user.tenant
    
    # جلب جميع المحادثات للمستخدم وفرزها
    sessions_ref = db.collection('chat_sessions').where('user_id', '==', user.id).stream()
    sessions = [ChatSessionModel(s.id, s.to_dict()) for s in sessions_ref]
    sessions.sort(key=lambda x: x.updated_at, reverse=True)

    with st.sidebar:
        st.markdown(f"<h3 class='text-primary-custom'>أهلاً، {user.username}</h3>", unsafe_allow_html=True)
        if st.button("➕ محادثة جديدة", use_container_width=True):
            new_uuid = str(uuid.uuid4())
            new_sess = ChatSessionModel(new_uuid, {'session_uuid': new_uuid, 'user_id': user.id, 'tenant_id': tenant.id, 'title': 'محادثة جديدة'})
            new_sess.save()
            st.session_state.chat_session_id = new_uuid
            st.rerun()
            
        st.divider()
        
        if not st.session_state.chat_session_id and sessions:
            st.session_state.chat_session_id = sessions[0].session_uuid
        elif not sessions:
            new_uuid = str(uuid.uuid4())
            new_sess = ChatSessionModel(new_uuid, {'session_uuid': new_uuid, 'user_id': user.id, 'tenant_id': tenant.id, 'title': 'محادثة جديدة'})
            new_sess.save()
            st.session_state.chat_session_id = new_uuid
            sessions = [new_sess]
            
        for s in sessions:
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(s.title[:20] + "...", key=f"sel_{s.session_uuid}", use_container_width=True, type="primary" if s.session_uuid == st.session_state.chat_session_id else "secondary"):
                    st.session_state.chat_session_id = s.session_uuid
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{s.session_uuid}"):
                    # حذف السجل المرتبط
                    hist_ref = db.collection('conversation_history').where('session_id', '==', s.session_uuid).stream()
                    for h in hist_ref: h.reference.delete()
                    # حذف الجلسة
                    db.collection('chat_sessions').document(s.session_uuid).delete()
                    
                    if st.session_state.chat_session_id == s.session_uuid: st.session_state.chat_session_id = None
                    st.rerun()

    current_session = st.session_state.chat_session_id
    if not current_session: return
    
    st.markdown("<h2 class='text-primary-custom'><i class='bi bi-robot'></i> الأسطى بلية</h2>", unsafe_allow_html=True)
    
    hist_ref = db.collection('conversation_history').where('session_id', '==', current_session).stream()
    chat_history = [HistoryModel(h.id, h.to_dict()) for h in hist_ref]
    chat_history.sort(key=lambda x: x.created_at) # ترتيب زمني قديم لجديد
    
    for msg in chat_history:
        with st.chat_message("user" if msg.role == "Worker" else "assistant"):
            if "[صورة مرفقة]" in msg.content or "data:image" in msg.content:
                st.write("صورة مرفقة 🖼️")
            else:
                st.write(msg.content)
            
            if msg.role == "AI" and decrypt_val(tenant.openai_api_key):
                if st.button("🔊 اسمع", key=f"tts_{msg.id}"):
                    try:
                        client = openai.OpenAI(api_key=decrypt_val(tenant.openai_api_key))
                        response = client.audio.speech.create(model="tts-1", voice="onyx", input=msg.content[:1000])
                        st.audio(response.read(), format="audio/mp3", autoplay=True)
                    except Exception as e:
                        st.error("تعذر تشغيل الصوت.")

    input_text = st.chat_input("اكتب سؤالك هنا يا هندسة...")
    
    col1, col2 = st.columns(2)
    with col1:
        audio_val = st.audio_input("سجل رسالة صوتية (المايك)")
    with col2:
        img_val = st.file_uploader("ارفع صورة العطل (أو صور بالكاميرا)", type=["png", "jpg", "jpeg"])

    if input_text or audio_val or img_val:
        transcribed_text = input_text or ""
        img_base64 = None
        
        if img_val:
            bytes_data = img_val.getvalue()
            img_base64 = f"data:{img_val.type};base64,{base64.b64encode(bytes_data).decode()}"
            if not transcribed_text: transcribed_text = "بص على الصورة دي وقولي الحل إيه؟"
            
        if audio_val:
            openai_key = decrypt_val(tenant.openai_api_key)
            if not openai_key:
                st.error("مفتاح OpenAI مطلوب لمعالجة الصوت.")
                return
            try:
                with st.spinner("جاري الاستماع..."):
                    client = openai.OpenAI(api_key=openai_key)
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1", file=("audio.wav", audio_val.getvalue(), "audio/wav"), language="ar"
                    )
                    transcribed_text = transcript.text
            except Exception as e:
                st.error(f"خطأ في قراءة الصوت: {e}")
                return

        if transcribed_text or img_base64:
            # تحديث عنوان الجلسة إذا كانت جديدة
            sess_doc = db.collection('chat_sessions').document(current_session).get()
            if sess_doc.exists:
                sess_obj = ChatSessionModel(sess_doc.id, sess_doc.to_dict())
                if sess_obj.title == "محادثة جديدة":
                    sess_obj.title = " ".join(transcribed_text.split()[:4]) or "محادثة"
                    sess_obj.updated_at = get_iso_now()
                    sess_obj.save()

            with st.chat_message("user"):
                st.write(transcribed_text)
                if img_val: st.image(img_val, width=200)
                
            db.collection('conversation_history').add({
                'session_id': current_session,
                'role': 'Worker',
                'content': transcribed_text,
                'tenant_id': tenant.id,
                'created_at': get_iso_now()
            })

            # RAG
            rag_context = ""
            if any(kw in transcribed_text for kw in ["ضاغط", "مجفف", "صيانة", "عطل", "بايظ", "مشكلة"]):
                pc_client = get_pinecone_client(decrypt_val(tenant.pinecone_api_key))
                if pc_client and tenant.pinecone_index:
                    try:
                        emb_key = decrypt_val(tenant.openai_api_key)
                        g_key = decrypt_val(tenant.google_api_key)
                        embeddings = OpenAIEmbeddings(openai_api_key=emb_key) if emb_key else GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=g_key) if g_key else None
                        if embeddings:
                            vstore = PineconeVectorStore(index=pc_client.Index(tenant.pinecone_index), embedding=embeddings, namespace=f"tenant_{tenant.id}")
                            docs = vstore.similarity_search(transcribed_text, k=2)
                            rag_context = "\n".join([d.page_content for d in docs])
                    except Exception as e:
                        logger.error(f"RAG Error: {e}")

            # LLM
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                try:
                    provider = tenant.llm_provider
                    model_name = tenant.llm_model
                    base_url = tenant.api_base_url
                    llm = None
                    
                    if provider == "openai": llm = ChatOpenAI(model_name=model_name, openai_api_key=decrypt_val(tenant.openai_api_key), temperature=0.3, base_url=base_url if base_url else None)
                    elif provider == "anthropic": llm = ChatAnthropic(model_name=model_name, api_key=decrypt_val(tenant.anthropic_api_key), temperature=0.3, base_url=base_url if base_url else None)
                    elif provider == "google": llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=decrypt_val(tenant.google_api_key), temperature=0.3)
                    elif provider == "custom": llm = ChatOpenAI(model_name=model_name, openai_api_key=decrypt_val(tenant.openai_api_key) or "sk-custom", temperature=0.3, base_url=base_url)
                    
                    if not llm: st.error("لم يتم التعرف على مزود الخدمة أو المفاتيح ناقصة.")
                    else:
                        hist_text = "\n".join([f"{h.role}: {h.content}" for h in chat_history[-3:]])
                        sys_prompt = f"{tenant.workshop_prompt}\n\nتاريخ المحادثة:\n{hist_text}\n\nمعلومات من الكتالوجات:\n{rag_context}"
                        
                        human_msg_content = [{"type": "text", "text": transcribed_text}]
                        if img_base64: human_msg_content.append({"type": "image_url", "image_url": {"url": img_base64}})
                        
                        messages = [SystemMessage(content=sys_prompt), HumanMessage(content=human_msg_content)]
                        
                        for chunk in llm.stream(messages):
                            full_response += chunk.content
                            message_placeholder.markdown(full_response + "▌")
                        message_placeholder.markdown(full_response)
                        
                        db.collection('conversation_history').add({
                            'session_id': current_session,
                            'role': 'AI',
                            'content': full_response,
                            'tenant_id': tenant.id,
                            'created_at': get_iso_now()
                        })
                        
                except Exception as e:
                    message_placeholder.markdown(f"❌ حدث خطأ: {e}")
                    
            st.rerun()

# 3. لوحة التحكم والإعدادات (للمدير)
def admin_dashboard(user):
    tenant = user.tenant
    st.markdown("<h2 class='text-primary-custom'>لوحة تحكم الورشة</h2>", unsafe_allow_html=True)
    
    # إحصائيات سريعة (Firebase Aggregate)
    try:
        chats_count = sum(1 for _ in db.collection('conversation_history').where('tenant_id', '==', tenant.id).stream())
        workers_count = sum(1 for _ in db.collection('users').where('tenant_id', '==', tenant.id).where('role', '==', 'worker').stream())
    except:
        chats_count, workers_count = "--", "--"
    
    col1, col2, col3 = st.columns(3)
    col1.markdown(f"<div class='custom-card text-center'><h3 class='text-primary-custom'>{chats_count}</h3><p>الرسائل والاستفسارات</p></div>", unsafe_allow_html=True)
    col2.markdown(f"<div class='custom-card text-center'><h3 class='text-info-custom'>{workers_count}</h3><p>عدد العمال</p></div>", unsafe_allow_html=True)
    col3.markdown(f"<div class='custom-card text-center'><h3 class='text-success-custom'>--</h3><p>التكلفة (راجع المزود)</p></div>", unsafe_allow_html=True)

    st.subheader("⚠️ التنبيهات الذكية (الأعطال المتكررة)")
    alerts_ref = db.collection('alerts').where('tenant_id', '==', tenant.id).stream()
    alerts = [AlertModel(a.id, a.to_dict()) for a in alerts_ref]
    alerts.sort(key=lambda x: x.created_at, reverse=True)
    
    if alerts:
        for a in alerts[:5]:
            # Convert ISO string back to date format for display
            date_str = a.created_at.split('T')[0] if 'T' in a.created_at else a.created_at
            st.warning(f"[{date_str}] {a.message}")
    else:
        st.info("لا توجد تنبيهات مؤخراً. الوضع مستقر!")

def admin_users(user):
    st.header("إدارة العمال")
    
    with st.expander("➕ إضافة مستخدم جديد", expanded=False):
        with st.form("add_user"):
            new_user = st.text_input("اسم المستخدم")
            new_pass = st.text_input("كلمة السر", type="password")
            new_role = st.selectbox("الصلاحية", ["worker", "admin"])
            if st.form_submit_button("إضافة"):
                existing = list(db.collection('users').where('username', '==', new_user).limit(1).stream())
                if not existing:
                    db.collection('users').add({
                        'username': new_user,
                        'hashed_password': get_password_hash(new_pass),
                        'role': new_role,
                        'tenant_id': user.tenant_id
                    })
                    st.success("تم الإضافة!")
                    st.rerun()
                else:
                    st.error("المستخدم موجود مسبقاً.")

    st.subheader("قائمة المستخدمين")
    users_ref = db.collection('users').where('tenant_id', '==', user.tenant_id).stream()
    users = [UserModel(u.id, u.to_dict()) for u in users_ref]
    
    for u in users:
        col1, col2, col3 = st.columns([3, 2, 1])
        col1.write(u.username)
        col2.write("مدير" if u.role == "admin" else "عامل")
        if u.id != user.id and col3.button("حذف", key=f"del_u_{u.id}"):
            db.collection('users').document(u.id).delete()
            st.rerun()

def admin_rag(user):
    tenant = user.tenant
    st.header("الكتالوجات والملفات (RAG)")
    
    uploaded_files = st.file_uploader("ارفع ملفات (PDF, TXT)", type=["pdf", "txt"], accept_multiple_files=True)
    if uploaded_files:
        if st.button("معالجة وحفظ في الذاكرة"):
            for f in uploaded_files:
                existing = list(db.collection('uploaded_documents').where('filename', '==', f.name).where('tenant_id', '==', tenant.id).stream())
                if not existing:
                    with st.spinner(f"جاري معالجة {f.name}..."):
                        success, msg = process_document(f.getvalue(), f.name, tenant)
                        if success:
                            db.collection('uploaded_documents').add({'filename': f.name, 'tenant_id': tenant.id})
                            st.success(f"تم حفظ {f.name}")
                        else:
                            st.error(msg)
                else:
                    st.warning(f"الملف {f.name} مرفوع مسبقاً.")
    
    st.subheader("الملفات المحفوظة")
    docs_ref = db.collection('uploaded_documents').where('tenant_id', '==', tenant.id).stream()
    docs = [DocModel(d.id, d.to_dict()) for d in docs_ref]
    
    for d in docs:
        col1, col2 = st.columns([4, 1])
        col1.write(f"📄 {d.filename}")
        if col2.button("حذف", key=f"del_doc_{d.id}"):
            try:
                pc_client = get_pinecone_client(decrypt_val(tenant.pinecone_api_key))
                if pc_client and tenant.pinecone_index:
                    pc_client.Index(tenant.pinecone_index).delete(filter={"filename": d.filename}, namespace=f"tenant_{tenant.id}")
            except Exception as e: logger.error(e)
            db.collection('uploaded_documents').document(d.id).delete()
            st.rerun()

def admin_settings(user):
    tenant = user.tenant
    st.header("إعدادات النظام والتخصيص")
    
    tab1, tab2, tab3 = st.tabs(["النماذج (LLM)", "الذاكرة (Pinecone)", "الشخصية (Prompt)"])
    
    with tab1:
        with st.form("llm_settings"):
            providers = ["google", "openai", "anthropic", "custom"]
            current_provider = tenant.llm_provider if tenant.llm_provider in providers else "google"
            provider = st.selectbox("مزود الخدمة", providers, index=providers.index(current_provider))
            model = st.text_input("اسم الموديل", value=tenant.llm_model)
            base_url = st.text_input("الرابط المخصص (Base URL)", value=tenant.api_base_url or "")
            o_key = st.text_input("مفتاح OpenAI (مطلوب للصوت)", value=decrypt_val(tenant.openai_api_key), type="password")
            a_key = st.text_input("مفتاح Anthropic", value=decrypt_val(tenant.anthropic_api_key), type="password")
            g_key = st.text_input("مفتاح Google Gemini", value=decrypt_val(tenant.google_api_key), type="password")
            
            if st.form_submit_button("حفظ إعدادات النماذج"):
                tenant.llm_provider = provider
                tenant.llm_model = model
                tenant.api_base_url = base_url
                tenant.openai_api_key = encrypt_val(o_key)
                tenant.anthropic_api_key = encrypt_val(a_key)
                tenant.google_api_key = encrypt_val(g_key)
                tenant.save()
                st.success("تم الحفظ بنجاح.")
                
    with tab2:
        with st.form("pinecone_settings"):
            p_key = st.text_input("Pinecone API Key", value=decrypt_val(tenant.pinecone_api_key), type="password")
            p_index = st.text_input("Pinecone Index Name", value=tenant.pinecone_index)
            if st.form_submit_button("حفظ إعدادات الذاكرة"):
                tenant.pinecone_api_key = encrypt_val(p_key)
                tenant.pinecone_index = p_index
                tenant.save()
                st.success("تم الحفظ بنجاح.")
                
    with tab3:
        with st.form("prompt_settings"):
            prompt = st.text_area("شخصية المساعد (System Prompt)", value=tenant.workshop_prompt, height=200)
            if st.form_submit_button("تحديث الشخصية"):
                tenant.workshop_prompt = prompt
                tenant.save()
                st.success("تم الحفظ بنجاح.")

# =====================================================================
# نظام التوجيه (Routing)
# =====================================================================
def main():
    user = get_current_user()
    
    if not user:
        login_view()
        return
        
    with st.sidebar:
        st.markdown(f"**تسجيل الدخول كـ:** {user.username}")
        if user.role == "admin":
            st.session_state.current_view = st.radio("القائمة الرئيسية", ["المحادثة (Kiosk)", "لوحة التحكم", "العمال", "الكتالوجات (RAG)", "الإعدادات"])
        else:
            st.session_state.current_view = "المحادثة (Kiosk)"
            
        st.markdown("---")
        if st.button("تسجيل الخروج 🚪", use_container_width=True):
            logout()
            
    view = st.session_state.current_view
    if view == "المحادثة (Kiosk)": chat_view(user)
    elif view == "لوحة التحكم": admin_dashboard(user)
    elif view == "العمال": admin_users(user)
    elif view == "الكتالوجات (RAG)": admin_rag(user)
    elif view == "الإعدادات": admin_settings(user)

if __name__ == "__main__":
    main()
