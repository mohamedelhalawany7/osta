

import os
import io
import json
import time
import uuid
import base64
import hashlib
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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


APP_NAME = "Industrial Knowledge RAG"
DEFAULT_INDEX = "industrial-knowledge-rag"
DEFAULT_NAMESPACE = "factory-knowledge"
FIREBASE_COLLECTION_USERS = "users"
FIREBASE_COLLECTION_FILES = "rag_files"


st.set_page_config(
    page_title=APP_NAME,
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================
# CSS: Glassmorphism + Neon
# =========================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg-0: #050712;
            --bg-1: #090d1f;
            --glass: rgba(255, 255, 255, 0.075);
            --glass-strong: rgba(255, 255, 255, 0.125);
            --line: rgba(255, 255, 255, 0.16);
            --cyan: #21f7ff;
            --purple: #a855f7;
            --pink: #ff4fd8;
            --text: #eef7ff;
            --muted: #9fb3c8;
            --danger: #ff476f;
            --ok: #33f2a0;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 12% 12%, rgba(33, 247, 255, 0.18), transparent 30%),
                radial-gradient(circle at 88% 16%, rgba(168, 85, 247, 0.20), transparent 28%),
                radial-gradient(circle at 50% 95%, rgba(255, 79, 216, 0.12), transparent 28%),
                linear-gradient(145deg, var(--bg-0), var(--bg-1));
            color: var(--text);
            font-family: Inter, Segoe UI, Tahoma, Arial, sans-serif;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        [data-testid="stSidebar"] {
            background: rgba(4, 7, 18, 0.74);
            backdrop-filter: blur(18px);
            border-right: 1px solid rgba(33, 247, 255, 0.18);
        }

        [data-testid="stSidebar"] * {
            color: var(--text);
        }

        .main-title {
            font-size: clamp(2rem, 5vw, 4.3rem);
            line-height: 1;
            font-weight: 900;
            letter-spacing: 0;
            margin: 0 0 0.6rem;
            background: linear-gradient(90deg, var(--cyan), #ffffff, var(--purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 32px rgba(33, 247, 255, 0.24);
        }

        .subtitle {
            color: var(--muted);
            font-size: clamp(0.95rem, 2vw, 1.15rem);
            max-width: 850px;
            margin-bottom: 1.1rem;
        }

        .glass-card {
            background: var(--glass);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1.1rem;
            box-shadow:
                0 0 0 1px rgba(33, 247, 255, 0.05),
                0 18px 50px rgba(0, 0, 0, 0.32),
                inset 0 1px 0 rgba(255, 255, 255, 0.12);
            backdrop-filter: blur(18px);
            margin-bottom: 1rem;
        }

        .neon-card {
            background: linear-gradient(135deg, rgba(33, 247, 255, 0.12), rgba(168, 85, 247, 0.12));
            border: 1px solid rgba(33, 247, 255, 0.35);
            box-shadow:
                0 0 22px rgba(33, 247, 255, 0.16),
                0 0 30px rgba(168, 85, 247, 0.12);
            border-radius: 8px;
            padding: 1rem;
        }

        .metric-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.6rem 0.8rem;
            margin: 0.2rem 0.2rem 0.2rem 0;
            border-radius: 8px;
            border: 1px solid rgba(33, 247, 255, 0.25);
            background: rgba(255,255,255,0.07);
            color: var(--text);
            font-size: 0.92rem;
        }

        .role-pill {
            display: inline-block;
            border: 1px solid rgba(168, 85, 247, 0.45);
            background: rgba(168, 85, 247, 0.12);
            color: #f1dcff;
            border-radius: 8px;
            padding: 0.35rem 0.6rem;
            font-weight: 700;
            margin-bottom: 0.8rem;
        }

        .answer-box {
            background: rgba(0, 0, 0, 0.25);
            border-left: 3px solid var(--cyan);
            border-radius: 8px;
            padding: 1rem;
            white-space: pre-wrap;
            color: var(--text);
        }

        .source-box {
            color: var(--muted);
            font-size: 0.88rem;
            border-top: 1px solid rgba(255,255,255,0.10);
            margin-top: 0.75rem;
            padding-top: 0.75rem;
        }

        .stButton > button,
        .stDownloadButton > button {
            border-radius: 8px !important;
            border: 1px solid rgba(33, 247, 255, 0.38) !important;
            background: linear-gradient(135deg, rgba(33, 247, 255, 0.16), rgba(168, 85, 247, 0.18)) !important;
            color: var(--text) !important;
            box-shadow: 0 0 18px rgba(33, 247, 255, 0.12);
            font-weight: 800 !important;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            border-color: rgba(33, 247, 255, 0.8) !important;
            box-shadow: 0 0 30px rgba(33, 247, 255, 0.28);
            transform: translateY(-1px);
        }

        input, textarea, select {
            border-radius: 8px !important;
        }

        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input {
            background: rgba(255,255,255,0.08) !important;
            border: 1px solid rgba(255,255,255,0.18) !important;
            color: var(--text) !important;
        }

        [data-testid="stFileUploader"] {
            background: rgba(255,255,255,0.06);
            border: 1px dashed rgba(33, 247, 255, 0.35);
            border-radius: 8px;
            padding: 0.8rem;
        }

        .success-text { color: var(--ok); font-weight: 800; }
        .danger-text { color: var(--danger); font-weight: 800; }

        @media (max-width: 768px) {
            .glass-card, .neon-card {
                padding: 0.85rem;
            }

            [data-testid="column"] {
                width: 100% !important;
                flex: 1 1 100% !important;
            }

            .main-title {
                font-size: 2.2rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================
# Session State
# =========================

def init_state() -> None:
    defaults = {
        "logged_in": False,
        "user_id": None,
        "username": None,
        "role": None,
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "pinecone_api_key": os.getenv("PINECONE_API_KEY", ""),
        "pinecone_index": os.getenv("PINECONE_INDEX", DEFAULT_INDEX),
        "pinecone_namespace": os.getenv("PINECONE_NAMESPACE", DEFAULT_NAMESPACE),
        "elevenlabs_api_key": os.getenv("ELEVENLABS_API_KEY", ""),
        "elevenlabs_voice_id": os.getenv("ELEVENLABS_VOICE_ID", ""),
        "chat_history": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# =========================
# Firebase
# =========================

def sha256_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@st.cache_resource(show_spinner=False)
def init_firebase():
    if firebase_admin is None:
        return None

    if firebase_admin._apps:
        return firestore.client()

    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    service_account_b64 = os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "")

    try:
        if service_account_json:
            info = json.loads(service_account_json)
            cred = credentials.Certificate(info)
        elif service_account_b64:
            info = json.loads(base64.b64decode(service_account_b64).decode("utf-8"))
            cred = credentials.Certificate(info)
        elif os.path.exists("firebase-service-account.json"):
            cred = credentials.Certificate("firebase-service-account.json")
        else:
            return None

        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as exc:
        st.error(f"Firebase init failed: {exc}")
        return None


def get_db():
    return init_firebase()


def bootstrap_admin_if_needed(db) -> None:
    admin_user = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")

    if not db:
        return

    try:
        ref = db.collection(FIREBASE_COLLECTION_USERS).document(admin_user)
        if not ref.get().exists:
            ref.set(
                {
                    "username": admin_user,
                    "password_hash": sha256_password(admin_pass),
                    "role": "admin",
                    "created_at": datetime.utcnow().isoformat(),
                    "active": True,
                }
            )
    except Exception:
        pass


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    db = get_db()

    if not db:
        fallback_user = os.getenv("LOCAL_ADMIN_USERNAME", "admin")
        fallback_pass = os.getenv("LOCAL_ADMIN_PASSWORD", "admin123")
        if username == fallback_user and password == fallback_pass:
            return {"username": username, "role": "admin", "active": True}
        return None

    bootstrap_admin_if_needed(db)

    try:
        snap = db.collection(FIREBASE_COLLECTION_USERS).document(username).get()
        if not snap.exists:
            return None

        user = snap.to_dict()
        if not user.get("active", True):
            return None

        if user.get("password_hash") == sha256_password(password):
            return user
    except Exception as exc:
        st.error(f"Authentication error: {exc}")

    return None


def create_or_update_user(username: str, password: str, role: str, active: bool = True) -> bool:
    db = get_db()
    if not db:
        st.warning("Firebase غير متصل. لا يمكن حفظ المستخدمين إلا بعد تفعيل Firebase.")
        return False

    try:
        payload = {
            "username": username,
            "role": role,
            "active": active,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if password:
            payload["password_hash"] = sha256_password(password)

        ref = db.collection(FIREBASE_COLLECTION_USERS).document(username)
        if not ref.get().exists:
            payload["created_at"] = datetime.utcnow().isoformat()

        ref.set(payload, merge=True)
        return True
    except Exception as exc:
        st.error(f"User save failed: {exc}")
        return False


def list_users() -> List[Dict]:
    db = get_db()
    if not db:
        return []

    try:
        docs = db.collection(FIREBASE_COLLECTION_USERS).stream()
        return [doc.to_dict() for doc in docs]
    except Exception:
        return []


# =========================
# Pinecone / LangChain
# =========================

def get_openai_client() -> Optional[OpenAI]:
    if OpenAI is None:
        st.error("OpenAI package غير مثبت.")
        return None

    key = st.session_state.openai_api_key
    if not key:
        st.warning("أدخل OpenAI API Key من الإعدادات.")
        return None

    return OpenAI(api_key=key)


@st.cache_resource(show_spinner=False)
def get_pinecone_client(api_key: str):
    if Pinecone is None:
        return None
    if not api_key:
        return None
    return Pinecone(api_key=api_key)


def ensure_pinecone_index() -> bool:
    api_key = st.session_state.pinecone_api_key
    index_name = st.session_state.pinecone_index

    if not api_key:
        st.warning("أدخل Pinecone API Key من الإعدادات.")
        return False

    pc = get_pinecone_client(api_key)
    if pc is None:
        st.error("Pinecone package غير مثبت.")
        return False

    try:
        existing = [idx["name"] for idx in pc.list_indexes()]
        if index_name not in existing:
            pc.create_index(
                name=index_name,
                dimension=1536,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            with st.spinner("جاري إنشاء Pinecone index..."):
                time.sleep(8)
        return True
    except Exception as exc:
        st.error(f"Pinecone index error: {exc}")
        return False


def get_vectorstore():
    if not ensure_pinecone_index():
        return None

    if OpenAIEmbeddings is None or PineconeVectorStore is None:
        st.error("LangChain packages غير مثبتة.")
        return None

    try:
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
    except Exception as exc:
        st.error(f"VectorStore error: {exc}")
        return None


def extract_text_from_file(uploaded_file) -> str:
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()

    if name.endswith(".txt"):
        return raw.decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        if PdfReader is None:
            raise RuntimeError("pypdf غير مثبت.")
        reader = PdfReader(io.BytesIO(raw))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)

    if name.endswith(".docx"):
        if docx is None:
            raise RuntimeError("python-docx غير مثبت.")
        document = docx.Document(io.BytesIO(raw))
        return "\n".join([p.text for p in document.paragraphs])

    raise ValueError("صيغة غير مدعومة. استخدم PDF أو DOCX أو TXT.")


def save_file_record(file_id: str, filename: str, chunks: int) -> None:
    db = get_db()
    if not db:
        return

    db.collection(FIREBASE_COLLECTION_FILES).document(file_id).set(
        {
            "file_id": file_id,
            "filename": filename,
            "chunks": chunks,
            "namespace": st.session_state.pinecone_namespace,
            "index": st.session_state.pinecone_index,
            "uploaded_by": st.session_state.username,
            "uploaded_at": datetime.utcnow().isoformat(),
        }
    )


def list_file_records() -> List[Dict]:
    db = get_db()
    if not db:
        return []

    try:
        docs = db.collection(FIREBASE_COLLECTION_FILES).stream()
        return [doc.to_dict() for doc in docs]
    except Exception:
        return []


def delete_file_record(file_id: str) -> None:
    db = get_db()
    if db:
        db.collection(FIREBASE_COLLECTION_FILES).document(file_id).delete()


def delete_file_vectors(file_id: str) -> bool:
    api_key = st.session_state.pinecone_api_key
    index_name = st.session_state.pinecone_index

    try:
        pc = get_pinecone_client(api_key)
        index = pc.Index(index_name)
        index.delete(
            namespace=st.session_state.pinecone_namespace,
            filter={"file_id": {"$eq": file_id}},
        )
        delete_file_record(file_id)
        return True
    except Exception as exc:
        st.error(f"Delete failed: {exc}")
        return False


def process_file(uploaded_file) -> Optional[Dict]:
    if RecursiveCharacterTextSplitter is None or Document is None:
        st.error("LangChain text splitter غير مثبت.")
        return None

    vectorstore = get_vectorstore()
    if not vectorstore:
        return None

    try:
        text = extract_text_from_file(uploaded_file)
        if not text.strip():
            st.warning("الملف لا يحتوي على نص قابل للاستخراج.")
            return None

        file_id = str(uuid.uuid4())
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=180,
            separators=["\n\n", "\n", ".", " ", ""],
        )

        chunks = splitter.split_text(text)
        documents = [
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

        ids = [f"{file_id}-{i}" for i in range(len(documents))]
        vectorstore.add_documents(documents=documents, ids=ids)
        save_file_record(file_id, uploaded_file.name, len(documents))

        return {"file_id": file_id, "filename": uploaded_file.name, "chunks": len(documents)}
    except Exception as exc:
        st.error(f"File processing failed: {exc}")
        return None


# =========================
# Audio + RAG Chat
# =========================

def transcribe_audio(audio_bytes: bytes) -> Optional[str]:
    client = get_openai_client()
    if not client:
        return None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ar",
            )

        try:
            os.remove(tmp_path)
        except Exception:
            pass

        return result.text
    except Exception as exc:
        st.error(f"Whisper transcription failed: {exc}")
        return None


def retrieve_context(question: str, k: int = 5) -> Tuple[str, List[Dict]]:
    vectorstore = get_vectorstore()
    if not vectorstore:
        return "", []

    try:
        docs = vectorstore.similarity_search(question, k=k)
        context = "\n\n".join(
            [f"[Source: {doc.metadata.get('filename', 'unknown')}]\n{doc.page_content}" for doc in docs]
        )
        sources = [doc.metadata for doc in docs]
        return context, sources
    except Exception as exc:
        st.error(f"Retrieval failed: {exc}")
        return "", []


def generate_answer(question: str, context: str) -> str:
    if ChatOpenAI is None or ChatPromptTemplate is None:
        return "LangChain ChatOpenAI غير مثبت."

    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.35,
            api_key=st.session_state.openai_api_key,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
أنت "الأسطى كبير": خبير صيانة صناعية مصري مخضرم.
أسلوبك عامي مصري محترم، عملي، مختصر، وواثق.
اشرح للعامل الخطوات بوضوح وبالترتيب.
لو في خطر كهربا، ضغط، حرارة، مواد كيماوية، أو ماكينة دوارة، ابدأ بتحذير أمان واضح.
اعتمد فقط على السياق الصناعي المرفق. لو المعلومة ناقصة قل إنك محتاج كتالوج أو قراءة إضافية.
لا تخترع أرقام عزم أو ضغط أو حرارة غير موجودة في السياق.
                    """,
                ),
                (
                    "human",
                    """
السياق من قاعدة المعرفة:
{context}

مشكلة العامل:
{question}

اكتب الرد بصوت الأسطى كبير:
                    """,
                ),
            ]
        )

        chain = prompt | llm
        response = chain.invoke({"context": context, "question": question})
        return response.content
    except Exception as exc:
        return f"LLM failed: {exc}"


def elevenlabs_tts(text: str) -> Optional[bytes]:
    api_key = st.session_state.elevenlabs_api_key
    voice_id = st.session_state.elevenlabs_voice_id

    if not api_key or not voice_id or requests is None:
        return None

    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.55,
                "similarity_boost": 0.75,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        if res.status_code == 200:
            return res.content
    except Exception:
        return None

    return None


def gtts_tts(text: str) -> Optional[bytes]:
    if gTTS is None:
        return None

    try:
        audio_io = io.BytesIO()
        tts = gTTS(text=text, lang="ar", slow=False)
        tts.write_to_fp(audio_io)
        audio_io.seek(0)
        return audio_io.read()
    except Exception as exc:
        st.warning(f"gTTS failed: {exc}")
        return None


def text_to_speech(text: str) -> Optional[bytes]:
    audio = elevenlabs_tts(text)
    if audio:
        return audio
    return gtts_tts(text)


def chat_interface() -> None:
    st.markdown('<div class="main-title">Voice-First RAG</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">سجل العطل بصوتك، والنظام يسترجع المعرفة الصناعية ويرد عليك بأسلوب الأسطى كبير.</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)

    col1, col2 = st.columns([1.05, 1])

    with col1:
        st.subheader("تسجيل المشكلة")
        typed_question = st.text_area(
            "اكتب المشكلة لو التسجيل غير متاح",
            placeholder="مثال: الموتور بيسخن بعد 10 دقايق تشغيل وفيه صوت عالي من ناحية البلية...",
            height=130,
        )

        audio_bytes = None
        if audio_recorder:
            audio_bytes = audio_recorder(
                text="اضغط وسجل المشكلة",
                recording_color="#ff4fd8",
                neutral_color="#21f7ff",
                icon_name="microphone",
                icon_size="2x",
            )
        else:
            st.warning("audio_recorder_streamlit غير مثبت. استخدم الكتابة مؤقتاً.")

        ask = st.button("اسأل الأسطى كبير", use_container_width=True)

    with col2:
        st.subheader("حالة النظام")
        st.markdown(
            f"""
            <span class="metric-chip">Index: {st.session_state.pinecone_index}</span>
            <span class="metric-chip">Namespace: {st.session_state.pinecone_namespace}</span>
            <span class="metric-chip">User: {st.session_state.username}</span>
            """,
            unsafe_allow_html=True,
        )
        st.caption("تأكد أن ملفات المعرفة مرفوعة من لوحة المدير قبل السؤال.")

    st.markdown("</div>", unsafe_allow_html=True)

    if ask:
        question = typed_question.strip()

        if audio_bytes:
            with st.spinner("بفك التسجيل وبحوله لنص..."):
                transcribed = transcribe_audio(audio_bytes)
                if transcribed:
                    question = transcribed
                    st.info(f"النص المستخرج: {question}")

        if not question:
            st.warning("اكتب المشكلة أو سجلها صوتياً أولاً.")
            return

        with st.spinner("بفتش في قاعدة المعرفة الصناعية..."):
            context, sources = retrieve_context(question)

        with st.spinner("الأسطى كبير بيجهز الرد..."):
            answer = generate_answer(question, context)

        st.session_state.chat_history.append(
            {
                "question": question,
                "answer": answer,
                "sources": sources,
                "time": datetime.now().strftime("%H:%M:%S"),
            }
        )

        with st.spinner("بحول الرد لصوت..."):
            audio_reply = text_to_speech(answer)

        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("رد الأسطى كبير")
        st.markdown(f'<div class="answer-box">{answer}</div>', unsafe_allow_html=True)

        if audio_reply:
            st.audio(audio_reply, format="audio/mp3")

        if sources:
            source_names = sorted(set([s.get("filename", "unknown") for s in sources]))
            st.markdown(
                f'<div class="source-box">المصادر: {", ".join(source_names)}</div>',
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.chat_history:
        st.subheader("آخر المحادثات")
        for item in reversed(st.session_state.chat_history[-5:]):
            with st.expander(f"{item['time']} - {item['question'][:70]}"):
                st.write(item["answer"])


# =========================
# Admin Panel
# =========================

def settings_panel() -> None:
    st.markdown('<div class="main-title">Settings</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">إدارة مفاتيح التشغيل والاتصال بالخدمات الخارجية.</div>', unsafe_allow_html=True)

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)

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
        if ensure_pinecone_index():
            st.success("Pinecone جاهز.")

    st.markdown("</div>", unsafe_allow_html=True)


def data_upload_panel() -> None:
    st.markdown('<div class="main-title">Knowledge Upload</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">ارفع كتالوجات، إجراءات صيانة، تقارير أعطال، وملفات تشغيل.</div>', unsafe_allow_html=True)

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "ملفات المعرفة الصناعية",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
    )

    if st.button("معالجة وتخزين الملفات", use_container_width=True):
        if not uploaded_files:
            st.warning("اختر ملف واحد على الأقل.")
        else:
            for file in uploaded_files:
                with st.spinner(f"جاري معالجة {file.name}..."):
                    result = process_file(file)
                if result:
                    st.success(f"تم تخزين {result['filename']} بعدد {result['chunks']} chunks.")

    st.markdown("</div>", unsafe_allow_html=True)

    st.subheader("إدارة الملفات")
    records = list_file_records()

    if not records:
        st.info("لا توجد ملفات مسجلة في Firebase حتى الآن.")
        return

    for rec in records:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            st.write(f"**{rec.get('filename', 'unknown')}**")
            st.caption(f"File ID: {rec.get('file_id')} | Chunks: {rec.get('chunks')}")

        with col2:
            st.caption(rec.get("uploaded_at", ""))

        with col3:
            if st.button("حذف", key=f"delete-{rec.get('file_id')}", use_container_width=True):
                if delete_file_vectors(rec.get("file_id")):
                    st.success("تم حذف الملف من Pinecone و Firebase.")
                    st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


def users_panel() -> None:
    st.markdown('<div class="main-title">Users</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">إدارة دخول العمال والمديرين عبر Firebase Admin.</div>', unsafe_allow_html=True)

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["worker", "admin"])
        active = st.toggle("Active", value=True)

        if st.button("حفظ المستخدم", use_container_width=True):
            if not username:
                st.warning("اكتب username.")
            elif create_or_update_user(username, password, role, active):
                st.success("تم حفظ المستخدم.")

    with col2:
        st.write("المستخدمون الحاليون")
        users = list_users()
        if users:
            for user in users:
                st.markdown(
                    f"""
                    <div class="neon-card">
                        <b>{user.get("username")}</b><br/>
                        Role: {user.get("role")}<br/>
                        Active: {user.get("active", True)}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("Firebase غير متصل أو لا توجد بيانات.")

    st.markdown("</div>", unsafe_allow_html=True)


def admin_panel() -> None:
    page = st.sidebar.radio(
        "Admin Navigation",
        ["الشات", "رفع البيانات", "الإعدادات", "المستخدمون"],
    )

    if page == "الشات":
        chat_interface()
    elif page == "رفع البيانات":
        data_upload_panel()
    elif page == "الإعدادات":
        settings_panel()
    elif page == "المستخدمون":
        users_panel()


def worker_panel() -> None:
    page = st.sidebar.radio("Worker Navigation", ["الشات", "الإعدادات"])
    if page == "الشات":
        chat_interface()
    else:
        settings_panel()


# =========================
# Login UI
# =========================

def login_screen() -> None:
    st.markdown('<div class="main-title">Industrial Knowledge RAG</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="subtitle">منصة معرفة صناعية صوتية للورش والمصانع: اسأل عن العطل، واستقبل رد عملي من قاعدة معرفة المصنع.</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.05, 0.95])

    with left:
        st.markdown(
            """
            <div class="glass-card">
                <div class="role-pill">Factory Intelligence</div>
                <h3>نظام واحد للعمال والمديرين</h3>
                <p style="color:#9fb3c8">
                    المدير يرفع ملفات المعرفة ويدير المستخدمين. العامل يسجل المشكلة بصوته ويحصل على إجابة عملية مبنية على مستندات المصنع.
                </p>
                <span class="metric-chip">Voice RAG</span>
                <span class="metric-chip">Pinecone</span>
                <span class="metric-chip">Firebase</span>
                <span class="metric-chip">Glass UI</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("تسجيل الدخول")

        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")

        if st.button("دخول", use_container_width=True):
            user = authenticate_user(username, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user_id = username
                st.session_state.username = user.get("username", username)
                st.session_state.role = user.get("role", "worker")
                st.success("تم تسجيل الدخول.")
                st.rerun()
            else:
                st.error("بيانات الدخول غير صحيحة.")

        st.caption("Fallback محلي عند عدم اتصال Firebase: admin / admin123")
        st.markdown("</div>", unsafe_allow_html=True)


# =========================
# Main
# =========================

def app_shell() -> None:
    st.sidebar.markdown("## Industrial RAG")
    st.sidebar.markdown(
        f"""
        <div class="neon-card">
            <b>{st.session_state.username}</b><br/>
            Role: {st.session_state.role}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.sidebar.button("تسجيل خروج", use_container_width=True):
        for key in ["logged_in", "user_id", "username", "role"]:
            st.session_state[key] = False if key == "logged_in" else None
        st.rerun()

    if st.session_state.role == "admin":
        admin_panel()
    else:
        worker_panel()


def main() -> None:
    inject_css()
    init_state()

    db = get_db()
    if db:
        bootstrap_admin_if_needed(db)

    if not st.session_state.logged_in:
        login_screen()
    else:
        app_shell()


if __name__ == "__main__":
    main()





