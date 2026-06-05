import os
import io
import json
import base64
import hashlib
from datetime import datetime
import re
import logging

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
from openai import OpenAI
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

# =====================================================================
# إعدادات واجهة Streamlit وحقن تصميم النيون (CSS Injection)
# =====================================================================
st.set_page_config(page_title="نظام الدريني للمصانع", page_icon="⚙️", layout="wide")

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

    h1, h2, h3, h4, h5, h6, p, label, span {
        color: #FFF !important;
    }

    /* إخفاء القوائم الافتراضية لستريمليت */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}

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
    [data-testid="stChatMessage"] .stMarkdown p {
        color: #FFF !important;
        font-size: 16px !important;
    }
    
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
</style>
""", unsafe_allow_html=True)

# =====================================================================
# التشفير والاتصال بقاعدة بيانات Firebase (جاهز للسحابة)
# =====================================================================
# مفتاح تشفير ثابت لضمان عدم ضياع كلمات المرور عند إعادة تشغيل السيرفر السحابي
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
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            if "firebase" in st.secrets:
                cred = credentials.Certificate(dict(st.secrets["firebase"]))
                firebase_admin.initialize_app(cred)
            elif os.path.exists("firebase-key.json"):
                cred = credentials.Certificate("firebase-key.json")
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        except Exception as e:
            st.error(f"خطأ في الاتصال بـ Firebase: {e}")
    return firestore.client()

db = init_firebase()

# =====================================================================
# الذكاء الاصطناعي (LangGraph & Pinecone)
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
# دوال واجهة المستخدم (Views)
# =====================================================================

def init_system():
    # التأكد من وجود شركة ومدير افتراضي في قاعدة البيانات
    tenants = list(db.collection("tenants").limit(1).stream())
    if not tenants:
        t_ref = db.collection("tenants").document()
        t_ref.set({
            "name": "الدريني للآلات والمعدات",
            "llm_model": "gpt-4o",
            "cs_prompt": "أنت 'الأسطى الآلي'، كبير المهندسين في شركة تصنيع معدات هندسية. تتحدث بلهجة مصرية عامية (صنايعي صميم). العمال بسطاء، لذا أعطهم حلول هندسية مظبوطة جداً وبلغة بلدية سهلة. امش معاهم خطوة بخطوة وقولهم (يا بطل، يا هندسة، ركز معايا)."
        })
        db.collection("users").add({
            "username": "admin",
            "hashed_password": get_password_hash("12345678"),
            "role": "admin",
            "tenant_id": t_ref.id
        })

def login_view():
    st.markdown("<h1 style='text-align: center; color: #00F0FF;'>تسجيل الدخول للورشة</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>نظام إدارة أعطال المصنع بالذكاء الاصطناعي</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.container():
            username = st.text_input("اسم المستخدم أو رقم الموبايل (للعمال)")
            password = st.text_input("الرقم السري", type="password")
            
            if st.button("دخول مؤمن 🚀", use_container_width=True):
                users = list(db.collection("users").where("username", "==", username).stream())
                if users:
                    u_data = users[0].to_dict()
                    if verify_password(password, u_data["hashed_password"]):
                        st.session_state.user = {"id": users[0].id, **u_data}
                        t_ref = db.collection("tenants").document(u_data["tenant_id"]).get()
                        st.session_state.tenant = {"id": t_ref.id, **t_ref.to_dict()}
                        st.rerun()
                st.error("بيانات الدخول غير صحيحة.")

def chat_view():
    st.subheader("الأسطى الآلي 👷‍♂️")
    st.info("🎤 **للعمال:** لتسجيل مشكلتك بالصوت، اضغط على علامة (المايكروفون) الموجودة في لوحة مفاتيح الموبايل الخاصة بك.")
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "يا هلا بيك يا بطل في الورشة، معاك الأسطى الآلي. المكنة فيها إيه؟ سجل صوتك أو اكتبلي."}]
        
    # عرض المحادثة
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="🧑‍🔧" if msg["role"] == "user" else "👷"):
            st.markdown(msg["content"])
            
    if prompt := st.chat_input("سجل عطل المكنة هنا..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑‍🔧"):
            st.markdown(prompt)
            
        with st.chat_message("assistant", avatar="👷"):
            with st.spinner("الأسطى بيفكر في الحل..."):
                rag_context = fetch_rag(st.session_state.tenant, prompt)
                enhanced_msg = prompt
                if rag_context:
                    enhanced_msg = f"سؤال العامل: {prompt}\n\n[معلومات فنية من كتالوجات الماكينات للمساعدة]:\n{rag_context}\n\nرد كأنك أسطى مصري بناءً على هذه المعلومات لمساعدة العامل."
                
                llm = get_llm_client(st.session_state.tenant)
                if llm:
                    graph = build_graph(llm, st.session_state.tenant)
                    res = graph.invoke({"messages": [HumanMessage(content=enhanced_msg)]})
                    ai_reply = res["messages"][-1].content
                    
                    st.markdown(ai_reply)
                    st.session_state.messages.append({"role": "assistant", "content": ai_reply})
                    st.session_state.last_audio = ai_reply
                else:
                    st.error("مفاتيح الذكاء الاصطناعي غير متوفرة. الرجاء إبلاغ المدير لإضافتها في الإعدادات.")

    # تشغيل النطق الصوتي للرد الأخير (Speech Synthesis)
    if st.session_state.get("last_audio"):
        clean_text = st.session_state.last_audio.replace('\n', ' ').replace("'", "").replace('"', '')
        clean_text = re.sub(r'[*_#]', '', clean_text) # تنظيف الماركداون
        
        js_code = f"""
        <script>
            if ('speechSynthesis' in window) {{
                window.speechSynthesis.cancel();
                const text = "{clean_text}";
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = 'ar-EG'; 
                utterance.pitch = 0.8; // صوت خشن قليلاً يناسب الأسطى
                utterance.rate = 1.0;
                window.speechSynthesis.speak(utterance);
            }}
        </script>
        """
        components.html(js_code, height=0, width=0)
        st.session_state.last_audio = None

def data_management_view():
    st.subheader("إدارة البيانات وتدريب الكتالوجات (RAG) 📚")
    st.write("ارفع كتالوجات الماكينات (CNC، مخارط، ليزر) أو ملفات صيانة الضواغط. الأسطى الآلي سيقرأها ويفهمها فوراً.")
    
    tenant_id = st.session_state.tenant["id"]
    t_data = st.session_state.tenant
    
    if not t_data.get("openai_api_key") or not t_data.get("pinecone_api_key"):
        st.warning("⚠️ يجب إضافة مفتاح OpenAI ومفتاح Pinecone في نافذة الإعدادات أولاً لتتمكن من التدريب.")
        return

    uploaded_file = st.file_uploader("اختر ملف (PDF, TXT, CSV)", type=["pdf", "txt", "csv"])
    if uploaded_file and st.button("رفع وتدريب الأسطى", type="primary"):
        with st.spinner("جاري قراءة الملف وتخزينه في Pinecone..."):
            try:
                # 1. حفظ في الفايربيز كمرجع
                db.collection("uploaded_files").add({
                    "filename": uploaded_file.name,
                    "upload_date": datetime.utcnow(),
                    "tenant_id": tenant_id
                })
                
                # 2. معالجة النص
                text = ""
                if uploaded_file.name.endswith(".pdf"):
                    pdf_reader = PdfReader(io.BytesIO(uploaded_file.getvalue()))
                    for page in pdf_reader.pages:
                        if page.extract_text(): text += page.extract_text() + "\n"
                else:
                    text = uploaded_file.getvalue().decode('utf-8')
                    
                # 3. التدريب
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
        df = pd.DataFrame([{"ID": d.id, "اسم الملف": d.to_dict().get("filename"), "التاريخ": d.to_dict().get("upload_date").strftime("%Y-%m-%d")} for d in files_docs])
        st.dataframe(df, hide_index=True)
        
        col1, col2 = st.columns(2)
        del_id = col1.text_input("أدخل الـ ID لحذف ملف من السجل:")
        if col2.button("حذف الملف 🗑️"):
            db.collection("uploaded_files").document(del_id).delete()
            st.success("تم حذف الملف من السجل بنجاح.")
            st.rerun()
    else:
        st.info("لا توجد ملفات مرفوعة حالياً.")

def settings_view():
    st.subheader("إعدادات الربط وإدارة العمال ⚙️")
    t_data = st.session_state.tenant
    
    tab1, tab2, tab3 = st.tabs(["إدارة العمال", "مفاتيح الذكاء الاصطناعي", "شخصية الأسطى"])
    
    with tab1:
        st.write("أضف عمال الورشة هنا. سيتم إنشاء حساب لكل عامل، ويكون **اسم المستخدم وكلمة المرور هما رقم الموبايل** الخاص به.")
        with st.form("add_worker"):
            w_name = st.text_input("اسم العامل (مثال: حسن الخراط)")
            w_phone = st.text_input("رقم الموبايل")
            if st.form_submit_button("إضافة عامل"):
                if w_name and w_phone:
                    # إضافة لجدول المستخدمين
                    db.collection("users").add({
                        "username": w_phone,
                        "hashed_password": get_password_hash(w_phone),
                        "role": "worker",
                        "tenant_id": t_data["id"]
                    })
                    st.success(f"تم إضافة {w_name}. يمكنه الآن الدخول برقمه.")
                    
        st.divider()
        st.write("👥 **العمال والمديرين الحاليين:**")
        users_docs = list(db.collection("users").where("tenant_id", "==", t_data["id"]).stream())
        udf = pd.DataFrame([{"اسم الدخول": d.to_dict().get("username"), "الصلاحية": "عامل" if d.to_dict().get("role")=="worker" else "مدير"} for d in users_docs])
        st.dataframe(udf, hide_index=True)

    with tab2:
        st.write("قم بوضع مفاتيح API الخاصة بك هنا لربط الذكاء الاصطناعي وقاعدة البيانات.")
        new_openai = st.text_input("OpenAI API Key", value=decrypt_val(t_data.get("openai_api_key")), type="password")
        new_pinecone = st.text_input("Pinecone API Key", value=decrypt_val(t_data.get("pinecone_api_key")), type="password")
        new_index = st.text_input("Pinecone Index Name", value=t_data.get("pinecone_index", ""))
        
        if st.button("حفظ مفاتيح الربط"):
            db.collection("tenants").document(t_data["id"]).update({
                "openai_api_key": encrypt_val(new_openai),
                "pinecone_api_key": encrypt_val(new_pinecone),
                "pinecone_index": new_index
            })
            st.success("تم الحفظ بنجاح!")
            # تحديث الـ Session
            t_ref = db.collection("tenants").document(t_data["id"]).get()
            st.session_state.tenant = {"id": t_ref.id, **t_ref.to_dict()}

    with tab3:
        st.write("هنا يمكنك تعديل التعليمات التي تحدد شخصية الأسطى وطريقة رده على العمال.")
        new_prompt = st.text_area("تعليمات الأسطى الآلي (Prompt)", value=t_data.get("cs_prompt", ""), height=200)
        if st.button("حفظ الشخصية"):
            db.collection("tenants").document(t_data["id"]).update({"cs_prompt": new_prompt})
            st.success("تم التحديث بنجاح!")
            t_ref = db.collection("tenants").document(t_data["id"]).get()
            st.session_state.tenant = {"id": t_ref.id, **t_ref.to_dict()}

# =====================================================================
# الموجه الرئيسي (Router)
# =====================================================================
def main_router():
    init_system()
    
    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user is None:
        login_view()
    else:
        st.sidebar.markdown(f"<h3 style='color:#00F0FF;'>نظام الدريني</h3>", unsafe_allow_html=True)
        st.sidebar.write(f"مرحباً: **{st.session_state.user['username']}**")
        st.sidebar.divider()
        
        # توجيه الصفحات حسب الصلاحية
        if st.session_state.user["role"] == "admin":
            pages = ["الأسطى الآلي (شات)", "إدارة البيانات والملفات", "الإعدادات"]
        else:
            pages = ["الأسطى الآلي (شات)"]
            
        selected = st.sidebar.radio("القائمة الرئيسية:", pages)
        
        st.sidebar.divider()
        if st.sidebar.button("تسجيل الخروج 🚪", use_container_width=True):
            st.session_state.user = None
            st.rerun()
            
        # عرض الصفحة المحددة
        if selected == "الأسطى الآلي (شات)":
            chat_view()
        elif selected == "إدارة البيانات والملفات":
            data_management_view()
        elif selected == "الإعدادات":
            settings_view()

if __name__ == "__main__":
    main_router()
