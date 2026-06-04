# -*- coding: utf-8 -*-
import os
import io
import json
import uuid
import time
import base64
import hashlib
import tempfile
from datetime import datetime

import streamlit as st

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None

try:
    from pinecone import Pinecone, ServerlessSpec
except Exception:
    Pinecone = None
    ServerlessSpec = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from audio_recorder_streamlit import audio_recorder
except Exception:
    audio_recorder = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

try:
    import requests
except Exception:
    requests = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import docx
except Exception:
    docx = None

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_openai import OpenAIEmbeddings, ChatOpenAI
    from langchain_pinecone import PineconeVectorStore
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.documents import Document
except Exception:
    RecursiveCharacterTextSplitter = None
    OpenAIEmbeddings = None
    ChatOpenAI = None
    PineconeVectorStore = None
    ChatPromptTemplate = None
    Document = None


APP_NAME = "الأسطى كبير"
DEFAULT_INDEX = "industrial-knowledge-rag"
DEFAULT_NAMESPACE = "factory-knowledge"
USERS_COLLECTION = "users"
FILES_COLLECTION = "rag_files"

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def css():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap');

:root {
    --bg: #030611;
    --panel: rgba(255,255,255,.075);
    --panel2: rgba(255,255,255,.115);
    --line: rgba(255,255,255,.17);
    --cyan: #18f7ff;
    --purple: #a855f7;
    --pink: #ff3fd4;
    --green: #34f5a4;
    --danger: #ff416c;
    --text: #f4fbff;
    --muted: #a9b8c8;
}

html, body, .stApp {
    direction: rtl;
    font-family: 'Cairo', sans-serif !important;
    color: var(--text);
    background:
        radial-gradient(circle at 15% 10%, rgba(24,247,255,.18), transparent 34%),
        radial-gradient(circle at 86% 14%, rgba(168,85,247,.22), transparent 32%),
        radial-gradient(circle at 48% 92%, rgba(255,63,212,.12), transparent 28%),
        linear-gradient(135deg, #02040c, #080d1e 48%, #050713);
}

[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { direction: ltr; }
[data-testid="stSidebar"] {
    direction: rtl;
    background: rgba(2,5,14,.82);
    backdrop-filter: blur(22px);
    border-left: 1px solid rgba(24,247,255,.24);
    border-right: 0;
    box-shadow: -18px 0 55px rgba(0,0,0,.34);
}
[data-testid="stSidebar"] * {
    font-family: 'Cairo', sans-serif !important;
}

.main .block-container {
    padding: 1.2rem 1.4rem 1.4rem;
    max-width: 100%;
}

.app-shell {
    min-height: calc(100vh - 36px);
}

.screen-title {
    font-size: clamp(2rem, 4vw, 4.1rem);
    line-height: 1.05;
    font-weight: 900;
    letter-spacing: 0;
    margin: .15rem 0 .35rem;
    color: #fff;
    text-shadow:
        0 0 12px rgba(24,247,255,.62),
        0 0 26px rgba(168,85,247,.48),
        0 0 46px rgba(255,63,212,.22);
}

.screen-subtitle {
    color: var(--muted);
    font-size: clamp(1rem, 1.55vw, 1.25rem);
    margin-bottom: 1rem;
}

.glass {
    background: linear-gradient(145deg, rgba(255,255,255,.105), rgba(255,255,255,.055));
    border: 1px solid var(--line);
    border-radius: 8px;
    box-shadow:
        0 20px 70px rgba(0,0,0,.38),
        inset 0 1px 0 rgba(255,255,255,.14),
        0 0 0 1px rgba(24,247,255,.04);
    backdrop-filter: blur(18px);
    padding: 1rem;
}

.hero-login {
    min-height: 72vh;
    display: grid;
    place-items: center;
}

.brand {
    padding: .8rem 0 1rem;
    border-bottom: 1px solid rgba(255,255,255,.12);
    margin-bottom: 1rem;
}
.brand-name {
    font-size: 1.75rem;
    font-weight: 900;
    color: #fff;
    text-shadow: 0 0 18px rgba(24,247,255,.55);
}
.brand-role {
    color: var(--muted);
    font-size: .95rem;
}

.nav-button button {
    width: 100%;
    min-height: 58px;
    border-radius: 8px !important;
    text-align: right !important;
    justify-content: flex-start !important;
    font-size: 1.08rem !important;
    font-weight: 800 !important;
    border: 1px solid rgba(255,255,255,.13) !important;
    background: rgba(255,255,255,.055) !important;
    color: var(--text) !important;
    margin-bottom: .55rem;
}
.nav-button button:hover {
    border-color: rgba(24,247,255,.62) !important;
    box-shadow: 0 0 24px rgba(24,247,255,.18);
}
.active-nav button {
    background: linear-gradient(135deg, rgba(24,247,255,.22), rgba(168,85,247,.24)) !important;
    border-color: rgba(24,247,255,.75) !important;
    box-shadow: 0 0 30px rgba(24,247,255,.22), inset 0 1px 0 rgba(255,255,255,.18);
}

.stButton > button, .stDownloadButton > button {
    min-height: 48px;
    border-radius: 8px !important;
    border: 1px solid rgba(24,247,255,.42) !important;
    background: linear-gradient(135deg, rgba(24,247,255,.18), rgba(168,85,247,.20)) !important;
    color: var(--text) !important;
    font-family: 'Cairo', sans-serif !important;
    font-weight: 900 !important;
    box-shadow: 0 0 20px rgba(24,247,255,.13);
}
.stButton > button:hover {
    border-color: rgba(24,247,255,.95) !important;
    box-shadow: 0 0 32px rgba(24,247,255,.27);
}

input, textarea {
    direction: rtl;
    text-align: right;
    font-family: 'Cairo', sans-serif !important;
}
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background: rgba(255,255,255,.075) !important;
    color: var(--text) !important;
    border: 1px solid rgba(255,255,255,.18) !important;
    border-radius: 8px !important;
}

.full-chat {
    min-height: calc(100vh - 190px);
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: 1rem;
}

.chat-stage {
    min-height: 48vh;
    max-height: 58vh;
    overflow-y: auto;
    padding: 1rem;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,.13);
    background: rgba(0,0,0,.22);
}

