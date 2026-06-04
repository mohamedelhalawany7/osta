import os
import io
import json
import base64
import uuid
from datetime import datetime, timedelta, timezone
import logging
from cryptography.fernet import Fernet
import bcrypt
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
# الإعدادات الأولية وتهيئة الصفحة والتصميم
# =====================================================================
st.set_page_config(page_title="مساعد الورشة الذكي", page_icon="🛠️", layout="wide", initial_sidebar_state="expanded")

# تصميم CSS ليتطابق مع واجهة الورشة الأصلية
st.markdown("""
<style>
    :root {
        --primary: #FF9800;
        --bg-card: #1e1e1e;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    .stButton>button {
        background-color: var(--primary) !important;
        color: black !important;
        font-weight: bold !important;
        border-radius: 10px !important;
        border: none !important;
        transition: all 0.3s ease !important;
    }
    .stButton>button:hover {
        background-color: #e68a00 !important;
        transform: translateY(-2px) !important;
    }
    
    /* تصميم الرسائل (Chat Bubbles) */
    .stChatMessage {
        border-radius: 15px !important;
        padding: 10px !important;
        margin-bottom: 10px !important;
    }
    [data-testid="chatAvatarIcon-user"] { background-color: var(--primary); }
    [data-testid="chatAvatarIcon-assistant"] { background-color: #333; }
    
    .custom-card {
        background-color: var(--bg-card);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid #333;
        margin-bottom: 20px;
        text-align: center;
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
# إدارة المفاتيح والأمان (الاعتماد على st.secrets)
# =====================================================================
def get_secret(key_name: str, default_value: str = "") -> str:
    if key_name in st.secrets:
        return st.secrets[key_name]
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

# =====================================================================
# تهيئة Firebase Firestore
# =====================================================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # قراءة مفاتيح Firebase من Secrets
        cred_json = get_secret("FIREBASE_CREDENTIALS")
        if not cred_json:
            st.error("⚠️ بيانات اعتماد Firebase (FIREBASE_CREDENTIALS) غير موجودة في st.secrets")
            st.stop()
        try:
            if isinstance(cred_json, str):
                cred_dict = json.loads(cred_json)
            else:
                cred_dict = dict(cred_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"⚠️ فشل الاتصال بـ Firebase: {e}")
            st.stop()
    return firestore.client()

db = init_firebase()

# =====================================================================
# دوال مساعدة لـ Firebase (إنشاء وتحديث البيانات)
# =====================================================================
def init_system_data():
    """تهيئة الورشة الافتراضية وحساب المدير في حال كانت قاعدة البيانات فارغة"""
    tenants_ref = db.collection('tenants')
    users_ref = db.collection('users')
    
    tenant_docs = list(tenants_ref.limit(1).stream())
    if not tenant_docs:
        # إنشاء Tenant الافتراضي
        tenant_data = {
            "name": "ورشة الصيانة والتصنيع",
            "llm_provider": "google",
            "llm_model": "gemini-1.5-flash",
            "api_base_url": "",
            "openai_api_key": "",
            "anthropic_api_key": "",
            "google_api_key": "",
            "pinecone_api_key": "",
            "pinecone_index": "",
            "workshop_prompt": """أنت 'الأسطى بلية'، أقدم وأشطر صنايعي ومهندس في ورشة ميكانيكا وصيانة ضواغط هواء ومجففات في مصر.
العمال اللي بيكلموك صنايعية على قدهم ومابيعرفوش يقرأوا ويكتبوا، عشان كده:
1. اتكلم معاهم بلهجة مصرية بلدي صميمة.
2. اشرح المشكلة وحلها ببساطة.
3. خليك جدع ومشجع وبتحل المشاكل بخطوات عملية 1، 2، 3.
4. لو بعتولك صورة، ركز فيها وقولهم فيها إيه بالظبط وكيفية صيانته.
5. اعتمد في إجاباتك على معلومات الكتالوجات المرفقة."""
        }
        tenant_ref = tenants_ref.document()
        tenant_ref.set(tenant_data)
        tenant_id = tenant_ref.id
        
        # إنشاء حساب المدير
        users_ref.document().set({
            "username": "admin",
            "hashed_password": get_password_hash("admin123"),
            "role": "admin",
            "tenant_id": tenant_id
        })
        # إنشاء حساب العامل
        users_ref.document().set({
            "username": "worker",
            "hashed_password": get_password_hash("1234"),
            "role": "worker",
            "tenant_id": tenant_id
        })

# =====================================================================
# تحليل الأعطال التلقائي (Cron Job)
# =====================================================================
def analyze_machine_issues_job():
    logger.info("Starting Daily Cron Job: Analyzing machine issues via Firebase...")
    try:
        tenants = db.collection('tenants').stream()
        for tenant_doc in tenants:
            tenant = tenant_doc.to_dict()
            tenant_id = tenant_doc.id
            if not tenant.get('openai_api_key'): continue
            
            openai_key = decrypt_val(tenant['openai_api_key'])
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            
            # جلب المحادثات لآخر شهر
            history_query = db.collection('conversation_history')\
                .where('tenant_id', '==', tenant_id)\
                .where('created_at', '>=', thirty_days_ago)\
                .order_by('created_at', direction=firestore.Query.DESCENDING)\
                .limit(500).stream()
                
            history_docs = list(history_query)
            if len(history_docs) < 10: continue
            
            text_log = "\n".join([f"{h.to_dict()['role']}: {h.to_dict()['content']}" for h in history_docs])
            prompt = """بصفتك مهندس صيانة ذكي، قم بتحليل سجلات محادثات العمال التالية خلال الشهر الماضي. 
هل تلاحظ وجود عطل في ماكينة معينة يتكرر السؤال عنه؟ إذا وجدت تكراراً يعطي مؤشراً على مشكلة مزمنة، اكتب تنبيهاً واحداً يوضح الماكينة. إذا كانت الأمور طبيعية اكتب فقط 'لا يوجد'."""
            
            try:
                llm = ChatOpenAI(model_name="gpt-4o-mini", openai_api_key=openai_key, temperature=0.0)
                res = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=text_log)])
                if "لا يوجد" not in res.content:
                    db.collection('alerts').document().set({
                        "tenant_id": tenant_id,
                        "message": f"⚠️ تنبيه ذكي: {res.content}",
                        "created_at": firestore.SERVER_TIMESTAMP
                    })
            except Exception as e:
                logger.error(f"Cron LLM error: {e}")
    except Exception as e:
         logger.error(f"Cron Job Error: {e}")

@st.cache_resource
def start_scheduler():
    init_system_data()
    scheduler = BackgroundScheduler()
    scheduler.add_job(analyze_machine_issues_job, 'cron', hour=2, minute=0)
    scheduler.start()
    return True

start_scheduler()

# =====================================================================
# دوال المساعدة لـ Pinecone والـ RAG
# =====================================================================
def get_pinecone_client(api_key):
    if api_key:
        try: return PineconeClient(api_key=api_key)
        except: return None
    return None

def process_document(file_bytes, filename, tenant_dict, tenant_id):
    openai_key = decrypt_val(tenant_dict.get('openai_api_key', ''))
    google_key = decrypt_val(tenant_dict.get('google_api_key', ''))
    pinecone_key = decrypt_val(tenant_dict.get('pinecone_api_key', ''))
    pinecone_index = tenant_dict.get('pinecone_index', '')
    
    pc_client = get_pinecone_client(pinecone_key)
    if not pc_client or not pinecone_index:
        return False, "إعدادات Pinecone غير مكتملة في الإعدادات."

    embeddings = None
    if openai_key: embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
    elif google_key: embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=google_key)
    
    if not embeddings: return False, "مفتاح OpenAI أو Google غير متوفر للتضمين."

    try:
        text_data = ""
        if filename.lower().endswith('.pdf'):
            pdf_reader = PdfReader(io.BytesIO(file_bytes))
            for page in pdf_reader.pages: text_data += (page.extract_text() or "") + "\n"
        else:
            text_data = file_bytes.decode('utf-8')
            
        chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_text(text_data)
        metadatas = [{"filename": filename} for _ in chunks]
        vector_store = PineconeVectorStore(index=pc_client.Index(pinecone_index), embedding=embeddings, namespace=f"tenant_{tenant_id}")
        vector_store.add_texts(texts=chunks, metadatas=metadatas)
        return True, "تم المعالجة والحفظ في Pinecone بنجاح."
    except Exception as e:
        return False, f"خطأ أثناء المعالجة: {str(e)}"

# =====================================================================
# إدارة جلسات Streamlit
# =====================================================================
if "user_id" not in st.session_state: st.session_state.user_id = None
if "user_role" not in st.session_state: st.session_state.user_role = None
if "tenant_id" not in st.session_state: st.session_state.tenant_id = None
if "current_view" not in st.session_state: st.session_state.current_view = "chat"
if "chat_session_uuid" not in st.session_state: st.session_state.chat_session_uuid = None

def logout():
    for key in ["user_id", "user_role", "tenant_id", "chat_session_uuid"]:
        st.session_state[key] = None
    st.session_state.current_view = "chat"
    st.rerun()

# =====================================================================
# الواجهات
# =====================================================================

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
                user_doc = next(users_ref, None)
                if user_doc:
                    user_data = user_doc.to_dict()
                    if verify_password(password, user_data['hashed_password']):
                        st.session_state.user_id = user_doc.id
                        st.session_state.user_role = user_data['role']
                        st.session_state.tenant_id = user_data['tenant_id']
                        st.rerun()
                st.error("بيانات الدخول غير صحيحة يا هندسة.")

def chat_view():
    tenant_doc = db.collection('tenants').document(st.session_state.tenant_id).get()
    tenant = tenant_doc.to_dict()
    user_id = st.session_state.user_id
    
    # --- Sidebar: إدارة الجلسات ---
    with st.sidebar:
        st.markdown(f"<h3 class='text-primary-custom'>أهلاً بك يا بطل</h3>", unsafe_allow_html=True)
        if st.button("➕ محادثة جديدة", use_container_width=True):
            new_uuid = str(uuid.uuid4())
            db.collection('chat_sessions').document(new_uuid).set({
                "session_uuid": new_uuid,
                "title": "محادثة جديدة",
                "user_id": user_id,
                "tenant_id": st.session_state.tenant_id,
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            st.session_state.chat_session_uuid = new_uuid
            st.rerun()
            
        st.divider()
        sessions = list(db.collection('chat_sessions')\
            .where('user_id', '==', user_id)\
            .order_by('updated_at', direction=firestore.Query.DESCENDING).stream())
        
        if not st.session_state.chat_session_uuid and sessions:
            st.session_state.chat_session_uuid = sessions[0].id
        elif not sessions:
            new_uuid = str(uuid.uuid4())
            db.collection('chat_sessions').document(new_uuid).set({
                "session_uuid": new_uuid, "title": "محادثة جديدة", "user_id": user_id, 
                "tenant_id": st.session_state.tenant_id, "updated_at": firestore.SERVER_TIMESTAMP
            })
            st.session_state.chat_session_uuid = new_uuid
            st.rerun()
            
        for s_doc in sessions:
            s_data = s_doc.to_dict()
            s_id = s_data['session_uuid']
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(s_data['title'][:20], key=f"sel_{s_id}", use_container_width=True, type="primary" if s_id == st.session_state.chat_session_uuid else "secondary"):
                    st.session_state.chat_session_uuid = s_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{s_id}"):
                    # مسح الرسائل المرتبطة بالجلسة
                    msgs = db.collection('conversation_history').where('session_id', '==', s_id).stream()
                    for m in msgs: m.reference.delete()
                    # مسح الجلسة
                    db.collection('chat_sessions').document(s_id).delete()
                    if st.session_state.chat_session_uuid == s_id: st.session_state.chat_session_uuid = None
                    st.rerun()

    # --- Main Chat Area ---
    current_session = st.session_state.chat_session_uuid
    if not current_session: return
    
    st.markdown("<h2 class='text-primary-custom'><i class='bi bi-robot'></i> الأسطى بلية</h2>", unsafe_allow_html=True)
    
    # جلب الرسائل من Firestore
    chat_history = list(db.collection('conversation_history')\
        .where('session_id', '==', current_session)\
        .order_by('created_at').stream())
    
    for msg_doc in chat_history:
        msg = msg_doc.to_dict()
        with st.chat_message("user" if msg['role'] == "Worker" else "assistant"):
            st.write(msg['content'])
            if msg['role'] == "AI" and tenant.get('openai_api_key'):
                if st.button("🔊 اسمع الرد", key=f"tts_{msg_doc.id}"):
                    try:
                        client = openai.OpenAI(api_key=decrypt_val(tenant['openai_api_key']))
                        response = client.audio.speech.create(model="tts-1", voice="onyx", input=msg['content'][:1000])
                        st.audio(response.read(), format="audio/mp3", autoplay=True)
                    except Exception as e:
                        st.error("تعذر تشغيل الصوت.")

    # --- Inputs ---
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
            img_base64 = f"data:{img_val.type};base64,{base64.b64encode(img_val.getvalue()).decode()}"
            if not transcribed_text: transcribed_text = "بص على الصورة دي وقولي الحل إيه؟"
            
        if audio_val:
            openai_key = decrypt_val(tenant.get('openai_api_key'))
            if not openai_key:
                st.error("مفتاح OpenAI مطلوب لمعالجة الصوت.")
                return
            try:
                with st.spinner("جاري الاستماع..."):
                    client = openai.OpenAI(api_key=openai_key)
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1", 
                        file=("audio.wav", audio_val.getvalue(), "audio/wav"), 
                        language="ar"
                    )
                    transcribed_text = transcript.text
            except Exception as e:
                st.error(f"خطأ في قراءة الصوت: {e}")
                return

        if transcribed_text or img_base64:
            # تحديث عنوان الجلسة (Firebase)
            sess_ref = db.collection('chat_sessions').document(current_session)
            sess_doc = sess_ref.get()
            if sess_doc.exists and sess_doc.to_dict().get('title') == "محادثة جديدة":
                sess_ref.update({"title": " ".join(transcribed_text.split()[:4]) or "محادثة"})

            with st.chat_message("user"):
                st.write(transcribed_text)
                if img_val: st.image(img_val, width=200)
                
            db.collection('conversation_history').document().set({
                "session_id": current_session,
                "role": "Worker",
                "content": transcribed_text + ("\n[صورة مرفقة]" if img_val else ""),
                "tenant_id": st.session_state.tenant_id,
                "created_at": firestore.SERVER_TIMESTAMP
            })

            # RAG Context
            rag_context = ""
            if any(kw in transcribed_text for kw in ["ضاغط", "مجفف", "صيانة", "عطل", "بايظ", "مشكلة"]):
                pc_client = get_pinecone_client(decrypt_val(tenant.get('pinecone_api_key')))
                if pc_client and tenant.get('pinecone_index'):
                    try:
                        emb_key = decrypt_val(tenant.get('openai_api_key'))
                        g_key = decrypt_val(tenant.get('google_api_key'))
                        embeddings = OpenAIEmbeddings(openai_api_key=emb_key) if emb_key else GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=g_key) if g_key else None
                        if embeddings:
                            vstore = PineconeVectorStore(index=pc_client.Index(tenant['pinecone_index']), embedding=embeddings, namespace=f"tenant_{st.session_state.tenant_id}")
                            docs = vstore.similarity_search(transcribed_text, k=2)
                            rag_context = "\n".join([d.page_content for d in docs])
                    except Exception as e:
                        logger.error(f"RAG Error: {e}")

            # LLM Response
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                try:
                    provider = tenant.get('llm_provider', 'google')
                    model_name = tenant.get('llm_model', 'gemini-1.5-flash')
                    base_url = tenant.get('api_base_url', '')
                    llm = None
                    
                    if provider == "openai":
                        llm = ChatOpenAI(model_name=model_name, openai_api_key=decrypt_val(tenant.get('openai_api_key')), temperature=0.3, base_url=base_url if base_url else None)
                    elif provider == "anthropic":
                        llm = ChatAnthropic(model_name=model_name, api_key=decrypt_val(tenant.get('anthropic_api_key')), temperature=0.3, base_url=base_url if base_url else None)
                    elif provider == "google":
                        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=decrypt_val(tenant.get('google_api_key')), temperature=0.3)
                    elif provider == "custom":
                        llm = ChatOpenAI(model_name=model_name, openai_api_key=decrypt_val(tenant.get('openai_api_key')) or "sk-custom", temperature=0.3, base_url=base_url)
                    
                    if not llm:
                        st.error("لم يتم التعرف على مزود الخدمة أو المفاتيح ناقصة.")
                    else:
                        hist_text = "\n".join([f"{h.to_dict()['role']}: {h.to_dict()['content']}" for h in chat_history[-3:]])
                        sys_prompt = f"{tenant.get('workshop_prompt')}\n\nتاريخ المحادثة:\n{hist_text}\n\nمعلومات من الكتالوجات:\n{rag_context}"
                        
                        human_msg_content = [{"type": "text", "text": transcribed_text}]
                        if img_base64: human_msg_content.append({"type": "image_url", "image_url": {"url": img_base64}})
                        
                        messages = [SystemMessage(content=sys_prompt), HumanMessage(content=human_msg_content)]
                        
                        for chunk in llm.stream(messages):
                            full_response += chunk.content
                            message_placeholder.markdown(full_response + "▌")
                        message_placeholder.markdown(full_response)
                        
                        db.collection('conversation_history').document().set({
                            "session_id": current_session,
                            "role": "AI",
                            "content": full_response,
                            "tenant_id": st.session_state.tenant_id,
                            "created_at": firestore.SERVER_TIMESTAMP
                        })
                        
                except Exception as e:
                    message_placeholder.markdown(f"❌ حدث خطأ: {e}")
                    
            st.rerun()

def admin_dashboard():
    st.markdown("<h2 class='text-primary-custom'>لوحة تحكم الورشة</h2>", unsafe_allow_html=True)
    tenant_id = st.session_state.tenant_id
    
    chats_count = len(list(db.collection('conversation_history').where('tenant_id', '==', tenant_id).stream()))
    workers_count = len(list(db.collection('users').where('tenant_id', '==', tenant_id).where('role', '==', 'worker').stream()))
    
    col1, col2, col3 = st.columns(3)
    col1.markdown(f"<div class='custom-card'><h3 class='text-primary-custom'>{chats_count}</h3><p>الرسائل والاستفسارات</p></div>", unsafe_allow_html=True)
    col2.markdown(f"<div class='custom-card'><h3 class='text-info-custom'>{workers_count}</h3><p>عدد العمال</p></div>", unsafe_allow_html=True)
    col3.markdown(f"<div class='custom-card'><h3 class='text-success-custom'>--</h3><p>الوضع</p></div>", unsafe_allow_html=True)

    st.subheader("⚠️ التنبيهات الذكية (الأعطال المتكررة)")
    alerts = list(db.collection('alerts').where('tenant_id', '==', tenant_id).order_by('created_at', direction=firestore.Query.DESCENDING).limit(5).stream())
    
    if alerts:
        for a in alerts:
            a_data = a.to_dict()
            date_str = a_data['created_at'].strftime('%Y-%m-%d') if 'created_at' in a_data else ''
            st.warning(f"[{date_str}] {a_data['message']}")
    else:
        st.info("لا توجد تنبيهات مؤخراً. الوضع مستقر!")

def admin_users():
    st.header("إدارة العمال")
    tenant_id = st.session_state.tenant_id
    
    with st.expander("➕ إضافة مستخدم جديد", expanded=False):
        with st.form("add_user"):
            new_user = st.text_input("اسم المستخدم")
            new_pass = st.text_input("كلمة السر", type="password")
            new_role = st.selectbox("الصلاحية", ["worker", "admin"])
            if st.form_submit_button("إضافة"):
                existing = list(db.collection('users').where('username', '==', new_user).stream())
                if not existing:
                    db.collection('users').document().set({
                        "username": new_user,
                        "hashed_password": get_password_hash(new_pass),
                        "role": new_role,
                        "tenant_id": tenant_id
                    })
                    st.success("تم الإضافة!")
                    st.rerun()
                else:
                    st.error("المستخدم موجود مسبقاً.")

    st.subheader("قائمة المستخدمين")
    users = db.collection('users').where('tenant_id', '==', tenant_id).stream()
    for u_doc in users:
        u = u_doc.to_dict()
        col1, col2, col3 = st.columns([3, 2, 1])
        col1.write(u['username'])
        col2.write("مدير" if u['role'] == "admin" else "عامل")
        if u_doc.id != st.session_state.user_id and col3.button("حذف", key=f"del_u_{u_doc.id}"):
            u_doc.reference.delete()
            st.rerun()

def admin_rag():
    st.header("الكتالوجات والملفات (RAG)")
    tenant_id = st.session_state.tenant_id
    tenant_dict = db.collection('tenants').document(tenant_id).get().to_dict()
    
    uploaded_files = st.file_uploader("ارفع ملفات (PDF, TXT)", type=["pdf", "txt"], accept_multiple_files=True)
    if uploaded_files:
        if st.button("معالجة وحفظ في الذاكرة"):
            for f in uploaded_files:
                existing = list(db.collection('uploaded_documents').where('filename', '==', f.name).where('tenant_id', '==', tenant_id).stream())
                if not existing:
                    with st.spinner(f"جاري معالجة {f.name}..."):
                        success, msg = process_document(f.getvalue(), f.name, tenant_dict, tenant_id)
                        if success:
                            db.collection('uploaded_documents').document().set({
                                "filename": f.name,
                                "tenant_id": tenant_id
                            })
                            st.success(f"تم حفظ {f.name}")
                        else:
                            st.error(msg)
                else:
                    st.warning(f"الملف {f.name} مرفوع مسبقاً.")
    
    st.subheader("الملفات المحفوظة")
    docs = db.collection('uploaded_documents').where('tenant_id', '==', tenant_id).stream()
    for d_doc in docs:
        d = d_doc.to_dict()
        col1, col2 = st.columns([4, 1])
        col1.write(f"📄 {d['filename']}")
        if col2.button("حذف", key=f"del_doc_{d_doc.id}"):
            try:
                pc_client = get_pinecone_client(decrypt_val(tenant_dict.get('pinecone_api_key')))
                if pc_client and tenant_dict.get('pinecone_index'):
                    pc_client.Index(tenant_dict['pinecone_index']).delete(filter={"filename": d['filename']}, namespace=f"tenant_{tenant_id}")
            except Exception as e: logger.error(e)
            d_doc.reference.delete()
            st.rerun()

def admin_settings():
    st.header("إعدادات النظام والتخصيص")
    tenant_id = st.session_state.tenant_id
    tenant_ref = db.collection('tenants').document(tenant_id)
    t = tenant_ref.get().to_dict()
    
    tab1, tab2, tab3 = st.tabs(["النماذج (LLM)", "الذاكرة (Pinecone)", "الشخصية (Prompt)"])
    
    with tab1:
        with st.form("llm_settings"):
            providers = ["google", "openai", "anthropic", "custom"]
            current_provider = t.get('llm_provider', 'google')
            provider_index = providers.index(current_provider) if current_provider in providers else 0
            
            provider = st.selectbox("مزود الخدمة", providers, index=provider_index)
            model = st.text_input("اسم الموديل", value=t.get('llm_model', ''))
            base_url = st.text_input("الرابط المخصص (Base URL)", value=t.get('api_base_url', ''))
            o_key = st.text_input("مفتاح OpenAI (مطلوب للصوت)", value=decrypt_val(t.get('openai_api_key', '')), type="password")
            a_key = st.text_input("مفتاح Anthropic", value=decrypt_val(t.get('anthropic_api_key', '')), type="password")
            g_key = st.text_input("مفتاح Google Gemini", value=decrypt_val(t.get('google_api_key', '')), type="password")
            
            if st.form_submit_button("حفظ إعدادات النماذج"):
                tenant_ref.update({
                    "llm_provider": provider, "llm_model": model, "api_base_url": base_url,
                    "openai_api_key": encrypt_val(o_key), "anthropic_api_key": encrypt_val(a_key), "google_api_key": encrypt_val(g_key)
                })
                st.success("تم الحفظ بنجاح.")
                
    with tab2:
        with st.form("pinecone_settings"):
            p_key = st.text_input("Pinecone API Key", value=decrypt_val(t.get('pinecone_api_key', '')), type="password")
            p_index = st.text_input("Pinecone Index Name", value=t.get('pinecone_index', ''))
            if st.form_submit_button("حفظ إعدادات الذاكرة"):
                tenant_ref.update({"pinecone_api_key": encrypt_val(p_key), "pinecone_index": p_index})
                st.success("تم الحفظ بنجاح.")
                
    with tab3:
        with st.form("prompt_settings"):
            prompt = st.text_area("شخصية المساعد (System Prompt)", value=t.get('workshop_prompt', ''), height=200)
            if st.form_submit_button("تحديث الشخصية"):
                tenant_ref.update({"workshop_prompt": prompt})
                st.success("تم الحفظ بنجاح.")

# =====================================================================
# Main Routing
# =====================================================================
def main():
    if not st.session_state.user_id:
        login_view()
        return
        
    user_doc = db.collection('users').document(st.session_state.user_id).get()
    if not user_doc.exists:
        logout()
        return
    user = user_doc.to_dict()
    
    with st.sidebar:
        st.markdown(f"**تسجيل الدخول كـ:** {user['username']}")
        if user['role'] == "admin":
            st.session_state.current_view = st.radio("القائمة الرئيسية", ["المحادثة (Kiosk)", "لوحة التحكم", "العمال", "الكتالوجات (RAG)", "الإعدادات"])
        else:
            st.session_state.current_view = "المحادثة (Kiosk)"
            
        st.markdown("---")
        if st.button("تسجيل الخروج 🚪", use_container_width=True):
            logout()
            
    view = st.session_state.current_view
    if view == "المحادثة (Kiosk)": chat_view()
    elif view == "لوحة التحكم": admin_dashboard()
    elif view == "العمال": admin_users()
    elif view == "الكتالوجات (RAG)": admin_rag()
    elif view == "الإعدادات": admin_settings()

if __name__ == "__main__":
    main()
