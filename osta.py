import streamlit as st
import os
import tempfile
import time
import hashlib
import base64
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import streamlit.components.v1 as components

# ==========================================
# 1. إعدادات الصفحة الأساسية
# ==========================================
st.set_page_config(
    page_title="Osta Chat | Enterprise",
    page_icon="🔧", # Streamlit requires an emoji for the favicon, but UI will use icons
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. تصميم الواجهة (WhatsApp Dark Theme & FontAwesome)
# ==========================================
WHATSAPP_CSS = """
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Tajawal', sans-serif !important;
        direction: rtl; text-align: right;
    }
    
    /* WhatsApp Dark Background */
    .stApp {
        background-color: #0b141a !important;
        background-image: url("https://user-images.githubusercontent.com/15075759/28719144-86dc0f70-73b1-11e7-911d-60d70fcded21.png");
        background-blend-mode: overlay;
        color: #e9edef;
    }

    #MainMenu, footer, header {visibility: hidden;}
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: #111b21 !important;
        border-left: 1px solid #222d34;
    }
    
    /* Input Fields */
    .stTextInput input, .stTextArea textarea, .stSelectbox select, .stNumberInput input {
        background-color: #2a3942 !important;
        color: #d1d7db !important;
        border: 1px solid #2a3942 !important;
        border-radius: 8px !important;
        padding: 12px;
    }
    .stTextInput input:focus, .stTextArea textarea:focus { border-color: #00a884 !important; }

    /* Buttons */
    .stButton > button {
        background-color: #00a884 !important;
        color: #111b21 !important; 
        border: none !important; 
        border-radius: 24px !important;
        font-weight: 700 !important; 
        transition: all 0.2s !important; 
        width: 100%;
        padding: 10px;
    }
    .stButton > button:hover { background-color: #00c298 !important; }
    .btn-logout > button { background-color: #ef4444 !important; color: white !important; }
    .btn-icon > button { background-color: #202c33 !important; color: #8696a0 !important; border-radius: 50% !important; padding: 15px !important;}
    .btn-icon > button:hover { background-color: #2a3942 !important; color: #d1d7db !important;}
    
    /* Chat Bubbles */
    [data-testid="stChatMessage"] {
        background-color: transparent !important;
        padding: 0 !important;
        margin-bottom: 15px;
    }
    
    /* User Bubble */
    [data-testid="stChatMessage"]:nth-child(odd) .stMarkdown {
        background-color: #005c4b;
        color: #e9edef;
        padding: 10px 15px;
        border-radius: 12px 0 12px 12px;
        max-width: 80%;
        float: right;
        clear: both;
        box-shadow: 0 1px 2px rgba(0,0,0,0.3);
    }
    
    /* Assistant Bubble */
    [data-testid="stChatMessage"]:nth-child(even) .stMarkdown {
        background-color: #202c33;
        color: #e9edef;
        padding: 10px 15px;
        border-radius: 0 12px 12px 12px;
        max-width: 80%;
        float: left;
        clear: both;
        box-shadow: 0 1px 2px rgba(0,0,0,0.3);
    }
    
    /* Hide native avatars for cleaner WhatsApp look */
    [data-testid="stChatMessage"] .stImage, [data-testid="stChatMessage"] div[data-testid="stIcon"] {
        display: none !important;
    }

    /* Metric Cards */
    .metric-box {
        text-align: center;
        padding: 20px;
        background-color: #202c33;
        border-radius: 12px;
        border: 1px solid #2a3942;
    }
    .metric-value { font-size: 2rem; font-weight: 800; color: #00a884; }
    .metric-title { font-size: 1rem; color: #8696a0; }
    
    /* Custom Icon Wrapper */
    .icon-title {
        display: flex; align-items: center; gap: 10px; color: #e9edef; font-size: 1.5rem; font-weight: bold; margin-bottom: 20px;
    }
    .icon-title i { color: #00a884; }
</style>
"""
st.markdown(WHATSAPP_CSS, unsafe_allow_html=True)

## ==========================================
# 3. إعدادات Firebase وقاعدة البيانات
# ==========================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        if "firebase" in st.secrets:
            cred = credentials.Certificate(dict(st.secrets["firebase"]))
            firebase_admin.initialize_app(cred)
        else:
            st.warning("يرجى إضافة إعدادات Firebase في Streamlit Secrets.")
            return None
    return firestore.client()

db = init_firebase()

def init_default_data():
    if db is None: return
    users_ref = db.collection('users')
    if not list(users_ref.where('username', '==', 'admin').limit(1).stream()):
        users_ref.add({'username': 'admin', 'password': hashlib.sha256(b'admin2024').hexdigest(), 'role': 'Manager'})
    if not list(users_ref.where('username', '==', 'worker').limit(1).stream()):
        users_ref.add({'username': 'worker', 'password': hashlib.sha256(b'worker').hexdigest(), 'role': 'Worker'})
    
    settings_ref = db.collection('settings')
    default_settings = {
        'llm_provider': 'OpenAI',
        'llm_model': 'gpt-4o-mini',
        'temperature': '0.2',
        'chunk_size': '1000',
        'chunk_overlap': '150',
        'k_results': '4',
        'tts_voice': 'onyx',
        'use_openai_tts': 'True',
        'system_prompt': "أنت 'أسطى كبير' مصري محترف في صيانة ضواغط الهواء والتصنيع المعدني. كلامك بلهجة صنايعية بسيطة وفي خطوات. استخدم [المعلومات المرفقة] فقط.",
        'index_name': 'osta-enterprise-rag'
    }
    for k, v in default_settings.items():
        if not settings_ref.document(k).get().exists:
            settings_ref.document(k).set({'value': str(v)})

init_default_data()

def get_setting(key, default=""):
    if db is None: return default
    doc = db.collection('settings').document(key).get()
    return doc.to_dict().get('value', default) if doc.exists else default

def set_setting(key, value):
    if db is None: return
    db.collection('settings').document(key).set({'value': str(value)})

## ==========================================
# 4. الاعتماديات المتأخرة والـ LLMs
# ==========================================
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_pinecone import PineconeVectorStore
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from audio_recorder_streamlit import audio_recorder

def get_llm():
    provider = get_setting('llm_provider')
    temp = float(get_setting('temperature', 0.2))
    
    if provider == 'Google Gemini':
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=get_setting('gemini_model', 'gemini-1.5-flash'), 
                                      google_api_key=get_setting('google_api_key'), temperature=temp)
    elif provider == 'Anthropic':
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=get_setting('anthropic_model', 'claude-3-haiku-20240307'), 
                             api_key=get_setting('anthropic_api_key'), temperature=temp)
    elif provider == 'Custom URL':
        return ChatOpenAI(model=get_setting('custom_model', 'local-model'), 
                          openai_api_base=get_setting('custom_base_url'), 
                          openai_api_key=get_setting('custom_api_key', 'dummy'), temperature=temp)
    else:
        return ChatOpenAI(model=get_setting('llm_model', 'gpt-4o-mini'), 
                          openai_api_key=get_setting('openai_api_key'), temperature=temp)