.big-mic {
    min-height: 170px;
    display: grid;
    place-items: center;
    text-align: center;
    border: 1px dashed rgba(24,247,255,.45);
    background: linear-gradient(135deg, rgba(24,247,255,.10), rgba(168,85,247,.12));
    border-radius: 8px;
}

.user-bubble, .bot-bubble {
    padding: 1rem;
    border-radius: 8px;
    margin-bottom: .85rem;
    line-height: 1.9;
    font-size: 1.08rem;
}
.user-bubble {
    background: rgba(24,247,255,.11);
    border: 1px solid rgba(24,247,255,.28);
}
.bot-bubble {
    background: rgba(168,85,247,.13);
    border: 1px solid rgba(168,85,247,.32);
    box-shadow: 0 0 22px rgba(168,85,247,.12);
}

.kpi {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    padding: .58rem .75rem;
    border-radius: 8px;
    background: rgba(255,255,255,.075);
    border: 1px solid rgba(255,255,255,.14);
    margin: .18rem;
    color: var(--text);
    font-weight: 700;
}

.file-card {
    padding: .9rem;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,.14);
    background: rgba(255,255,255,.065);
    margin-bottom: .7rem;
}

[data-testid="stFileUploader"] {
    border: 1px dashed rgba(24,247,255,.44);
    background: rgba(255,255,255,.055);
    border-radius: 8px;
    padding: .8rem;
}

@media (max-width: 900px) {
    .main .block-container {
        padding: .8rem;
    }
    .chat-stage {
        min-height: 45vh;
        max-height: none;
    }
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def init_state():
    defaults = {
        "logged_in": False,
        "username": None,
        "role": None,
        "page": "chat",
        "chat_history": [],
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "pinecone_api_key": os.getenv("PINECONE_API_KEY", ""),
        "pinecone_index": os.getenv("PINECONE_INDEX", DEFAULT_INDEX),
        "pinecone_namespace": os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE),
        "elevenlabs_api_key": os.getenv("ELEVENLABS_API_KEY", ""),
        "elevenlabs_voice_id": os.getenv("ELEVENLABS_VOICE_ID", ""),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def sha_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@st.cache_resource(show_spinner=False)
def init_firebase():
    if firebase_admin is None:
        return None

    if firebase_admin._apps:
        return firestore.client()

    try:
        raw_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
        raw_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "")

        if raw_json:
            cred = credentials.Certificate(json.loads(raw_json))
        elif raw_b64:
            cred = credentials.Certificate(json.loads(base64.b64decode(raw_b64).decode("utf-8")))
        elif os.path.exists("firebase-service-account.json"):
            cred = credentials.Certificate("firebase-service-account.json")
        else:
            return None

        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as exc:
        st.error(f"Firebase error: {exc}")
        return None


