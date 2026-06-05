import os
import io
import json
import base64
import hashlib
from datetime import datetime, timezone
import re

import streamlit as st
import streamlit.components.v1 as components
import bcrypt
import pandas as pd
from cryptography.fernet import Fernet
from pypdf import PdfReader

# --- Firebase ---
import firebase_admin
from firebase_admin import credentials, firestore

# --- AI & LangChain ---
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

# =====================================================================
# 1. إعدادات واجهة Streamlit وحقن تصميم النيون (CSS Injection)
# =====================================================================
st.set_page_config(page_title="نظام الدريني للورش", page_icon="⚙️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Cairo', sans-serif !important;
        direction: rtl !important;
        text-align: right !important;
    }

    /* الخلفية الرئيسية للتطبيق */
    .stApp {
        background-color: #0A0E17 !important;
        background-image: radial-gradient(circle at 15% 50%, rgba(176, 38, 255, 0.05), transparent 25%), 
                          radial-gradient(circle at 85% 30%, rgba(0, 240, 255, 0.05), transparent 25%) !important;
        color: #E2E8F0 !important;
    }

    h1, h2, h3, h4, h5, h6, p, label, span { color: #FFF !important; }
    
    /* شريط التنقل الجانبي */
    [data-testid="stSidebar"] {
        background-color: rgba(10, 14, 23, 0.95) !important;
        border-left: 1px solid rgba(0, 240, 255, 0.1) !important;
    }
    
    /* الأزرار الأساسية (النيون) */
    .stButton > button {
        background-color: transparent !important;
        border: 1px solid #00F0FF !important;
        color: #00F0FF !important;
        border-radius: 14px !important;
        box-shadow: inset 0 0 10px rgba(0, 240, 255, 0.1), 0 0 10px rgba(0, 240, 255, 0.2) !important;
        font-weight: bold !important;
        transition: all 0.3s ease !important;
    }
    .stButton > button:hover {
        background-color: #00F0FF !important;
        color: #000 !important;
        box-shadow: 0 0 20px #00F0FF !important;
    }

    /* أزرار الحذف/الخطر */
    button[kind="secondary"] {
        border-color: #FF003C !important;
        color: #FF003C !important;
        box-shadow: inset 0 0 10px rgba(255, 0, 60, 0.1) !important;
    }
    button[kind="secondary"]:hover {
        background-color: #FF003C !important;
        color: #FFF !important;
        box-shadow: 0 0 20px #FF003C !important;
    }

    /* حقول الإدخال */
    .stTextInput > div > div > input, .stSelectbox > div > div > select, .stTextArea > div > div > textarea {
        background-color: rgba(0,0,0,0.5) !important;
        color: #00F0FF !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 14px !important;
    }
    .stTextInput > div > div > input:focus, .stTextArea > div > div > textarea:focus {
        border-color: #00F0FF !important;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.3) !important;
    }

    /* المحادثة والشات */
    [data-testid="stChatMessage"] {
        background-color: rgba(16, 22, 35, 0.9) !important;
        border: 1px solid rgba(0, 240, 255, 0.2) !important;
        border-radius: 16px !important;
        padding: 15px !important;
        margin-bottom: 10px !important;
    }
    [data-testid="stChatMessage"] .stMarkdown p { color: #FFF !important; font-size: 16px !important; }
    [data-testid="stChatInput"] {
        background-color: rgba(10, 14, 23, 0.95) !important;
        border-top: 1px solid rgba(0, 240, 255, 0.2) !important;
    }
    
    /* صناديق البيانات (Cards) */
    div[data-testid="stExpander"] {
        background: rgba(16, 22, 35, 0.8) !important;
        border: 1px solid rgba(0, 240, 255, 0.2) !important;
        border-radius: 16px !important;
    }
    
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# =====================================================================
# 2. التشفير وإعدادات Firebase الآمنة (حل مشكلة Streamlit Cloud Secrets)
# =====================================================================
fallback_key = base64.urlsafe_b64encode(hashlib.sha256(b"Elderiny_Secret_Key_2026").digest())
FERNET_KEY = os.getenv("FERNET_KEY", fallback_key.decode())
cipher = Fernet(FERNET_KEY.encode())

def encrypt_val(value: str) -> str:
    if not value: return ""
    return cipher.encrypt(value.encode()).decode()

def decrypt_val(value: str) -> str:
    if not value: return ""
    try: return cipher.decrypt(value.encode()).decode()
    except: return value

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password, hashed_password):
    try:
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password)
    except ValueError:
        return False