## ==========================================
# 5. دوال الصوت والميديا (TTS & STT)
# ==========================================
def generate_audio_player_html(text):
    api_key = get_setting('openai_api_key')
    use_tts = get_setting('use_openai_tts', 'True') == 'True'
    
    if not api_key or not use_tts:
        return "" # No TTS player if disabled or no key
        
    try:
        client = OpenAI(api_key=api_key)
        response = client.audio.speech.create(
            model="tts-1", voice=get_setting('tts_voice', 'onyx'), input=text
        )
        audio_b64 = base64.b64encode(response.content).decode('utf-8')
        # Custom HTML Audio Player with Autoplay and Controls
        html_player = f"""
        <div style="margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 10px;">
            <audio controls autoplay style="width: 100%; height: 35px; border-radius: 20px;">
                <source src="data:audio/mp3;base64,{audio_b64}" type="audio/mp3">
                Your browser does not support the audio element.
            </audio>
        </div>
        """
        return html_player
    except Exception as e:
        return f"<div style='color:red; font-size:12px;'>خطأ في توليد الصوت: {e}</div>"

def transcribe_audio(audio_bytes):
    api_key = get_setting('openai_api_key')
    if not api_key: return "تحويل الصوت لنص يتطلب OpenAI API Key."
    client = OpenAI(api_key=api_key)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
        tmp_audio.write(audio_bytes)
        tmp_audio_path = tmp_audio.name
    with open(tmp_audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file, language="ar")
    os.unlink(tmp_audio_path)
    return transcript.text

