import base64
import io
import json
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from streamlit_mic_recorder import mic_recorder

try:
    import docx2txt
except Exception:
    docx2txt = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except Exception:
    firebase_admin = None
    credentials = None
    firestore = None


APP_DIR = Path(__file__).resolve().parent
LOCAL_DB = APP_DIR / "local_app.db"
UPLOAD_DIR = APP_DIR / "uploaded_files"
UPLOAD_DIR.mkdir(exist_ok=True)

DEFAULT_SYSTEM_PROMPT = """
انت مساعد صيانة وتصنيع معدني داخل ورشة CNC ومخارط وفرايز ومقاشط ومثاقب وليزر ولحام وضواغط ومجففات هواء.
ردك يكون بالمصري العامي الصنايعي، واضح وقصير ومنظم.
ابدأ بتشخيص احتمالات العطل، ثم خطوات فحص آمنة، ثم الحل، ثم تحذيرات السلامة.
لو السؤال فيه خطر كهرباء/هواء مضغوط/دوران/ليزر/لحام، اذكر فصل الطاقة وتفريغ الضغط ولبس مهمات الوقاية قبل أي خطوة.
لو المعلومات من ملفات الشركة مش كفاية، قول كده بصراحة واسأل عن قراءة العداد أو الصوت أو الكود أو نوع الماكينة.
"""