@st.cache_resource(show_spinner=False)
def init_firebase():
    if not firebase_admin._apps:
        try:
            # قراءة المفتاح من Streamlit Secrets بصيغة JSON مباشرة
            if "FIREBASE_KEY" in st.secrets:
                firebase_config = json.loads(st.secrets["FIREBASE_KEY"])
                if "project_id" in firebase_config:
                    os.environ["GOOGLE_CLOUD_PROJECT"] = firebase_config["project_id"]
                cred = credentials.Certificate(firebase_config)
                firebase_admin.initialize_app(cred)
            elif "firebase" in st.secrets:
                fb_secrets = dict(st.secrets["firebase"])
                if "private_key" in fb_secrets:
                    fb_secrets["private_key"] = fb_secrets["private_key"].replace('\\n', '\n')
                if "project_id" in fb_secrets:
                    os.environ["GOOGLE_CLOUD_PROJECT"] = fb_secrets["project_id"]
                cred = credentials.Certificate(fb_secrets)
                firebase_admin.initialize_app(cred)
            elif os.path.exists("firebase-key.json"):
                with open("firebase-key.json", "r", encoding="utf-8") as f:
                    fb_keys = json.load(f)
                if "project_id" in fb_keys:
                    os.environ["GOOGLE_CLOUD_PROJECT"] = fb_keys["project_id"]
                cred = credentials.Certificate(fb_keys)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        except Exception as e:
            st.error(f"خطأ في الاتصال بـ Firebase: {e}")
            return None
    return firestore.client()

db = init_firebase()

# =====================================================================
# 3. الذكاء الاصطناعي (LangGraph & Pinecone)
# =====================================================================
class AgentState(MessagesState):
    pass

def build_graph(llm, tenant_data):
    workflow = StateGraph(AgentState)
    def process_msg(state: AgentState):
        sys_prompt = SystemMessage(content=tenant_data.get("cs_prompt", "أنت أسطى مصري خبير في المعدات."))
        messages = [sys_prompt] + state["messages"]
        response = llm.invoke(messages)
        return {"messages": [response]}
    
    workflow.add_node("agent", process_msg)
    workflow.add_edge(START, "agent")
    workflow.add_edge("agent", END)
    return workflow.compile()

def get_llm_client(tenant_data):
    key = decrypt_val(tenant_data.get("openai_api_key", ""))
    if not key: return None
    try:
        return ChatOpenAI(model_name=tenant_data.get("llm_model", "gpt-4o"), openai_api_key=key, temperature=0.2)
    except Exception as e:
        st.error(f"خطأ في الاتصال بـ OpenAI: {e}")
        return None

def fetch_rag(tenant_data, query):
    openai_key = decrypt_val(tenant_data.get("openai_api_key", ""))
    pinecone_key = decrypt_val(tenant_data.get("pinecone_api_key", ""))
    index_name = tenant_data.get("pinecone_index", "")
    
    if not openai_key or not pinecone_key or not index_name:
        return ""
        
    try:
        embeddings = OpenAIEmbeddings(openai_api_key=openai_key)
        pc = PineconeClient(api_key=pinecone_key)
        index = pc.Index(index_name)
        vector_store = PineconeVectorStore(index=index, embedding=embeddings, namespace=f"tenant_{tenant_data['id']}")
        
        docs = vector_store.similarity_search(query, k=3)
        return "\n---\n".join([doc.page_content for doc in docs])
    except Exception as e:
        return f"تعذر جلب معلومات الكتالوج: {e}"