def process_documents(uploaded_files):
    os.environ['OPENAI_API_KEY'] = get_setting('openai_api_key')
    pc = Pinecone(api_key=get_setting('pinecone_api_key'))
    idx_name = get_setting('index_name')
    if idx_name not in pc.list_indexes().names():
        pc.create_index(name=idx_name, dimension=1536, metric='cosine', spec=ServerlessSpec(cloud='aws', region='us-east-1'))
        while not pc.describe_index(idx_name).status['ready']: time.sleep(1)
    
    index = pc.Index(idx_name)
    vector_store = PineconeVectorStore(index=index, embedding=OpenAIEmbeddings(), text_key="text")
    all_docs = []
    
    for uf in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uf.name.split('.')[-1]}") as tmp:
            tmp.write(uf.getvalue())
            tmp_path = tmp.name
        
        loader = None
        if uf.name.endswith('.pdf'): loader = PyPDFLoader(tmp_path)
        elif uf.name.endswith('.txt'): loader = TextLoader(tmp_path, encoding='utf-8')
        elif uf.name.endswith('.docx'): loader = Docx2txtLoader(tmp_path)
        
        if loader:
            docs = loader.load()
            splitter = RecursiveCharacterTextSplitter(chunk_size=int(get_setting('chunk_size', 1000)), chunk_overlap=int(get_setting('chunk_overlap', 150)))
            all_docs.extend(splitter.split_documents(docs))
        os.unlink(tmp_path)
        
    if all_docs:
        vector_store.add_documents(all_docs)
        return len(all_docs)
    return 0

## ==========================================
# 6. واجهات النظام (Views)
# ==========================================
if 'user_id' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'user_id': None, 'username': None, 'current_session': None})