def db():
    return init_firebase()


def bootstrap_admin():
    database = db()
    if not database:
        return

    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")

    ref = database.collection(USERS_COLLECTION).document(username)
    if not ref.get().exists:
        ref.set({
            "username": username,
            "password_hash": sha_password(password),
            "role": "admin",
            "active": True,
            "created_at": datetime.utcnow().isoformat(),
        })


def authenticate(username, password):
    database = db()

    if not database:
        if username == os.getenv("LOCAL_ADMIN_USERNAME", "admin") and password == os.getenv("LOCAL_ADMIN_PASSWORD", "admin123"):
            return {"username": username, "role": "admin", "active": True}
        return None

    bootstrap_admin()
    snap = database.collection(USERS_COLLECTION).document(username).get()
    if not snap.exists:
        return None

    user = snap.to_dict()
    if not user.get("active", True):
        return None

    if user.get("password_hash") == sha_password(password):
        return user

    return None


def save_user(username, password, role, active):
    database = db()
    if not database:
        st.warning("Firebase غير متصل.")
        return False

    payload = {
        "username": username,
        "role": role,
        "active": active,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if password:
        payload["password_hash"] = sha_password(password)

    database.collection(USERS_COLLECTION).document(username).set(payload, merge=True)
    return True


def list_users():
    database = db()
    if not database:
        return []
    return [x.to_dict() for x in database.collection(USERS_COLLECTION).stream()]


@st.cache_resource(show_spinner=False)
def pinecone_client(api_key):
    if Pinecone is None or not api_key:
        return None
    return Pinecone(api_key=api_key)


def ensure_index():
    if not st.session_state.pinecone_api_key:
        st.warning("ضع Pinecone API Key من الإعدادات.")
        return False

    pc = pinecone_client(st.session_state.pinecone_api_key)
    if pc is None:
        st.error("مكتبة Pinecone غير مثبتة.")
        return False

    index_name = st.session_state.pinecone_index

    try:
        names = [idx["name"] for idx in pc.list_indexes()]
        if index_name not in names:
            pc.create_index(
                name=index_name,
                dimension=1536,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            time.sleep(8)
        return True
    except Exception as exc:
        st.error(f"Pinecone error: {exc}")
        return False


def vectorstore():
    if not st.session_state.openai_api_key:
        st.warning("ضع OpenAI API Key من الإعدادات.")
        return None

    if not ensure_index():
        return None

    if OpenAIEmbeddings is None or PineconeVectorStore is None:
        st.error("مكتبات LangChain غير مثبتة.")
        return None

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=st.session_state.openai_api_key,
    )

    return PineconeVectorStore(
        index_name=st.session_state.pinecone_index,
        embedding=embeddings,
        namespace=st.session_state.pinecone_namespace,
        pinecone_api_key=st.session_state.pinecone_api_key,
    )


def extract_text(uploaded_file):
    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        if PdfReader is None:
            raise RuntimeError("pypdf غير مثبت.")
        reader = PdfReader(io.BytesIO(data))
        return "\n".join([(page.extract_text() or "") for page in reader.pages])

    if name.endswith(".docx"):
        if docx is None:
            raise RuntimeError("python-docx غير مثبت.")
        document = docx.Document(io.BytesIO(data))
        return "\n".join([p.text for p in document.paragraphs])

    raise RuntimeError("صيغة غير مدعومة.")


def save_file_record(file_id, filename, chunks):
    database = db()
    if not database:
        return
    database.collection(FILES_COLLECTION).document(file_id).set({
        "file_id": file_id,
        "filename": filename,
        "chunks": chunks,
        "index": st.session_state.pinecone_index,
        "namespace": st.session_state.pinecone_namespace,
        "uploaded_by": st.session_state.username,
        "uploaded_at": datetime.utcnow().isoformat(),
    })


def list_files():
    database = db()
    if not database:
        return []
    return [x.to_dict() for x in database.collection(FILES_COLLECTION).stream()]


def delete_file_vectors(file_id):
    try:
        pc = pinecone_client(st.session_state.pinecone_api_key)
        index = pc.Index(st.session_state.pinecone_index)
        index.delete(
            namespace=st.session_state.pinecone_namespace,
            filter={"file_id": {"$eq": file_id}},
        )

        database = db()
        if database:
            database.collection(FILES_COLLECTION).document(file_id).delete()

        return True
    except Exception as exc:
        st.error(f"فشل الحذف: {exc}")
        return False


def process_file(uploaded_file):
    if RecursiveCharacterTextSplitter is None or Document is None:
        st.error("مكتبات LangChain غير مكتملة.")
        return None

    store = vectorstore()
    if not store:
        return None

    text = extract_text(uploaded_file)
    if not text.strip():
        st.warning("الملف لا يحتوي على نص قابل للاستخراج.")
        return None

    file_id = str(uuid.uuid4())
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=180)
    chunks = splitter.split_text(text)

    docs = [
        Document(
            page_content=chunk,
            metadata={
                "file_id": file_id,
                "filename": uploaded_file.name,
                "chunk": i,
                "uploaded_at": datetime.utcnow().isoformat(),
            },
        )
        for i, chunk in enumerate(chunks)
    ]

    ids = [f"{file_id}-{i}" for i in range(len(docs))]
    store.add_documents(docs, ids=ids)
    save_file_record(file_id, uploaded_file.name, len(docs))

    return {"file_id": file_id, "filename": uploaded_file.name, "chunks": len(docs)}