# =====================================================================
# 4. دوال واجهة المستخدم (Views - Streamlit Native)
# =====================================================================
def login_view():
    st.markdown("<h1 style='text-align: center; color: #00F0FF;'>تسجيل الدخول للورشة</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>نظام إدارة أعطال المصنع بالذكاء الاصطناعي</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("اسم المستخدم أو رقم الموبايل (للعمال)")
            password = st.text_input("الرقم السري", type="password")
            
            if st.form_submit_button("دخول مؤمن 🚀", use_container_width=True):
                if db is None:
                    st.error("قاعدة البيانات غير متصلة. تأكد من الإعدادات.")
                    return
                users = list(db.collection("users").where("username", "==", username).limit(1).stream())
                if users:
                    u_data = users[0].to_dict()
                    if verify_password(password, u_data.get("hashed_password", "")):
                        st.session_state.user = {"id": users[0].id, **u_data}
                        t_ref = db.collection("tenants").document(u_data["tenant_id"]).get()
                        st.session_state.tenant = {"id": t_ref.id, **t_ref.to_dict()}
                        st.rerun()
                st.error("بيانات الدخول غير صحيحة.")

def register_view():
    st.markdown("<h1 style='text-align: center; color: #39FF14;'>تسجيل ورشة/شركة جديدة</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("register_form"):
            company_name = st.text_input("اسم الورشة / الشركة")
            admin_username = st.text_input("اسم المستخدم (للدخول)")
            admin_password = st.text_input("كلمة المرور", type="password")
            
            if st.form_submit_button("تسجيل وإنشاء مساحة العمل 🚀", use_container_width=True):
                if len(company_name) < 3 or len(admin_username) < 3 or len(admin_password) < 6:
                    st.error("يرجى إدخال بيانات صحيحة (الاسم 3 أحرف على الأقل، والباسورد 6).")
                else:
                    existing_t = list(db.collection("tenants").where("name", "==", company_name).limit(1).stream())
                    existing_u = list(db.collection("users").where("username", "==", admin_username).limit(1).stream())
                    
                    if existing_t:
                        st.error("اسم الشركة مسجل مسبقاً.")
                    elif existing_u:
                        st.error("اسم المستخدم محجوز لمدير آخر.")
                    else:
                        t_ref = db.collection("tenants").document()
                        t_ref.set({
                            "name": company_name,
                            "llm_model": "gpt-4o",
                            "cs_prompt": "أنت 'الأسطى الآلي'، كبير المهندسين في شركة تصنيع معدات هندسية. تتحدث بلهجة مصرية عامية (صنايعي صميم). العمال بسطاء، لذا أعطهم حلول هندسية مظبوطة جداً وبلغة بلدية سهلة. امش معاهم خطوة بخطوة."
                        })
                        db.collection("users").add({
                            "username": admin_username,
                            "hashed_password": get_password_hash(admin_password),
                            "role": "admin",
                            "tenant_id": t_ref.id
                        })
                        st.success("تم الإنشاء بنجاح! يمكنك الآن العودة وتسجيل الدخول.")

def chat_view():
    st.subheader("الأسطى الآلي 👷‍♂️")
    user_id = st.session_state.user['id']
    tenant_id = st.session_state.tenant['id']
    
    # الحل الجراحي للـ Index: جلب البيانات بدون order_by، ثم ترتيبها In-Memory
    raw_sessions = list(db.collection('chat_sessions').where('user_id', '==', user_id).stream())
    raw_sessions.sort(key=lambda s: s.to_dict().get('updated_at', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    
    with st.sidebar:
        st.write("📋 **محادثاتي السابقة:**")
        if st.button("➕ محادثة جديدة", use_container_width=True):
            st.session_state.active_chat_id = None
            st.session_state.messages = []
            st.rerun()
            
        for s_doc in raw_sessions:
            s_data = s_doc.to_dict()
            # الحل الجراحي لمعالجة KeyError (session_uuid)
            s_id = s_data.get('session_uuid', s_doc.id) 
            title = s_data.get('title', 'محادثة')
            
            btn_type = "primary" if st.session_state.get('active_chat_id') == s_id else "secondary"
            if st.button(f"💬 {title[:20]}", key=f"sel_{s_id}", type=btn_type, use_container_width=True):
                st.session_state.active_chat_id = s_id
                
                # جلب رسائل المحادثة وترتيبها In-Memory لتجنب مشكلة الـ Composite Index
                msgs_raw = list(db.collection('chat_messages').where('session_uuid', '==', s_id).stream())
                msgs_raw.sort(key=lambda m: m.to_dict().get('timestamp', datetime.min.replace(tzinfo=timezone.utc)))
                
                st.session_state.messages = [{"role": m.to_dict().get('role'), "content": m.to_dict().get('content')} for m in msgs_raw]
                st.rerun()

    st.info("🎤 **للعمال:** لتسجيل مشكلتك بالصوت، اضغط على علامة (المايكروفون) في كيبورد الموبايل الخاص بك.")
    
    if "messages" not in st.session_state or not st.session_state.messages:
        st.session_state.messages = [{"role": "assistant", "content": "يا هلا بيك يا بطل في الورشة، معاك الأسطى الآلي. المكنة فيها إيه؟"}]
        
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="🧑‍🔧" if msg["role"] == "user" else "👷"):
            st.markdown(msg["content"])
            
    if prompt := st.chat_input("سجل عطل المكنة هنا..."):
        if not st.session_state.get('active_chat_id'):
            new_session = db.collection('chat_sessions').add({
                'user_id': user_id,
                'tenant_id': tenant_id,
                'title': prompt[:30],
                'updated_at': firestore.SERVER_TIMESTAMP
            })
            st.session_state.active_chat_id = new_session[1].id
            new_session[1].update({'session_uuid': new_session[1].id})
            
            db.collection('chat_messages').add({
                'session_uuid': st.session_state.active_chat_id,
                'role': 'assistant',
                'content': st.session_state.messages[0]["content"],
                'timestamp': firestore.SERVER_TIMESTAMP
            })

        st.session_state.messages.append({"role": "user", "content": prompt})
        db.collection('chat_messages').add({
            'session_uuid': st.session_state.active_chat_id,
            'role': 'user',
            'content': prompt,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        db.collection('chat_sessions').document(st.session_state.active_chat_id).update({'updated_at': firestore.SERVER_TIMESTAMP})

        with st.chat_message("user", avatar="🧑‍🔧"):
            st.markdown(prompt)
            
        with st.chat_message("assistant", avatar="👷"):
            with st.spinner("الأسطى بيفكر في الحل..."):
                rag_context = fetch_rag(st.session_state.tenant, prompt)
                enhanced_msg = prompt
                if rag_context:
                    enhanced_msg = f"سؤال العامل: {prompt}\n\n[معلومات فنية من الكتالوجات المرفوعة]:\n{rag_context}\n\nرد كأنك أسطى مصري بناءً على هذه المعلومات فقط."
                
                llm = get_llm_client(st.session_state.tenant)
                if llm:
                    graph = build_graph(llm, st.session_state.tenant)
                    res = graph.invoke({"messages": [HumanMessage(content=enhanced_msg)]})
                    ai_reply = res["messages"][-1].content
                    
                    st.markdown(ai_reply)
                    st.session_state.messages.append({"role": "assistant", "content": ai_reply})
                    
                    db.collection('chat_messages').add({
                        'session_uuid': st.session_state.active_chat_id,
                        'role': 'assistant',
                        'content': ai_reply,
                        'timestamp': firestore.SERVER_TIMESTAMP
                    })
                    
                    st.session_state.last_audio = ai_reply
                else:
                    st.error("مفاتيح الذكاء الاصطناعي غير متوفرة. الرجاء إبلاغ المدير.")

    if st.session_state.get("last_audio"):
        clean_text = st.session_state.last_audio.replace('\n', ' ').replace("'", "").replace('"', '')
        clean_text = re.sub(r'[*_#]', '', clean_text) 
        
        # الحل الجراحي: استبدال components.html بطريقة حقن آمنة لا تولد iframe يتسبب في localhost refused
        audio_js = f"""
        <script>
            setTimeout(function() {{
                if ('speechSynthesis' in window) {{
                    window.speechSynthesis.cancel();
                    const text = "{clean_text}";
                    const utterance = new SpeechSynthesisUtterance(text);
                    utterance.lang = 'ar-EG'; 
                    utterance.pitch = 0.8; 
                    utterance.rate = 1.0;
                    window.speechSynthesis.speak(utterance);
                }}
            }}, 500);
        </script>
        """
        st.components.v1.html(audio_js, width=0, height=0, scrolling=False)
        st.session_state.last_audio = None

def admin_dashboard():
    st.subheader("لوحة تحكم المدير 📊")
    tenant_id = st.session_state.tenant['id']
    
    # In-Memory Sort للأعطال
    alerts_docs = list(db.collection('alerts').where('tenant_id', '==', tenant_id).stream())
    alerts_docs.sort(key=lambda a: a.to_dict().get('created_at', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("عدد العمال المسجلين", len(list(db.collection('users').where('tenant_id', '==', tenant_id).where('role', '==', 'worker').stream())))
    with col2:
        st.metric("التنبيهات والأعطال", len(alerts_docs))
        
    if alerts_docs:
        for a_doc in alerts_docs:
            a = a_doc.to_dict()
            st.warning(f"**عطل:** {a.get('details', '')}")
    else:
        st.success("لا توجد أعطال حرجة مسجلة حالياً.")

def admin_rag():
    st.subheader("إدارة البيانات وتدريب الكتالوجات (RAG) 📚")
    tenant_id = st.session_state.tenant["id"]
    t_data = st.session_state.tenant
    
    if not t_data.get("openai_api_key") or not t_data.get("pinecone_api_key"):
        st.warning("⚠️ يجب إضافة مفتاح OpenAI ومفتاح Pinecone في نافذة الإعدادات أولاً لتتمكن من التدريب.")
        return

    uploaded_file = st.file_uploader("اختر ملف (PDF, TXT, CSV)", type=["pdf", "txt", "csv"])
    if uploaded_file and st.button("رفع وتدريب الأسطى", type="primary"):
        with st.spinner("جاري قراءة الملف وتخزينه في Pinecone..."):
            try:
                db.collection("uploaded_files").add({
                    "filename": uploaded_file.name,
                    "upload_date": firestore.SERVER_TIMESTAMP,
                    "tenant_id": tenant_id
                })
                
                text = ""
                if uploaded_file.name.endswith(".pdf"):
                    pdf_reader = PdfReader(io.BytesIO(uploaded_file.getvalue()))
                    for page in pdf_reader.pages:
                        if page.extract_text(): text += page.extract_text() + "\n"
                else:
                    text = uploaded_file.getvalue().decode('utf-8')
                    
                embeddings = OpenAIEmbeddings(openai_api_key=decrypt_val(t_data["openai_api_key"]))
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
                chunks = text_splitter.split_text(text)
                
                pc = PineconeClient(api_key=decrypt_val(t_data["pinecone_api_key"]))
                index = pc.Index(t_data["pinecone_index"])
                vector_store = PineconeVectorStore(index=index, embedding=embeddings, namespace=f"tenant_{tenant_id}")
                vector_store.add_texts(chunks)
                
                st.success("✅ تم التدريب بنجاح! الأسطى الآن يعلم محتوى هذا الملف.")
            except Exception as e:
                st.error(f"حدث خطأ أثناء التدريب: {e}")

    st.divider()
    st.write("📁 **الملفات المرفوعة للورشة:**")
    files_docs = list(db.collection("uploaded_files").where("tenant_id", "==", tenant_id).stream())
    
    if files_docs:
        df = pd.DataFrame([{"ID": d.id, "اسم الملف": d.to_dict().get("filename")} for d in files_docs])
        st.dataframe(df, hide_index=True)
        
        del_id = st.text_input("أدخل الـ ID لحذف ملف من السجل:")
        if st.button("حذف الملف 🗑️"):
            db.collection("uploaded_files").document(del_id).delete()
            st.success("تم حذف الملف من السجل بنجاح.")
            st.rerun()
    else:
        st.info("لا توجد ملفات مرفوعة حالياً.")

def admin_users():
    st.subheader("إدارة العمال والمستخدمين 👥")
    t_data = st.session_state.tenant
    
    with st.form("add_worker"):
        st.write("سيتم إنشاء حساب لكل عامل، ويكون **اسم المستخدم وكلمة المرور هما رقم الموبايل** الخاص به.")
        w_name = st.text_input("اسم العامل (مثال: حسن الخراط)")
        w_phone = st.text_input("رقم الموبايل")
        if st.form_submit_button("إضافة عامل"):
            if w_name and w_phone:
                db.collection("users").add({
                    "username": w_phone,
                    "hashed_password": get_password_hash(w_phone),
                    "role": "worker",
                    "tenant_id": t_data["id"]
                })
                st.success(f"تم إضافة {w_name}. يمكنه الآن الدخول برقمه.")
                
    st.divider()
    users_docs = list(db.collection("users").where("tenant_id", "==", t_data["id"]).stream())
    if users_docs:
        udf = pd.DataFrame([{"ID": d.id, "اسم الدخول": d.to_dict().get("username"), "الصلاحية": "عامل" if d.to_dict().get("role")=="worker" else "مدير"} for d in users_docs])
        st.dataframe(udf, hide_index=True)
        
        del_u_id = st.text_input("أدخل الـ ID لحذف مستخدم:")
        if st.button("حذف المستخدم 🗑️", type="secondary"):
            db.collection("users").document(del_u_id).delete()
            st.success("تم حذف المستخدم.")
            st.rerun()

def admin_settings():
    st.subheader("إعدادات الربط والذكاء الاصطناعي ⚙️")
    t_data = st.session_state.tenant
    
    st.write("قم بوضع مفاتيح API الخاصة بك هنا لربط الذكاء الاصطناعي وقاعدة البيانات.")
    new_openai = st.text_input("OpenAI API Key", value=decrypt_val(t_data.get("openai_api_key")), type="password")
    new_pinecone = st.text_input("Pinecone API Key", value=decrypt_val(t_data.get("pinecone_api_key")), type="password")
    new_index = st.text_input("Pinecone Index Name", value=t_data.get("pinecone_index", ""))
    new_prompt = st.text_area("تعليمات الأسطى الآلي (Prompt)", value=t_data.get("cs_prompt", ""), height=150)
    
    if st.button("حفظ الإعدادات", type="primary"):
        db.collection("tenants").document(t_data["id"]).update({
            "openai_api_key": encrypt_val(new_openai),
            "pinecone_api_key": encrypt_val(new_pinecone),
            "pinecone_index": new_index,
            "cs_prompt": new_prompt
        })
        st.success("تم الحفظ بنجاح!")
        t_ref = db.collection("tenants").document(t_data["id"]).get()
        st.session_state.tenant = {"id": t_ref.id, **t_ref.to_dict()}

# =====================================================================
# 5. الموجه الرئيسي (Router)
# =====================================================================
def main():
    if "user" not in st.session_state:
        st.session_state.user = None
    if "view" not in st.session_state:
        st.session_state.view = "login"

    if st.session_state.user is None:
        if st.session_state.view == "login":
            login_view()
            st.markdown("<br><hr>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1,2,1])
            with col2:
                if st.button("لا تملك حساب للورشة؟ تسجيل شركة جديدة", use_container_width=True):
                    st.session_state.view = "register"
                    st.rerun()
        else:
            register_view()
            st.markdown("<br><hr>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1,2,1])
            with col2:
                if st.button("العودة لتسجيل الدخول", use_container_width=True):
                    st.session_state.view = "login"
                    st.rerun()
    else:
        st.sidebar.markdown(f"<h3 style='color:#00F0FF;'>نظام الدريني</h3>", unsafe_allow_html=True)
        st.sidebar.write(f"مرحباً: **{st.session_state.user['username']}**")
        st.sidebar.divider()
        
        if st.session_state.user["role"] == "admin":
            pages = ["المحادثة (Kiosk)", "لوحة التحكم", "الكتالوجات (RAG)", "العمال", "الإعدادات"]
        else:
            pages = ["المحادثة (Kiosk)"]
            
        selected = st.sidebar.radio("القائمة الرئيسية:", pages)
        st.session_state.current_view = selected
        
        st.sidebar.divider()
        if st.sidebar.button("تسجيل الخروج 🚪", use_container_width=True):
            st.session_state.user = None
            st.session_state.active_chat_id = None
            st.rerun()
            
        view = st.session_state.current_view
        if view == "المحادثة (Kiosk)": chat_view()
        elif view == "لوحة التحكم": admin_dashboard()
        elif view == "العمال": admin_users()
        elif view == "الكتالوجات (RAG)": admin_rag()
        elif view == "الإعدادات": admin_settings()

if __name__ == "__main__":
    main()