st.set_page_config(
    page_title="CNC RAG Voice Assistant",
    page_icon="⚙",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg0: #05070d;
            --bg1: #0a1020;
            --cyan: #00e5ff;
            --lime: #b6ff3b;
            --pink: #ff2bd6;
            --orange: #ffb000;
            --muted: #a9b5c7;
            --glass: rgba(255, 255, 255, .075);
            --stroke: rgba(255, 255, 255, .17);
        }
        html, body, [data-testid="stAppViewContainer"] {
            direction: rtl;
            background:
              radial-gradient(circle at 8% 8%, rgba(0, 229, 255, .22), transparent 26rem),
              radial-gradient(circle at 88% 20%, rgba(255, 43, 214, .18), transparent 24rem),
              linear-gradient(135deg, #04070d 0%, #0d1020 42%, #07151a 100%);
            color: #eef7ff;
        }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(7, 13, 28, .88), rgba(4, 7, 13, .96));
            border-left: 1px solid rgba(255, 255, 255, .14);
        }
        .block-container {
            padding-top: 1.5rem;
            max-width: 1420px;
        }
        h1, h2, h3 { letter-spacing: 0; }
        h1 {
            font-size: clamp(2rem, 4vw, 4.6rem);
            line-height: 1.04;
            margin-bottom: .35rem;
        }
        .hero {
            padding: 1.2rem 0 1.1rem;
            border-bottom: 1px solid rgba(255,255,255,.12);
            margin-bottom: 1rem;
        }
        .hero small {
            color: var(--lime);
            font-weight: 800;
            letter-spacing: .08em;
        }
        .glass {
            background: linear-gradient(135deg, rgba(255,255,255,.11), rgba(255,255,255,.045));
            border: 1px solid var(--stroke);
            box-shadow: 0 24px 80px rgba(0,0,0,.32);
            backdrop-filter: blur(18px);
            border-radius: 8px;
            padding: 1rem;
        }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: .75rem;
            margin: .8rem 0 1.2rem;
        }
        .metric-tile {
            min-height: 92px;
            border: 1px solid rgba(255,255,255,.14);
            border-radius: 8px;
            padding: .9rem;
            background: rgba(255,255,255,.06);
        }
        .metric-tile b {
            display: block;
            font-size: 1.5rem;
            color: white;
        }
        .metric-tile span { color: var(--muted); font-size: .9rem; }
        .chat-user, .chat-ai {
            border-radius: 8px;
            padding: .95rem 1rem;
            margin: .65rem 0;
            border: 1px solid rgba(255,255,255,.13);
        }
        .chat-user {
            background: linear-gradient(135deg, rgba(0,229,255,.17), rgba(0,229,255,.045));
        }
        .chat-ai {
            background: linear-gradient(135deg, rgba(182,255,59,.13), rgba(255,43,214,.055));
        }
        .source-chip {
            display: inline-block;
            margin: .2rem .15rem;
            padding: .28rem .55rem;
            border: 1px solid rgba(0,229,255,.35);
            color: #dffbff;
            border-radius: 999px;
            background: rgba(0,229,255,.08);
            font-size: .82rem;
        }
        .stButton>button, .stDownloadButton>button {
            border-radius: 8px;
            border: 1px solid rgba(0,229,255,.42);
            background: linear-gradient(135deg, rgba(0,229,255,.22), rgba(255,43,214,.16));
            color: white;
            min-height: 2.55rem;
            font-weight: 800;
        }
        .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"],
        .stNumberInput input {
            border-radius: 8px;
            border-color: rgba(255,255,255,.18) !important;
            background: rgba(255,255,255,.07) !important;
            color: white !important;
        }
        [data-testid="stFileUploader"] {
            border: 1px dashed rgba(0,229,255,.34);
            border-radius: 8px;
            padding: .7rem;
            background: rgba(255,255,255,.045);
        }
        .status-ok { color: var(--lime); font-weight: 800; }
        .status-bad { color: #ff6b8b; font-weight: 800; }
        .caption { color: var(--muted); font-size: .92rem; }
        @media (max-width: 720px) {
            .block-container { padding: .9rem .75rem 2rem; }
            h1 { font-size: 2rem; }
            .glass { padding: .75rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_local_db() -> None:
    with sqlite3.connect(LOCAL_DB) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pin TEXT NOT NULL,
                role TEXT NOT NULL,
                can_chat INTEGER DEFAULT 1,
                can_upload INTEGER DEFAULT 0,
                can_settings INTEGER DEFAULT 0,
                can_users INTEGER DEFAULT 0
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                namespace TEXT NOT NULL,
                chunks INTEGER NOT NULL,
                uploaded_by TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        admin_count = con.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        if admin_count == 0:
            con.execute(
                """
                INSERT OR IGNORE INTO users
                (id, name, pin, role, can_chat, can_upload, can_settings, can_users)
                VALUES (?, ?, ?, ?, 1, 1, 1, 1)
                """,
                ("admin", "المدير", "1234", "admin"),
            )
        con.commit()


def get_setting(key: str, default: str = "") -> str:
    if key in st.session_state:
        return st.session_state[key]
    with sqlite3.connect(LOCAL_DB) as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    value = row[0] if row else default
    st.session_state[key] = value
    return value


def set_setting(key: str, value: str) -> None:
    st.session_state[key] = value
    with sqlite3.connect(LOCAL_DB) as con:
        con.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        con.commit()


def effective_secret(name: str, setting_key: str = "") -> str:
    return os.getenv(name) or get_setting(setting_key or name.lower(), "")


def get_openai_client() -> Optional[OpenAI]:
    key = effective_secret("OPENAI_API_KEY", "openai_api_key")
    if not key:
        return None
    return OpenAI(api_key=key)


def get_pinecone_index():
    key = effective_secret("PINECONE_API_KEY", "pinecone_api_key")
    index_name = get_setting("pinecone_index", "cnc-rag")
    cloud = get_setting("pinecone_cloud", "aws")
    region = get_setting("pinecone_region", "us-east-1")
    dimension = int(get_setting("embedding_dimension", "1536") or "1536")
    metric = get_setting("pinecone_metric", "cosine")
    if not key or not index_name:
        return None
    pc = Pinecone(api_key=key)
    listed_indexes = pc.list_indexes()
    if hasattr(listed_indexes, "names"):
        existing = listed_indexes.names()
    else:
        existing = [idx["name"] if isinstance(idx, dict) else getattr(idx, "name", "") for idx in listed_indexes]
    if index_name not in existing:
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric=metric,
            spec=ServerlessSpec(cloud=cloud, region=region),
        )
        time.sleep(4)
    return pc.Index(index_name)


def init_firebase():
    if firebase_admin is None:
        return None
    raw = effective_secret("FIREBASE_SERVICE_ACCOUNT_JSON", "firebase_service_account_json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        app_name = "cnc-rag-firebase"
        if not firebase_admin._apps:
            cred = credentials.Certificate(data)
            firebase_admin.initialize_app(cred, name=app_name)
        app = firebase_admin.get_app(app_name) if app_name in firebase_admin._apps else firebase_admin.get_app()
        return firestore.client(app=app)
    except Exception as exc:
        st.warning(f"Firebase مش متوصل: {exc}")
        return None


def list_local_users() -> List[Dict[str, Any]]:
    with sqlite3.connect(LOCAL_DB) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM users ORDER BY role, name").fetchall()
    return [dict(r) for r in rows]


def upsert_local_user(user: Dict[str, Any]) -> None:
    with sqlite3.connect(LOCAL_DB) as con:
        con.execute(
            """
            INSERT INTO users(id, name, pin, role, can_chat, can_upload, can_settings, can_users)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, pin=excluded.pin, role=excluded.role,
            can_chat=excluded.can_chat, can_upload=excluded.can_upload,
            can_settings=excluded.can_settings, can_users=excluded.can_users
            """,
            (
                user["id"],
                user["name"],
                user["pin"],
                user["role"],
                int(user.get("can_chat", True)),
                int(user.get("can_upload", False)),
                int(user.get("can_settings", False)),
                int(user.get("can_users", False)),
            ),
        )
        con.commit()


def delete_local_user(user_id: str) -> None:
    if user_id == "admin":
        return
    with sqlite3.connect(LOCAL_DB) as con:
        con.execute("DELETE FROM users WHERE id=?", (user_id,))
        con.commit()


def authenticate(user_id: str, pin: str) -> Optional[Dict[str, Any]]:
    db = init_firebase()
    if db:
        doc = db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            if str(data.get("pin")) == str(pin):
                return {"id": user_id, **data}
    with sqlite3.connect(LOCAL_DB) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM users WHERE id=? AND pin=?", (user_id, pin)).fetchone()
    return dict(row) if row else None


def can(permission: str) -> bool:
    user = st.session_state.get("user") or {}
    if user.get("role") == "admin":
        return True
    return bool(user.get(permission))


def extract_text(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix.lower()
    raw = uploaded_file.getvalue()
    if suffix in {".txt", ".md", ".log", ".nc", ".gcode", ".json", ".xml"}:
        return raw.decode("utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        return BeautifulSoup(raw.decode("utf-8", errors="ignore"), "html.parser").get_text("\n")
    if suffix == ".pdf":
        if PdfReader is None:
            raise RuntimeError("ثبت pypdf لقراءة ملفات PDF")
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix in {".docx", ".doc"}:
        if docx2txt is None:
            raise RuntimeError("ثبت docx2txt لقراءة ملفات Word")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            return docx2txt.process(tmp_path) or ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    if suffix in {".csv"}:
        return pd.read_csv(io.BytesIO(raw)).to_csv(index=False)
    if suffix in {".xlsx", ".xls"}:
        sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
        return "\n\n".join(f"Sheet: {name}\n{df.to_csv(index=False)}" for name, df in sheets.items())
    return raw.decode("utf-8", errors="ignore")


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> List[str]:
    clean = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    chunks = []
    start = 0
    while start < len(clean):
        end = min(start + chunk_size, len(clean))
        chunks.append(clean[start:end])
        start = max(end - overlap, end) if end == len(clean) else end - overlap
    return [c for c in chunks if len(c.strip()) > 30]


def embed_texts(client: OpenAI, texts: List[str]) -> List[List[float]]:
    model = get_setting("embedding_model", "text-embedding-3-small")
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def save_file_record(file_id: str, filename: str, namespace: str, chunks: int, user_id: str) -> None:
    with sqlite3.connect(LOCAL_DB) as con:
        con.execute(
            "INSERT OR REPLACE INTO files(id, filename, namespace, chunks, uploaded_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, filename, namespace, chunks, user_id, datetime.utcnow().isoformat()),
        )
        con.commit()


def list_files() -> List[Dict[str, Any]]:
    with sqlite3.connect(LOCAL_DB) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_file_record(file_id: str) -> None:
    with sqlite3.connect(LOCAL_DB) as con:
        con.execute("DELETE FROM files WHERE id=?", (file_id,))
        con.commit()


def index_uploaded_file(uploaded_file, namespace: str, user_id: str) -> Tuple[str, int]:
    client = get_openai_client()
    index = get_pinecone_index()
    if not client:
        raise RuntimeError("حط OpenAI API key في الإعدادات الأول")
    if index is None:
        raise RuntimeError("حط Pinecone API key واسم index في الإعدادات الأول")
    file_id = str(uuid.uuid4())
    text = extract_text(uploaded_file)
    chunks = chunk_text(text)
    if not chunks:
        raise RuntimeError("الملف ماطلعش منه نص قابل للفهرسة")
    vectors = []
    batch_size = 64
    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start : batch_start + batch_size]
        embeddings = embed_texts(client, batch)
        for offset, (chunk, vector) in enumerate(zip(batch, embeddings)):
            chunk_no = batch_start + offset
            vectors.append(
                {
                    "id": f"{file_id}-{chunk_no}",
                    "values": vector,
                    "metadata": {
                        "file_id": file_id,
                        "filename": uploaded_file.name,
                        "chunk": chunk_no,
                        "text": chunk[:4000],
                    },
                }
            )
    for batch_start in range(0, len(vectors), 100):
        index.upsert(vectors=vectors[batch_start : batch_start + 100], namespace=namespace)
    (UPLOAD_DIR / f"{file_id}_{uploaded_file.name}").write_bytes(uploaded_file.getvalue())
    save_file_record(file_id, uploaded_file.name, namespace, len(chunks), user_id)
    return file_id, len(chunks)


def delete_indexed_file(file_id: str, namespace: str) -> None:
    index = get_pinecone_index()
    if index is not None:
        index.delete(filter={"file_id": {"$eq": file_id}}, namespace=namespace)
    for path in UPLOAD_DIR.glob(f"{file_id}_*"):
        path.unlink(missing_ok=True)
    delete_file_record(file_id)


def retrieve_context(question: str, namespace: str, top_k: int) -> Tuple[str, List[Dict[str, Any]]]:
    client = get_openai_client()
    index = get_pinecone_index()
    if not client or index is None:
        return "", []
    vector = embed_texts(client, [question])[0]
    result = index.query(vector=vector, top_k=top_k, namespace=namespace, include_metadata=True)
    matches = result.get("matches", []) if isinstance(result, dict) else result.matches
    sources = []
    blocks = []
    for match in matches:
        meta = match.get("metadata", {}) if isinstance(match, dict) else match.metadata
        score = match.get("score", 0) if isinstance(match, dict) else match.score
        text = meta.get("text", "")
        filename = meta.get("filename", "ملف")
        if text:
            blocks.append(f"المصدر: {filename}\n{text}")
            sources.append({"filename": filename, "score": score, "file_id": meta.get("file_id")})
    return "\n\n---\n\n".join(blocks), sources


def ask_llm(question: str, namespace: str) -> Tuple[str, List[Dict[str, Any]]]:
    client = get_openai_client()
    if not client:
        return "لسه مفتاح OpenAI مش متسجل. افتح الإعدادات وحطه الأول.", []
    top_k = int(get_setting("top_k", "5") or "5")
    context, sources = retrieve_context(question, namespace, top_k)
    prompt = f"""
سؤال العامل:
{question}

معلومات الشركة المسترجعة من الملفات:
{context or "لا توجد ملفات مسترجعة أو Pinecone غير متصل."}

اكتب إجابة عملية بالمصري الصنايعي. خليها مرقمة:
1. التشخيص الأقرب
2. خطوات الفحص
3. الحل
4. السلامة
5. محتاج أعرف إيه لو العطل لسه موجود
"""
    model = get_setting("llm_model", "gpt-5.4-mini")
    response = client.responses.create(
        model=model,
        instructions=get_setting("system_prompt", DEFAULT_SYSTEM_PROMPT),
        input=prompt,
    )
    answer = getattr(response, "output_text", "") or str(response)
    return answer, sources


def speech_to_text(audio_bytes: bytes) -> str:
    client = get_openai_client()
    if not client:
        return ""
    model = get_setting("stt_model", "gpt-4o-mini-transcribe")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as fh:
            transcript = client.audio.transcriptions.create(model=model, file=fh, language="ar")
        return getattr(transcript, "text", "") or str(transcript)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def text_to_speech(text: str) -> Optional[bytes]:
    client = get_openai_client()
    if not client:
        return None
    model = get_setting("tts_model", "gpt-4o-mini-tts")
    voice = get_setting("tts_voice", "ash")
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text[:3500],
        instructions="اتكلم بلهجة مصرية صنايعي ودودة وواضحة، سرعة متوسطة، من غير فصحى تقيلة.",
    )
    return response.read()


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <small>CNC • COMPRESSORS • FIELD RAG</small>
          <h1>مساعد الورشة الذكي بالصوت</h1>
          <div class="caption">تشخيص أعطال، تعليمات صيانة، ورفع معرفة الشركة للعامل بلغة بسيطة وصوت واضح.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def login_view() -> None:
    render_hero()
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("دخول")
    user_id = st.text_input("كود العامل أو المدير", value="admin")
    pin = st.text_input("PIN", type="password", value="")
    if st.button("دخول", use_container_width=True):
        user = authenticate(user_id.strip(), pin.strip())
        if user:
            st.session_state.user = user
            st.rerun()
        st.error("الكود أو PIN غلط")
    st.caption("أول تشغيل: admin / 1234، غيره من صفحة المستخدمين.")
    st.markdown("</div>", unsafe_allow_html=True)


def sidebar_nav() -> str:
    user = st.session_state.get("user", {})
    st.sidebar.markdown(f"### {user.get('name', 'مستخدم')}")
    st.sidebar.caption(f"الدور: {user.get('role', 'worker')}")
    pages = []
    if can("can_chat"):
        pages.append("الشات الصوتي")
    if can("can_upload"):
        pages.append("رفع الداتا")
    if can("can_settings"):
        pages.append("الإعدادات")
    if can("can_users"):
        pages.append("المستخدمين")
    choice = st.sidebar.radio("النوافذ", pages, label_visibility="collapsed")
    if st.sidebar.button("خروج", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    return choice


def render_metrics() -> None:
    files = list_files()
    chunks = sum(int(f["chunks"]) for f in files)
    st.markdown(
        f"""
        <div class="metric-grid">
          <div class="metric-tile"><b>{len(files)}</b><span>ملفات معرفة</span></div>
          <div class="metric-tile"><b>{chunks}</b><span>قطع مفهرسة</span></div>
          <div class="metric-tile"><b>{get_setting("pinecone_index", "cnc-rag")}</b><span>Pinecone index</span></div>
          <div class="metric-tile"><b>{get_setting("llm_model", "gpt-5.4-mini")}</b><span>موديل الرد</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def chat_page() -> None:
    render_hero()
    render_metrics()
    namespace = get_setting("pinecone_namespace", "factory")
    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("اتكلم أو اكتب المشكلة")
    col1, col2 = st.columns([1, 1])
    with col1:
        audio = mic_recorder(
            start_prompt="سجل المشكلة",
            stop_prompt="وقف التسجيل",
            just_once=True,
            use_container_width=True,
            key="voice_recorder",
        )
    with col2:
        question = st.text_area("اكتب المشكلة لو مش هتسجل صوت", height=118, placeholder="مثال: الكومبروسر بيفصل overload بعد عشر دقايق...")

    spoken_text = ""
    if audio and audio.get("bytes"):
        with st.spinner("بفك التسجيل العربي..."):
            spoken_text = speech_to_text(audio["bytes"])
        if spoken_text:
            st.info(f"النص اللي اتسمع: {spoken_text}")
            question = spoken_text

    submit = st.button("اسأل المساعد", use_container_width=True)
    if submit and question.strip():
        st.session_state.messages.append({"role": "user", "text": question.strip()})
        with st.spinner("براجع ملفات الشركة وبجهز رد عملي..."):
            answer, sources = ask_llm(question.strip(), namespace)
        st.session_state.messages.append({"role": "assistant", "text": answer, "sources": sources})
        if get_setting("auto_tts", "1") == "1":
            try:
                audio_bytes = text_to_speech(answer)
                if audio_bytes:
                    st.audio(audio_bytes, format="audio/mp3")
            except Exception as exc:
                st.warning(f"الرد الصوتي تعطل: {exc}")

    for msg in st.session_state.messages[-10:]:
        klass = "chat-user" if msg["role"] == "user" else "chat-ai"
        label = "العامل" if msg["role"] == "user" else "المساعد"
        st.markdown(f'<div class="{klass}"><b>{label}</b><br>{msg["text"]}</div>', unsafe_allow_html=True)
        if msg.get("sources"):
            chips = "".join(
                f'<span class="source-chip">{s["filename"]} • {float(s.get("score", 0)):.2f}</span>'
                for s in msg["sources"]
            )
            st.markdown(chips, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def upload_page() -> None:
    render_hero()
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("رفع ملفات المعرفة")
    namespace = st.text_input("Namespace", value=get_setting("pinecone_namespace", "factory"))
    files = st.file_uploader(
        "ارفع PDF / Word / Excel / CSV / TXT / HTML / NC / G-code",
        accept_multiple_files=True,
        type=["pdf", "docx", "doc", "xlsx", "xls", "csv", "txt", "md", "html", "htm", "log", "nc", "gcode", "json", "xml"],
    )
    if st.button("فهرسة الملفات", use_container_width=True, disabled=not files):
        set_setting("pinecone_namespace", namespace)
        for f in files:
            with st.spinner(f"بفهرس {f.name}..."):
                try:
                    file_id, chunks = index_uploaded_file(f, namespace, st.session_state.user["id"])
                    st.success(f"تم رفع {f.name}: {chunks} جزء")
                except Exception as exc:
                    st.error(f"{f.name}: {exc}")

    st.divider()
    st.subheader("الملفات الحالية")
    rows = list_files()
    if rows:
        for row in rows:
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.write(row["filename"])
            c2.write(f'{row["chunks"]} جزء')
            c3.write(row["namespace"])
            if c4.button("حذف", key=f"del_{row['id']}"):
                try:
                    delete_indexed_file(row["id"], row["namespace"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"الحذف تعطل: {exc}")
    else:
        st.info("لسه مفيش ملفات مرفوعة.")
    st.markdown("</div>", unsafe_allow_html=True)


def settings_page() -> None:
    render_hero()
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("الإعدادات والربط")
    with st.form("settings"):
        openai_key = st.text_input("OpenAI API Key", value=get_setting("openai_api_key", ""), type="password")
        pinecone_key = st.text_input("Pinecone API Key", value=get_setting("pinecone_api_key", ""), type="password")
        firebase_json = st.text_area("Firebase service account JSON", value=get_setting("firebase_service_account_json", ""), height=120)
        c1, c2, c3 = st.columns(3)
        llm_model = c1.text_input("LLM model", value=get_setting("llm_model", "gpt-5.4-mini"))
        embedding_model = c2.text_input("Embedding model", value=get_setting("embedding_model", "text-embedding-3-small"))
        embedding_dimension = c3.text_input("Embedding dimension", value=get_setting("embedding_dimension", "1536"))
        c4, c5, c6 = st.columns(3)
        stt_model = c4.text_input("Speech-to-text model", value=get_setting("stt_model", "gpt-4o-mini-transcribe"))
        tts_model = c5.text_input("Text-to-speech model", value=get_setting("tts_model", "gpt-4o-mini-tts"))
        tts_voice = c6.text_input("Voice", value=get_setting("tts_voice", "ash"))
        c7, c8, c9 = st.columns(3)
        pinecone_index = c7.text_input("Pinecone index", value=get_setting("pinecone_index", "cnc-rag"))
        pinecone_cloud = c8.text_input("Cloud", value=get_setting("pinecone_cloud", "aws"))
        pinecone_region = c9.text_input("Region", value=get_setting("pinecone_region", "us-east-1"))
        namespace = st.text_input("Default namespace", value=get_setting("pinecone_namespace", "factory"))
        top_k = st.slider("عدد المصادر المسترجعة", min_value=1, max_value=12, value=int(get_setting("top_k", "5") or "5"))
        auto_tts = st.checkbox("تشغيل الرد الصوتي تلقائي", value=get_setting("auto_tts", "1") == "1")
        system_prompt = st.text_area("شخصية وتعليمات المساعد", value=get_setting("system_prompt", DEFAULT_SYSTEM_PROMPT), height=190)
        saved = st.form_submit_button("حفظ الإعدادات", use_container_width=True)
    if saved:
        pairs = {
            "openai_api_key": openai_key,
            "pinecone_api_key": pinecone_key,
            "firebase_service_account_json": firebase_json,
            "llm_model": llm_model,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "stt_model": stt_model,
            "tts_model": tts_model,
            "tts_voice": tts_voice,
            "pinecone_index": pinecone_index,
            "pinecone_cloud": pinecone_cloud,
            "pinecone_region": pinecone_region,
            "pinecone_namespace": namespace,
            "top_k": str(top_k),
            "auto_tts": "1" if auto_tts else "0",
            "system_prompt": system_prompt,
        }
        for key, value in pairs.items():
            set_setting(key, value)
        st.success("اتحفظت.")

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'OpenAI: <span class="{"status-ok" if get_openai_client() else "status-bad"}">{"متوصل" if get_openai_client() else "ناقص"}</span>', unsafe_allow_html=True)
    c2.markdown(f'Pinecone: <span class="{"status-ok" if effective_secret("PINECONE_API_KEY", "pinecone_api_key") else "status-bad"}">{"مفتاح موجود" if effective_secret("PINECONE_API_KEY", "pinecone_api_key") else "ناقص"}</span>', unsafe_allow_html=True)
    c3.markdown(f'Firebase: <span class="{"status-ok" if get_setting("firebase_service_account_json", "") else "status-bad"}">{"مجهز" if get_setting("firebase_service_account_json", "") else "اختياري"}</span>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def users_page() -> None:
    render_hero()
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("إدارة العمال والصلاحيات")
    with st.form("user_form"):
        c1, c2, c3, c4 = st.columns(4)
        user_id = c1.text_input("كود المستخدم")
        name = c2.text_input("الاسم")
        pin = c3.text_input("PIN", type="password")
        role = c4.selectbox("الدور", ["worker", "supervisor", "admin"])
        p1, p2, p3, p4 = st.columns(4)
        can_chat = p1.checkbox("الشات", value=True)
        can_upload = p2.checkbox("رفع الداتا")
        can_settings = p3.checkbox("الإعدادات")
        can_users = p4.checkbox("المستخدمين")
        add = st.form_submit_button("حفظ المستخدم", use_container_width=True)
    if add:
        if user_id and name and pin:
            user = {
                "id": user_id.strip(),
                "name": name.strip(),
                "pin": pin.strip(),
                "role": role,
                "can_chat": can_chat,
                "can_upload": can_upload,
                "can_settings": can_settings,
                "can_users": can_users,
            }
            upsert_local_user(user)
            db = init_firebase()
            if db:
                db.collection("users").document(user["id"]).set(user)
            st.success("اتحفظ.")
        else:
            st.error("الكود والاسم والـ PIN مطلوبين.")

    rows = list_local_users()
    st.dataframe(pd.DataFrame(rows).drop(columns=["pin"], errors="ignore"), use_container_width=True, hide_index=True)
    delete_id = st.selectbox("حذف مستخدم", [r["id"] for r in rows if r["id"] != "admin"])
    if st.button("حذف المستخدم", use_container_width=True, disabled=not delete_id):
        delete_local_user(delete_id)
        db = init_firebase()
        if db:
            db.collection("users").document(delete_id).delete()
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    init_local_db()
    inject_css()
    if "user" not in st.session_state:
        login_view()
        return
    page = sidebar_nav()
    if page == "الشات الصوتي":
        chat_page()
    elif page == "رفع الداتا":
        upload_page()
    elif page == "الإعدادات":
        settings_page()
    elif page == "المستخدمين":
        users_page()


if __name__ == "__main__":
    main()