def openai_client():
    if OpenAI is None:
        st.error("مكتبة OpenAI غير مثبتة.")
        return None
    if not st.session_state.openai_api_key:
        st.warning("ضع OpenAI API Key من الإعدادات.")
        return None
    return OpenAI(api_key=st.session_state.openai_api_key)


def transcribe(audio_bytes):
    client = openai_client()
    if not client:
        return ""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_bytes)
        path = tmp.name

    try:
        with open(path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ar",
            )
        return result.text
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def retrieve(question):
    store = vectorstore()
    if not store:
        return "", []

    docs = store.similarity_search(question, k=5)
    context = "\n\n".join([
        f"المصدر: {doc.metadata.get('filename', 'unknown')}\n{doc.page_content}"
        for doc in docs
    ])
    sources = [doc.metadata for doc in docs]
    return context, sources


def answer_question(question, context):
    if ChatOpenAI is None or ChatPromptTemplate is None:
        return "مكتبات LangChain الخاصة بالشات غير مثبتة."

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.3,
        api_key=st.session_state.openai_api_key,
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """
أنت "الأسطى كبير"، خبير صيانة وتشغيل صناعي مصري.
تتكلم بالعامية المصرية البسيطة، لكن باحترام ووضوح شديد.
المستخدم غالبا عامل في المصنع وقد لا يكون خبيرا بالقراءة أو التكنولوجيا.
اجعل الرد قصير، عملي، مرقم، ومباشر.
ابدأ بتحذير أمان لو المشكلة فيها كهرباء، ضغط، حرارة، ماكينة دوارة، زيت، غاز، أو كيميائيات.
لا تخترع بيانات غير موجودة في السياق.
لو السياق ناقص، قل للعامل بوضوح ما الذي يجب تصويره أو قياسه أو سؤال المدير عنه.
            """,
        ),
        (
            "human",
            """
سياق قاعدة المعرفة:
{context}

مشكلة العامل:
{question}

اكتب رد الأسطى كبير:
            """,
        ),
    ])

    chain = prompt | llm
    result = chain.invoke({"context": context, "question": question})
    return result.content