def render_login():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
            <div style="text-align: center; margin-bottom: 30px;">
                <i class="fa-brands fa-whatsapp" style="font-size: 5rem; color: #00a884;"></i>
                <h1 style="color: #e9edef; font-size: 2rem;">OSTA Chat</h1>
                <p style="color: #8696a0;">بوابة دخول النظام الصناعي</p>
            </div>
        """, unsafe_allow_html=True)
        
        user = st.text_input("اسم المستخدم", placeholder="أدخل اسم المستخدم هنا")
        pwd = st.text_input("كلمة المرور", type="password", placeholder="••••••••")
        if st.button("تسجيل الدخول"):
            if db is None:
                st.error("قاعدة البيانات غير متصلة.")
                return
            hashed_pwd = hashlib.sha256(pwd.encode()).hexdigest()
            users_ref = list(db.collection('users').where('username', '==', user).where('password', '==', hashed_pwd).limit(1).stream())
            
            if users_ref:
                user_data = users_ref[0].to_dict()
                st.session_state.update({'logged_in': True, 'user_id': users_ref[0].id, 'role': user_data['role'], 'username': user})
                st.rerun()
            else:
                st.error("بيانات الدخول غير صحيحة.")

def render_admin_dashboard():
    with st.sidebar:
        st.markdown(f"<div class='icon-title'><i class='fa-solid fa-user-shield'></i> أهلاً، {st.session_state['username']}</div>", unsafe_allow_html=True)
        menu = st.radio("", [
            "📊 لوحة التحكم والإحصائيات", 
            "👥 إدارة المستخدمين", 
            "⚙️ الإعدادات المتقدمة", 
            "📚 قاعدة البيانات والتدريب"
        ])
        st.markdown("<div class='btn-logout'>", unsafe_allow_html=True)
        if st.button("تسجيل الخروج"):
            st.session_state.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    if "إحصائيات" in menu:
        st.markdown("<div class='icon-title'><i class='fa-solid fa-chart-line'></i> لوحة تحكم النظام</div>", unsafe_allow_html=True)
        if db is None: return
        
        workers_count = sum(1 for _ in db.collection('users').where('role', '==', 'Worker').stream())
        msgs_count = sum(1 for _ in db.collection('messages').stream())
        sessions_count = sum(1 for _ in db.collection('chat_sessions').stream())
        
        col1, col2, col3 = st.columns(3)
        with col1: st.markdown(f"<div class='metric-box'><div class='metric-value'>{workers_count}</div><div class='metric-title'>فرق العمل</div></div>", unsafe_allow_html=True)
        with col2: st.markdown(f"<div class='metric-box'><div class='metric-value'>{msgs_count}</div><div class='metric-title'>إجمالي الرسائل المرسلة</div></div>", unsafe_allow_html=True)
        with col3: st.markdown(f"<div class='metric-box'><div class='metric-value'>{sessions_count}</div><div class='metric-title'>جلسات المحادثة</div></div>", unsafe_allow_html=True)

    elif "المستخدمين" in menu:
        st.markdown("<div class='icon-title'><i class='fa-solid fa-users-cog'></i> إدارة المستخدمين</div>", unsafe_allow_html=True)
        if db is None: return
        with st.form("add_user"):
            nu = st.text_input("اسم المستخدم الجديد")
            np = st.text_input("كلمة المرور", type="password")
            nr = st.selectbox("الصلاحية", ["Worker", "Manager"])
            if st.form_submit_button("إضافة مستخدم"):
                if list(db.collection('users').where('username', '==', nu).limit(1).stream()):
                    st.error("المستخدم موجود بالفعل.")
                else:
                    db.collection('users').add({'username': nu, 'password': hashlib.sha256(np.encode()).hexdigest(), 'role': nr})
                    st.success("تم بنجاح!")
        
        st.markdown("---")
        users = db.collection('users').stream()
        for u in users:
            u_data = u.to_dict()
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"<i class='fa-solid fa-user'></i> **{u_data['username']}** ({u_data['role']})", unsafe_allow_html=True)
            if u_data['username'] != 'admin' and c2.button("حذف", key=f"del_{u.id}"):
                db.collection('users').document(u.id).delete()
                st.rerun()

    elif "الإعدادات" in menu:
        st.markdown("<div class='icon-title'><i class='fa-solid fa-sliders'></i> الإعدادات والتكوين</div>", unsafe_allow_html=True)
        t1, t2, t3 = st.tabs(["🤖 إعدادات المحرك (LLM)", "🗣️ الشخصية والصوت (Persona)", "🔎 خوارزميات البحث (RAG)"])
        
        with t1:
            provider = st.selectbox("المزود (Provider)", ["OpenAI", "Google Gemini", "Anthropic", "Custom URL"], index=["OpenAI", "Google Gemini", "Anthropic", "Custom URL"].index(get_setting('llm_provider', 'OpenAI')))
            set_setting('llm_provider', provider)
            if provider == "OpenAI":
                set_setting('openai_api_key', st.text_input("OpenAI API Key", get_setting('openai_api_key'), type="password"))
                set_setting('llm_model', st.selectbox("Model", ["gpt-4o", "gpt-4o-mini"], index=0 if get_setting('llm_model')=='gpt-4o' else 1))
            elif provider == "Google Gemini":
                set_setting('google_api_key', st.text_input("Google API Key", get_setting('google_api_key'), type="password"))
                set_setting('gemini_model', st.text_input("Model Name", get_setting('gemini_model', 'gemini-1.5-flash')))
            elif provider == "Anthropic":
                set_setting('anthropic_api_key', st.text_input("Anthropic API Key", get_setting('anthropic_api_key'), type="password"))
                set_setting('anthropic_model', st.text_input("Model Name", get_setting('anthropic_model', 'claude-3-haiku-20240307')))
            elif provider == "Custom URL":
                set_setting('custom_base_url', st.text_input("Base URL", get_setting('custom_base_url', 'http://localhost:11434/v1')))
                set_setting('custom_api_key', st.text_input("API Key (Optional)", get_setting('custom_api_key', 'dummy'), type="password"))
                set_setting('custom_model', st.text_input("Model Name", get_setting('custom_model', 'llama3')))
                
            set_setting('pinecone_api_key', st.text_input("Pinecone API Key", get_setting('pinecone_api_key'), type="password"))
            set_setting('temperature', st.slider("مستوى الإبداع (Temperature)", 0.0, 1.0, float(get_setting('temperature', 0.2))))
            
        with t2:
            set_setting('system_prompt', st.text_area("تعليمات الذكاء الاصطناعي (System Prompt)", get_setting('system_prompt'), height=150))
            set_setting('use_openai_tts', st.checkbox("تفعيل النطق التلقائي (Auto-TTS)", value=(get_setting('use_openai_tts', 'True')=='True')))
            set_setting('tts_voice', st.selectbox("نبرة الصوت (OpenAI Voices)", ["onyx", "echo", "alloy", "fable", "nova", "shimmer"], index=0))

        with t3:
            set_setting('chunk_size', st.number_input("حجم القطعة (Chunk Size)", value=int(get_setting('chunk_size', 1000))))
            set_setting('chunk_overlap', st.number_input("التداخل (Chunk Overlap)", value=int(get_setting('chunk_overlap', 150))))
            set_setting('k_results', st.number_input("عدد النتائج المسترجعة (K)", value=int(get_setting('k_results', 4))))

    elif "التدريب" in menu:
        st.markdown("<div class='icon-title'><i class='fa-solid fa-database'></i> مركز المعرفة (Knowledge Base)</div>", unsafe_allow_html=True)
        set_setting('index_name', st.text_input("Pinecone Index Name", get_setting('index_name')))
        uf = st.file_uploader("ارفع أدلة الصيانة والتشغيل (PDF, TXT, DOCX)", accept_multiple_files=True)
        if st.button("تحديث الذاكرة"):
            if uf and get_setting('pinecone_api_key'):
                with st.spinner("جاري الحقن في قاعدة البيانات..."):
                    cnt = process_documents(uf)
                    st.success(f"تم حقن {cnt} وحدة معرفية بنجاح.")
            else:
                st.error("مفاتيح أو ملفات مفقودة.")

#def render_worker_chat():
    if db is None: return
    uid = st.session_state['user_id']
    
    # Sidebar (Chats List)
    with st.sidebar:
        st.markdown("<div style='text-align:center; padding:10px;'><i class='fa-brands fa-whatsapp' style='font-size:3rem; color:#00a884;'></i><br><b style='font-size:1.2rem; color:#e9edef;'>محادثاتي</b></div>", unsafe_allow_html=True)
        if st.button("➕ محادثة جديدة"):
            res = db.collection('chat_sessions').add({'user_id': uid, 'title': f"استشارة {datetime.now().strftime('%H:%M')}", 'created_at': datetime.now()})
            st.session_state['current_session'] = res[1].id
            st.rerun()
            
        sessions = list(db.collection('chat_sessions').where('user_id', '==', uid).stream())
        sessions.sort(key=lambda x: x.to_dict().get('created_at', ''), reverse=True)
        
        for sess in sessions:
            s_data = sess.to_dict()
            c1, c2 = st.columns([4, 1])
            if c1.button(f"💬 {s_data['title'][:15]}", key=f"sess_{sess.id}"):
                st.session_state['current_session'] = sess.id
                st.rerun()
            if c2.button("🗑️", key=f"del_{sess.id}"):
                db.collection('chat_sessions').document(sess.id).delete()
                for m in db.collection('messages').where('session_id', '==', sess.id).stream():
                    db.collection('messages').document(m.id).delete()
                if st.session_state['current_session'] == sess.id: st.session_state['current_session'] = None
                st.rerun()
                
        st.markdown("<div class='btn-logout' style='position:absolute; bottom:10px; width:90%;'>", unsafe_allow_html=True)
        if st.button("خروج"):
            st.session_state.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # Auto Create Session
    if not st.session_state.get('current_session'):
        if sessions: st.session_state['current_session'] = sessions[0].id
        else:
            res = db.collection('chat_sessions').add({'user_id': uid, 'title': f"محادثة {datetime.now().strftime('%H:%M')}", 'created_at': datetime.now()})
            st.session_state['current_session'] = res[1].id

    sid = st.session_state['current_session']
    
    # Chat Area
    msgs = list(db.collection('messages').where('session_id', '==', sid).stream())
    msgs.sort(key=lambda x: x.to_dict().get('timestamp', ''))
    
    for m in msgs:
        m_data = m.to_dict()
        if m_data['role'] == 'user':
            with st.chat_message("user"):
                st.markdown(m_data['content'])
                if m_data.get('image_b64'): st.image(base64.b64decode(m_data['image_b64']))
        else:
            with st.chat_message("assistant"):
                st.markdown(m_data['content'])
                if m_data.get('audio_html'): st.markdown(m_data['audio_html'], unsafe_allow_html=True)

    st.markdown("<div style='height: 100px;'></div>", unsafe_allow_html=True) # Spacer

    # Bottom Input Bar (WhatsApp Style)
    col_tools, col_input = st.columns([1, 5])
    
    with col_tools:
        with st.popover("📎"):
            audio_bytes = audio_recorder("🎙️ سجل رسالة صوتية", icon_size="2x", neutral_color="#8696a0", recording_color="#00a884")
            img_file = st.camera_input("📸 صورة")
            
    prompt = st.chat_input("اكتب رسالة...")
    
    if audio_bytes and get_setting('openai_api_key'):
        with st.spinner("جاري الاستماع..."): prompt = transcribe_audio(audio_bytes)

    if prompt or img_file:
        img_b64 = base64.b64encode(img_file.getvalue()).decode() if img_file else None
        
        # Display User Input
        with st.chat_message("user"):
            st.markdown(prompt)
            if img_file: st.image(img_file)
            
        db.collection('messages').add({
            'session_id': sid, 'role': 'user', 'content': prompt, 'image_b64': img_b64, 'timestamp': datetime.now()
        })
        
        # Fetch RAG Context
        context = ""
        if get_setting('pinecone_api_key'):
            try:
                os.environ['OPENAI_API_KEY'] = get_setting('openai_api_key')
                pc = Pinecone(api_key=get_setting('pinecone_api_key'))
                idx = pc.Index(get_setting('index_name'))
                vs = PineconeVectorStore(index=idx, embedding=OpenAIEmbeddings(), text_key="text")
                docs = vs.similarity_search(prompt, k=int(get_setting('k_results', 4)))
                context = "\n\n".join([d.page_content for d in docs])
            except: pass

        sys_msg = get_setting('system_prompt')
        full_prompt = f"المعلومات:\n{context}\n\nالسؤال: {prompt}"
        lc_msgs = [{"role": "system", "content": sys_msg}]
        if img_b64:
            lc_msgs.append({"role": "user", "content": [{"type": "text", "text": full_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}]})
        else:
            lc_msgs.append({"role": "user", "content": full_prompt})

        # Display AI Stream & Generate TTS
        with st.chat_message("assistant"):
            try:
                llm = get_llm()
                answer = st.write_stream(llm.stream(lc_msgs)) 
                
                # Generate Audio Player
                audio_html = generate_audio_player_html(answer)
                if audio_html: st.markdown(audio_html, unsafe_allow_html=True)
                
                db.collection('messages').add({
                    'session_id': sid, 'role': 'assistant', 'content': answer, 'audio_html': audio_html, 'timestamp': datetime.now()
                })
            except Exception as e:
                st.error(f"خطأ في الاتصال بالمحرك: {e}")

def main():
    if not st.session_state['logged_in']:
        render_login()
    else:
        if st.session_state['role'] == "Manager":
            render_admin_dashboard()
        elif st.session_state['role'] == "Worker":
            render_worker_chat()

if __name__ == "__main__":
    main()