def tts_elevenlabs(text):
    if not st.session_state.elevenlabs_api_key or not st.session_state.elevenlabs_voice_id:
        return None
    if requests is None:
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{st.session_state.elevenlabs_voice_id}"
    headers = {
        "xi-api-key": st.session_state.elevenlabs_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.58,
            "similarity_boost": 0.78,
            "style": 0.32,
            "use_speaker_boost": True,
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code == 200:
        return response.content
    return None


def tts_gtts(text):
    if gTTS is None:
        return None

    audio = io.BytesIO()
    gTTS(text=text, lang="ar", slow=False).write_to_fp(audio)
    audio.seek(0)
    return audio.read()


def text_to_audio(text):
    audio = tts_elevenlabs(text)
    if audio:
        return audio
    return tts_gtts(text)


def page_header(title, subtitle):
    st.markdown(f'<div class="screen-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="screen-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def nav_button(label, page_key):
    active = st.session_state.page == page_key
    css_class = "nav-button active-nav" if active else "nav-button"

    st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
    clicked = st.button(label, key=f"nav_{page_key}", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if clicked:
        st.session_state.page = page_key
        st.rerun()


def sidebar():
    st.sidebar.markdown(
        f"""
<div class="brand">
    <div class="brand-name">🛠️ الأسطى كبير</div>
    <div class="brand-role">المستخدم: {st.session_state.username or "-"}</div>
    <div class="brand-role">الصلاحية: {st.session_state.role or "-"}</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    nav_button("💬 شات الأعطال الصوتي", "chat")

    if st.session_state.role == "admin":
        nav_button("📚 رفع وإدارة المعرفة", "data")
        nav_button("👷 إدارة العمال والمديرين", "users")

    nav_button("⚙️ الإعدادات", "settings")

    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    if st.sidebar.button("تسجيل خروج", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.session_state.page = "chat"
        st.rerun()


def login_page():
    st.markdown('<div class="hero-login">', unsafe_allow_html=True)
    col1, col2 = st.columns([1.15, .85])

    with col1:
        st.markdown(
            """
<div class="glass">
    <div class="screen-title">الأسطى كبير</div>
    <div class="screen-subtitle">
        مساعد صناعي صوتي للعامل والمدير. العامل يسجل العطل بصوته، والنظام يرد من كتالوجات وتعليمات المصنع.
    </div>
    <span class="kpi">🎙️ صوت أولا</span>
    <span class="kpi">📚 RAG صناعي</span>
    <span class="kpi">⚡ واجهة كبيرة وواضحة</span>
    <span class="kpi">🔐 Firebase</span>
</div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        st.subheader("تسجيل الدخول")
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")

        if st.button("دخول للنظام", use_container_width=True):
            user = authenticate(username, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.username = user.get("username", username)
                st.session_state.role = user.get("role", "worker")
                st.session_state.page = "chat"
                st.rerun()
            else:
                st.error("بيانات الدخول غير صحيحة.")

        st.caption("عند عدم توصيل Firebase: admin / admin123")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def chat_page():
    page_header(
        "شات الأعطال الصوتي",
        "واجهة كبيرة وواضحة للعامل: سجل المشكلة أو اكتبها، وخذ رد عملي مباشر من الأسطى كبير.",
    )

    st.markdown('<div class="full-chat">', unsafe_allow_html=True)

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.markdown(
        f"""
<span class="kpi">👤 {st.session_state.username}</span>
<span class="kpi">🗂️ {st.session_state.pinecone_index}</span>
<span class="kpi">🏭 {st.session_state.pinecone_namespace}</span>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="glass chat-stage">', unsafe_allow_html=True)
    if not st.session_state.chat_history:
        st.markdown(
            """
<div class="bot-bubble">
    أنا الأسطى كبير. قولّي العطل بصوتك أو اكتبه، وأنا أرجع لك بخطوات واضحة من معرفة المصنع.
</div>
            """,
            unsafe_allow_html=True,
        )

    for item in st.session_state.chat_history[-8:]:
        st.markdown(f'<div class="user-bubble"><b>العامل:</b><br>{item["question"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="bot-bubble"><b>الأسطى كبير:</b><br>{item["answer"]}</div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    col1, col2 = st.columns([.9, 1.1])

    with col1:
        st.markdown('<div class="big-mic">', unsafe_allow_html=True)
        audio_bytes = None
        if audio_recorder:
            audio_bytes = audio_recorder(
                text="اضغط هنا وسجل العطل",
                recording_color="#ff3fd4",
                neutral_color="#18f7ff",
                icon_name="microphone",
                icon_size="3x",
            )
        else:
            st.warning("تسجيل الصوت غير متاح لأن audio_recorder_streamlit غير مثبت.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        question_text = st.text_area(
            "أو اكتب العطل هنا",
            height=150,
            placeholder="مثال: الطلمبة صوتها عالي والضغط بيقع بعد التشغيل بدقيقتين...",
        )
        ask = st.button("اسأل الأسطى كبير الآن", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    if ask:
        question = question_text.strip()

        if audio_bytes:
            with st.spinner("بفك التسجيل..."):
                question = transcribe(audio_bytes) or question
                if question:
                    st.info(f"النص المستخرج من الصوت: {question}")

        if not question:
            st.warning("سجل العطل أو اكتبه الأول.")
            return

        with st.spinner("براجع معرفة المصنع..."):
            context, sources = retrieve(question)

        with st.spinner("الأسطى كبير بيجهز الرد..."):
            answer = answer_question(question, context)

        audio = None
        with st.spinner("بحول الرد لصوت..."):
            audio = text_to_audio(answer)

        st.session_state.chat_history.append({
            "question": question,
            "answer": answer,
            "sources": sources,
            "time": datetime.now().strftime("%H:%M"),
        })

        if audio:
            st.audio(audio, format="audio/mp3")

        st.rerun()


def data_page():
    page_header(
        "رفع وإدارة المعرفة",
        "ارفع كتالوجات PDF و DOCX و TXT، والنظام يحولها إلى Vector Store داخل Pinecone.",
    )

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    files = st.file_uploader(
        "اختر ملفات المصنع",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
    )

    if st.button("معالجة وتخزين الملفات", use_container_width=True):
        if not files:
            st.warning("اختر ملف واحد على الأقل.")
        else:
            for file in files:
                with st.spinner(f"جاري معالجة {file.name}..."):
                    result = process_file(file)
                if result:
                    st.success(f"تم تخزين {result['filename']} بعدد {result['chunks']} جزء.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("الملفات المسجلة")
    records = list_files()

    if not records:
        st.info("لا توجد ملفات مسجلة بعد.")
        return

    for rec in records:
        st.markdown('<div class="file-card">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([2, 1, .7])
        with c1:
            st.write(f"**{rec.get('filename', 'unknown')}**")
            st.caption(f"ID: {rec.get('file_id')}")
        with c2:
            st.write(f"Chunks: {rec.get('chunks', 0)}")
            st.caption(rec.get("uploaded_at", ""))
        with c3:
            if st.button("حذف", key=f"del_{rec.get('file_id')}", use_container_width=True):
                if delete_file_vectors(rec.get("file_id")):
                    st.success("تم الحذف.")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


def users_page():
    page_header(
        "إدارة العمال والمديرين",
        "إنشاء وتحديث حسابات الدخول عبر Firebase Admin.",
    )

    c1, c2 = st.columns([.9, 1.1])

    with c1:
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور الجديدة", type="password")
        role = st.selectbox("الصلاحية", ["worker", "admin"])
        active = st.toggle("الحساب نشط", value=True)

        if st.button("حفظ المستخدم", use_container_width=True):
            if not username:
                st.warning("اكتب اسم المستخدم.")
            elif save_user(username, password, role, active):
                st.success("تم حفظ المستخدم.")
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="glass">', unsafe_allow_html=True)
        users = list_users()
        if not users:
            st.info("لا توجد بيانات مستخدمين أو Firebase غير متصل.")
        for user in users:
            st.markdown(
                f"""
<div class="file-card">
    <b>{user.get("username")}</b><br>
    الصلاحية: {user.get("role")}<br>
    الحالة: {"نشط" if user.get("active", True) else "موقوف"}
</div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)


def settings_page():
    page_header(
        "الإعدادات",
        "مفاتيح OpenAI و Pinecone و ElevenLabs. يمكن وضعها أيضا كـ Environment Variables.",
    )

    st.markdown('<div class="glass">', unsafe_allow_html=True)

    st.session_state.openai_api_key = st.text_input(
        "OpenAI API Key",
        value=st.session_state.openai_api_key,
        type="password",
    )
    st.session_state.pinecone_api_key = st.text_input(
        "Pinecone API Key",
        value=st.session_state.pinecone_api_key,
        type="password",
    )
    st.session_state.pinecone_index = st.text_input(
        "Pinecone Index",
        value=st.session_state.pinecone_index,
    )
    st.session_state.pinecone_namespace = st.text_input(
        "Pinecone Namespace",
        value=st.session_state.pinecone_namespace,
    )
    st.session_state.elevenlabs_api_key = st.text_input(
        "ElevenLabs API Key اختياري",
        value=st.session_state.elevenlabs_api_key,
        type="password",
    )
    st.session_state.elevenlabs_voice_id = st.text_input(
        "ElevenLabs Voice ID اختياري",
        value=st.session_state.elevenlabs_voice_id,
    )

    if st.button("اختبار Pinecone / إنشاء Index", use_container_width=True):
        if ensure_index():
            st.success("Pinecone جاهز.")

    st.markdown("</div>", unsafe_allow_html=True)


def router():
    sidebar()

    st.markdown('<div class="app-shell">', unsafe_allow_html=True)

    if st.session_state.page == "chat":
        chat_page()
    elif st.session_state.page == "data" and st.session_state.role == "admin":
        data_page()
    elif st.session_state.page == "users" and st.session_state.role == "admin":
        users_page()
    elif st.session_state.page == "settings":
        settings_page()
    else:
        st.session_state.page = "chat"
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def main():
    css()
    init_state()
    bootstrap_admin()

    if not st.session_state.logged_in:
        login_page()
    else:
        router()


if __name__ == "__main__":
    main()


