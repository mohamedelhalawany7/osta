import base64
import hashlib
import io
import json
import os
import secrets
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import bcrypt
import firebase_admin
import google.generativeai as genai
import streamlit as st
from anthropic import Anthropic
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from openai import OpenAI
from pinecone import Pinecone
from pypdf import PdfReader

load_dotenv()


DEFAULT_PROMPT = """أنت 'الأسطى بلية'، أقدم وأشطر صنايعي ومهندس في ورشة ميكانيكا وصيانة ضواغط هواء ومجففات في مصر.
العمال اللي بيكلموك صنايعية على قدهم ومابيعرفوش يقرأوا ويكتبوا، عشان كده:
1. اتكلم معاهم بلهجة مصرية بلدي صميمة، زي الصنايعية الكبار في الورش.
2. اشرح المشكلة وحلها ببساطة جدا وبدون مصطلحات إنجليزي مكلكعة.
3. خليك جدع ومشجع وبتحل المشاكل بخطوات عملية 1، 2، 3.
4. لو بعتولك صورة، ركز فيها كويس وقولهم فيها إيه بالظبط وإيه اللي بايظ وكيفية صيانته.
5. اعتمد في إجاباتك على معلومات الكتالوجات المرفقة، وضيف عليها خبرتك كأسطى كبير في السوق.
"""

TECHNICAL_KEYWORDS = [
    "ضاغط",
    "مجفف",
    "فلتر",
    "أويل",
    "بيلت",
    "عطل",
    "ضغط",
    "بارد",
    "حرارة",
    "زيت",
    "صيانة",
    "ماكينة",
    "موتور",
    "صوت",
    "مشكلة",
    "صورة",
    "الحل",
    "خربان",
    "بايظ",
    "مكسور",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@st.cache_resource
def parse_firebase_credentials(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        raise RuntimeError("FIREBASE_CREDENTIALS is missing.")

    if os.path.exists(raw):
        with open(raw, "r", encoding="utf-8") as cred_file:
            return json.load(cred_file)

    candidates = [raw]
    if '"private_key"' in raw:
        prefix, sep, suffix = raw.partition('"private_key"')
        key_name, colon, rest = suffix.partition(":")
        first_quote = rest.find('"')
        end_marker = rest.find('",', first_quote + 1)
        if end_marker == -1:
            end_marker = rest.find('"\n}', first_quote + 1)
        if first_quote != -1 and end_marker != -1:
            key_value = rest[first_quote + 1 : end_marker]
            fixed_value = key_value.replace("\r\n", "\\n").replace("\n", "\\n")
            fixed_rest = rest[: first_quote + 1] + fixed_value + rest[end_marker:]
            candidates.append(prefix + sep + key_name + colon + fixed_rest)

    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        candidates.append(decoded)
    except Exception:
        pass

    last_error = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "private_key" in data:
                data["private_key"] = data["private_key"].replace("\\n", "\n")
            return data
        except json.JSONDecodeError as exc:
            last_error = exc

    raise RuntimeError(
        "FIREBASE_CREDENTIALS must be valid JSON, base64 JSON, or a path to the service-account JSON file. "
        f"Parser error: {last_error}"
    )


@st.cache_resource
def get_db():
    raw = os.getenv("FIREBASE_CREDENTIALS", "")
    if not raw:
        raw = st.secrets.get("FIREBASE_CREDENTIALS", "") if hasattr(st, "secrets") else ""

    cred_dict = parse_firebase_credentials(raw)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(cred_dict))
    return firestore.client()


@st.cache_resource
def get_cipher():
    key = os.getenv("FERNET_KEY", "")
    if not key:
        key = st.secrets.get("FERNET_KEY", "") if hasattr(st, "secrets") else ""
    if not key:
        key = Fernet.generate_key().decode()
        st.warning("FERNET_KEY غير موجود. تم إنشاء مفتاح مؤقت، ضع مفتاحا ثابتا في .env قبل الإنتاج.")
    return Fernet(key.encode())


def encrypt_val(value: str) -> str:
    return get_cipher().encrypt(value.encode()).decode() if value else ""


def decrypt_val(value: str) -> str:
    if not value:
        return ""
    try:
        return get_cipher().decrypt(value.encode()).decode()
    except Exception:
        return value


def password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_id() -> str:
    return str(uuid.uuid4())


def ensure_seed_data(db) -> None:
    tenants = list(db.collection("tenants").limit(1).stream())
    if tenants:
        return

    tenant_id = create_id()
    tenant_name = os.getenv("DEFAULT_TENANT_NAME", "ورشة الصيانة والتصنيع")
    db.collection("tenants").document(tenant_id).set(
        {
            "name": tenant_name,
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "api_base_url": "",
            "openai_api_key": "",
            "anthropic_api_key": "",
            "google_api_key": "",
            "pinecone_api_key": "",
            "pinecone_index": "",
            "workshop_prompt": DEFAULT_PROMPT,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )

    users = [
        (
            os.getenv("DEFAULT_ADMIN_USERNAME", "admin"),
            os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123"),
            "admin",
        ),
        (
            os.getenv("DEFAULT_WORKER_USERNAME", "worker"),
            os.getenv("DEFAULT_WORKER_PASSWORD", "1234"),
            "worker",
        ),
    ]
    for username, password, role in users:
        db.collection("users").document(create_id()).set(
            {
                "username": username,
                "hashed_password": password_hash(password),
                "role": role,
                "tenant_id": tenant_id,
                "created_at": utc_now(),
            }
        )


def get_user_by_username(db, username: str) -> Optional[Dict]:
    docs = db.collection("users").where("username", "==", username).limit(1).stream()
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return None


def authenticate(db, username: str, password: str) -> Optional[Dict]:
    user = get_user_by_username(db, username.strip())
    if not user or not verify_password(password, user["hashed_password"]):
        return None
    tenant = get_tenant(db, user["tenant_id"])
    user["tenant"] = tenant
    return user


def get_tenant(db, tenant_id: str) -> Dict:
    doc = db.collection("tenants").document(tenant_id).get()
    if not doc.exists:
        raise RuntimeError("Tenant not found.")
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def save_tenant_settings(db, tenant_id: str, data: Dict) -> None:
    encrypted_keys = {
        key: encrypt_val(value)
        for key, value in data.items()
        if key.endswith("_api_key") and value
    }
    update = {**data, **encrypted_keys, "updated_at": utc_now()}
    db.collection("tenants").document(tenant_id).update(update)


def list_sessions(db, tenant_id: str, limit: int = 30) -> List[Dict]:
    query = (
        db.collection("chat_sessions")
        .where("tenant_id", "==", tenant_id)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [with_id(doc) for doc in query.stream()]


def get_or_create_session(db, tenant_id: str, user_id: str, session_id: Optional[str] = None) -> Dict:
    if session_id:
        doc = db.collection("chat_sessions").document(session_id).get()
        if doc.exists:
            return with_id(doc)

    session_id = create_id()
    data = {
        "title": "محادثة جديدة",
        "tenant_id": tenant_id,
        "user_id": user_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    db.collection("chat_sessions").document(session_id).set(data)
    data["id"] = session_id
    return data


def rename_session_from_message(db, session_id: str, current_title: str, message: str) -> None:
    if current_title != "محادثة جديدة":
        return
    title = " ".join((message or "محادثة صوتية").split()[:4])
    db.collection("chat_sessions").document(session_id).update(
        {"title": title or "محادثة جديدة", "updated_at": utc_now()}
    )


def save_message(db, tenant_id: str, session_id: str, role: str, content: str) -> None:
    clean = content[:4000] if "data:image" not in content else "[صورة مرفقة]"
    db.collection("conversation_history").document(create_id()).set(
        {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "role": role,
            "content": clean,
            "created_at": utc_now(),
        }
    )
    db.collection("chat_sessions").document(session_id).update({"updated_at": utc_now()})


def load_messages(db, session_id: str, limit: int = 100) -> List[Dict]:
    query = (
        db.collection("conversation_history")
        .where("session_id", "==", session_id)
        .order_by("created_at")
        .limit(limit)
    )
    return [with_id(doc) for doc in query.stream()]


def history_text(db, session_id: str, limit: int = 6) -> str:
    messages = load_messages(db, session_id, limit=limit)
    return "\n".join(f"{m['role']}: {m['content']}" for m in messages[-limit:])


def with_id(doc) -> Dict:
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def is_technical_query(message: str) -> bool:
    if not message:
        return True
    return any(word in message for word in TECHNICAL_KEYWORDS)


def extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def chunk_text(text: str, chunk_size: int = 1100, overlap: int = 180) -> List[str]:
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def openai_client(api_key: str, base_url: str = "") -> OpenAI:
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def embed_texts(openai_key: str, texts: List[str]) -> List[List[float]]:
    client = openai_client(openai_key)
    result = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [item.embedding for item in result.data]


def pinecone_index(api_key: str, index_name: str):
    return Pinecone(api_key=api_key).Index(index_name)


def upsert_document_to_pinecone(
    db,
    tenant: Dict,
    filename: str,
    file_bytes: bytes,
) -> Tuple[int, str]:
    openai_key = decrypt_val(tenant.get("openai_api_key", ""))
    pinecone_key = decrypt_val(tenant.get("pinecone_api_key", ""))
    index_name = tenant.get("pinecone_index", "")
    if not openai_key or not pinecone_key or not index_name:
        raise RuntimeError("OpenAI key, Pinecone key, and Pinecone index are required.")

    text = extract_pdf_text(file_bytes)
    chunks = chunk_text(text)
    if not chunks:
        raise RuntimeError("لم يتم استخراج نص من الملف.")

    vectors = embed_texts(openai_key, chunks)
    index = pinecone_index(pinecone_key, index_name)
    namespace = f"tenant_{tenant['id']}"
    doc_id = create_id()
    pinecone_vectors = []
    for i, (chunk, values) in enumerate(zip(chunks, vectors)):
        stable_id = hashlib.sha256(f"{doc_id}:{i}:{filename}".encode()).hexdigest()
        pinecone_vectors.append(
            {
                "id": stable_id,
                "values": values,
                "metadata": {"text": chunk, "filename": filename, "tenant_id": tenant["id"]},
            }
        )
    index.upsert(vectors=pinecone_vectors, namespace=namespace)
    db.collection("uploaded_documents").document(doc_id).set(
        {
            "tenant_id": tenant["id"],
            "filename": filename,
            "chunks": len(chunks),
            "created_at": utc_now(),
        }
    )
    return len(chunks), doc_id


def rag_context(tenant: Dict, message: str, k: int = 3) -> str:
    if not is_technical_query(message):
        return ""
    openai_key = decrypt_val(tenant.get("openai_api_key", ""))
    pinecone_key = decrypt_val(tenant.get("pinecone_api_key", ""))
    index_name = tenant.get("pinecone_index", "")
    if not openai_key or not pinecone_key or not index_name:
        return ""

    vector = embed_texts(openai_key, [message or "صيانة ضاغط هواء"])[0]
    index = pinecone_index(pinecone_key, index_name)
    result = index.query(
        vector=vector,
        top_k=k,
        namespace=f"tenant_{tenant['id']}",
        include_metadata=True,
    )
    matches = result.get("matches", []) if isinstance(result, dict) else result.matches
    texts = []
    for match in matches:
        metadata = match.get("metadata", {}) if isinstance(match, dict) else match.metadata
        if metadata and metadata.get("text"):
            texts.append(metadata["text"])
    return "\n\n".join(texts)


def image_to_data_url(uploaded_file) -> Optional[str]:
    if not uploaded_file:
        return None
    data = uploaded_file.getvalue()
    mime = uploaded_file.type or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def transcribe_audio(openai_key: str, audio_bytes: bytes, suffix: str = ".wav") -> str:
    client = openai_client(openai_key)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp.write(audio_bytes)
        temp_path = temp.name
    try:
        with open(temp_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio, language="ar")
            return transcript.text
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def build_system_prompt(tenant: Dict, history: str, context: str) -> str:
    return f"""{tenant.get('workshop_prompt') or DEFAULT_PROMPT}

تاريخ المحادثة السابقة:
{history}

معلومات فنية من الكتالوجات:
{context}
"""


def stream_openai(tenant: Dict, system_prompt: str, message: str, image_url: Optional[str]) -> Iterable[str]:
    key = decrypt_val(tenant.get("openai_api_key", ""))
    if not key:
        raise RuntimeError("مفتاح OpenAI مفقود.")
    client = openai_client(key, tenant.get("api_base_url", ""))
    user_content = [{"type": "text", "text": message}]
    if image_url:
        user_content.append({"type": "image_url", "image_url": {"url": image_url}})
    stream = client.chat.completions.create(
        model=tenant.get("llm_model") or "gpt-4o-mini",
        temperature=0.3,
        stream=True,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def stream_anthropic(tenant: Dict, system_prompt: str, message: str) -> Iterable[str]:
    key = decrypt_val(tenant.get("anthropic_api_key", ""))
    if not key:
        raise RuntimeError("مفتاح Anthropic مفقود.")
    client = Anthropic(api_key=key)
    with client.messages.stream(
        model=tenant.get("llm_model") or "claude-3-5-haiku-latest",
        max_tokens=1600,
        temperature=0.3,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def stream_google(tenant: Dict, system_prompt: str, message: str, image_url: Optional[str]) -> Iterable[str]:
    key = decrypt_val(tenant.get("google_api_key", ""))
    if not key:
        raise RuntimeError("مفتاح Google Gemini مفقود.")
    genai.configure(api_key=key)
    model = genai.GenerativeModel(tenant.get("llm_model") or "gemini-1.5-flash")
    parts = [system_prompt, message]
    if image_url:
        header, encoded = image_url.split(",", 1)
        mime = header.replace("data:", "").replace(";base64", "")
        parts.append({"mime_type": mime, "data": base64.b64decode(encoded)})
    response = model.generate_content(parts, stream=True)
    for chunk in response:
        if chunk.text:
            yield chunk.text


def stream_llm(tenant: Dict, system_prompt: str, message: str, image_url: Optional[str]) -> Iterable[str]:
    provider = tenant.get("llm_provider", "openai")
    if provider == "openai" or provider == "custom":
        return stream_openai(tenant, system_prompt, message, image_url)
    if provider == "anthropic":
        return stream_anthropic(tenant, system_prompt, message)
    if provider == "google":
        return stream_google(tenant, system_prompt, message, image_url)
    raise RuntimeError("مزود الخدمة المختار غير مدعوم.")


def generate_tts(tenant: Dict, text: str) -> bytes:
    key = decrypt_val(tenant.get("openai_api_key", ""))
    if not key:
        raise RuntimeError("مفتاح OpenAI مطلوب لتوليد الصوت.")
    audio = openai_client(key).audio.speech.create(model="tts-1", voice="onyx", input=text[:4000])
    return audio.read()


def analyze_machine_issues(db, tenant: Dict) -> Optional[str]:
    openai_key = decrypt_val(tenant.get("openai_api_key", ""))
    if not openai_key:
        return None

    cutoff = utc_now() - timedelta(days=30)
    query = (
        db.collection("conversation_history")
        .where("tenant_id", "==", tenant["id"])
        .where("created_at", ">=", cutoff)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(500)
    )
    history = [doc.to_dict() for doc in query.stream()]
    if len(history) < 10:
        return None

    text_log = "\n".join(f"{row['role']}: {row['content']}" for row in history)
    prompt = """بصفتك مهندس صيانة ذكي، حلل سجل محادثات العمال خلال الشهر الماضي.
هل يوجد عطل في ماكينة معينة أو ضاغط هواء معين تكرر السؤال عنه أكثر من مرتين؟
إذا وجدت تكرارا يعطي مؤشرا على مشكلة مزمنة، اكتب تنبيها واحدا مباشرا وموجزا.
إذا كانت الأمور طبيعية فاكتب فقط: لا يوجد"""
    client = openai_client(openai_key)
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text_log}],
    )
    content = res.choices[0].message.content or ""
    if "لا يوجد" in content:
        return None
    db.collection("alerts").document(create_id()).set(
        {"tenant_id": tenant["id"], "message": f"تنبيه ذكي: {content}", "created_at": utc_now()}
    )
    return content


def list_alerts(db, tenant_id: str, limit: int = 20) -> List[Dict]:
    query = (
        db.collection("alerts")
        .where("tenant_id", "==", tenant_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [with_id(doc) for doc in query.stream()]


def list_documents(db, tenant_id: str, limit: int = 50) -> List[Dict]:
    query = (
        db.collection("uploaded_documents")
        .where("tenant_id", "==", tenant_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [with_id(doc) for doc in query.stream()]

# =====================================================================
# Streamlit UI
# =====================================================================

st.set_page_config(page_title="الأسطى بلية", page_icon="🛠️", layout="wide")

st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; }
    .stChatMessage { text-align: right; }
    [data-testid="stSidebar"] { direction: rtl; }
    textarea, input { direction: rtl; }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state() -> None:
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("last_answer", "")


def login_view(db) -> None:
    st.title("الأسطى بلية")
    st.caption("مساعد الورشة الذكي - Streamlit + Firebase + Pinecone")

    with st.form("login_form"):
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")
        submitted = st.form_submit_button("دخول", use_container_width=True)

    if submitted:
        user = authenticate(db, username, password)
        if not user:
            st.error("اسم المستخدم أو كلمة المرور غير صحيح.")
            return
        st.session_state.user = user
        st.session_state.session_id = None
        st.rerun()


def sidebar(db):
    user = st.session_state.user
    tenant = get_tenant(db, user["tenant_id"])
    user["tenant"] = tenant

    st.sidebar.title("الورشة")
    st.sidebar.write(tenant["name"])
    st.sidebar.caption(f"المستخدم: {user['username']} - {user['role']}")

    if st.sidebar.button("محادثة جديدة", use_container_width=True):
        session = get_or_create_session(db, tenant["id"], user["id"])
        st.session_state.session_id = session["id"]
        st.rerun()

    sessions = list_sessions(db, tenant["id"])
    options = {s["title"]: s["id"] for s in sessions}
    if sessions:
        labels = [s["title"] for s in sessions]
        current_label = next((s["title"] for s in sessions if s["id"] == st.session_state.session_id), labels[0])
        selected = st.sidebar.selectbox("المحادثات", labels, index=labels.index(current_label))
        st.session_state.session_id = options[selected]

    if st.sidebar.button("خروج", use_container_width=True):
        st.session_state.user = None
        st.session_state.session_id = None
        st.rerun()

    return tenant


def chat_page(db, tenant):
    user = st.session_state.user
    session = get_or_create_session(db, tenant["id"], user["id"], st.session_state.session_id)
    st.session_state.session_id = session["id"]

    st.header("المساعد الفني")
    st.caption("اسأل عن عطل، ارفع صورة، أو استخدم الصوت لو متاح في Streamlit عندك.")

    for msg in load_messages(db, session["id"]):
        role = "assistant" if msg["role"] == "AI" else "user"
        with st.chat_message(role):
            st.write(msg["content"])

    cols = st.columns([2, 1])
    with cols[0]:
        image_file = st.file_uploader("صورة من الورشة", type=["png", "jpg", "jpeg", "webp"])
    with cols[1]:
        audio_file = None
        if hasattr(st, "audio_input"):
            audio_file = st.audio_input("رسالة صوتية")
        else:
            st.info("نسخة Streamlit الحالية لا تدعم st.audio_input.")

    prompt = st.chat_input("اكتب المشكلة هنا يا هندسة")
    if not prompt and audio_file:
        openai_key = decrypt_val(tenant.get("openai_api_key", ""))
        if openai_key:
            with st.spinner("بفك الرسالة الصوتية..."):
                prompt = transcribe_audio(openai_key, audio_file.getvalue(), ".wav")
        else:
            st.error("الصوت يحتاج مفتاح OpenAI للتفريغ.")

    if prompt or image_file:
        image_url = image_to_data_url(image_file)
        message = prompt or "بص على الصورة دي وقولي الحل إيه؟"
        rename_session_from_message(db, session["id"], session["title"], message)
        save_message(db, tenant["id"], session["id"], "Worker", message)

        with st.chat_message("user"):
            st.write(message)
            if image_file:
                st.image(image_file)

        with st.chat_message("assistant"):
            try:
                context = rag_context(tenant, message)
                system_prompt = f"{tenant.get('workshop_prompt') or DEFAULT_PROMPT}\n\n"
                system_prompt += f"تاريخ المحادثة السابقة:\n{history_text(db, session['id'], 6)}\n\n"
                system_prompt += f"معلومات فنية من الكتالوجات:\n{context}"
                chunks: List[str] = []

                def generator():
                    for part in stream_llm(tenant, system_prompt, message, image_url):
                        chunks.append(part)
                        yield part

                st.write_stream(generator())
                answer = "".join(chunks)
                st.session_state.last_answer = answer
                save_message(db, tenant["id"], session["id"], "AI", answer)
            except Exception as exc:
                st.error(f"حصل عطل في الرد: {exc}")

    if st.session_state.last_answer:
        if st.button("اسمع آخر رد"):
            try:
                audio = generate_tts(tenant, st.session_state.last_answer)
                st.audio(audio, format="audio/mp3")
            except Exception as exc:
                st.error(f"تعذر توليد الصوت: {exc}")


def documents_page(db, tenant):
    st.header("كتالوجات الورشة")
    st.caption("ارفع ملفات PDF ليتم تخزينها في Pinecone وربطها بإجابات الشات.")

    uploaded = st.file_uploader("PDF", type=["pdf"], accept_multiple_files=True)
    if uploaded and st.button("رفع وفهرسة", use_container_width=True):
        for file in uploaded:
            with st.spinner(f"بفهرس {file.name}..."):
                try:
                    chunks, _ = upsert_document_to_pinecone(db, tenant, file.name, file.getvalue())
                    st.success(f"تم فهرسة {file.name} بعدد {chunks} جزء.")
                except Exception as exc:
                    st.error(f"{file.name}: {exc}")

    st.subheader("الملفات المرفوعة")
    docs = list_documents(db, tenant["id"])
    if not docs:
        st.info("لا توجد كتالوجات حتى الآن.")
    for doc in docs:
        st.write(f"- {doc['filename']} ({doc.get('chunks', 0)} جزء)")


def alerts_page(db, tenant):
    st.header("التنبيهات")
    if st.button("حلل آخر 30 يوم", use_container_width=True):
        with st.spinner("بحلل المحادثات..."):
            result = analyze_machine_issues(db, tenant)
            if result:
                st.success(result)
            else:
                st.info("لا يوجد تكرار واضح أو مفتاح OpenAI غير متاح.")

    alerts = list_alerts(db, tenant["id"])
    if not alerts:
        st.info("لا توجد تنبيهات.")
    for alert in alerts:
        st.warning(alert["message"])


def settings_page(db, tenant):
    st.header("الإعدادات")
    with st.form("settings"):
        name = st.text_input("اسم الورشة", value=tenant.get("name", ""))
        provider = st.selectbox(
            "مزود الذكاء الاصطناعي",
            ["openai", "google", "anthropic", "custom"],
            index=["openai", "google", "anthropic", "custom"].index(tenant.get("llm_provider", "openai")),
        )
        model = st.text_input("الموديل", value=tenant.get("llm_model", "gpt-4o-mini"))
        api_base_url = st.text_input("Base URL اختياري", value=tenant.get("api_base_url", ""))
        openai_key = st.text_input("OpenAI API Key", type="password", placeholder="اتركه فارغا للاحتفاظ بالموجود")
        google_key = st.text_input("Google API Key", type="password", placeholder="اتركه فارغا للاحتفاظ بالموجود")
        anthropic_key = st.text_input("Anthropic API Key", type="password", placeholder="اتركه فارغا للاحتفاظ بالموجود")
        pinecone_key = st.text_input("Pinecone API Key", type="password", placeholder="اتركه فارغا للاحتفاظ بالموجود")
        pinecone_index = st.text_input("Pinecone Index", value=tenant.get("pinecone_index", ""))
        workshop_prompt = st.text_area("Prompt الورشة", value=tenant.get("workshop_prompt", DEFAULT_PROMPT), height=240)
        submitted = st.form_submit_button("حفظ", use_container_width=True)

    if submitted:
        data = {
            "name": name,
            "llm_provider": provider,
            "llm_model": model,
            "api_base_url": api_base_url,
            "pinecone_index": pinecone_index,
            "workshop_prompt": workshop_prompt,
        }
        if openai_key:
            data["openai_api_key"] = openai_key
        if google_key:
            data["google_api_key"] = google_key
        if anthropic_key:
            data["anthropic_api_key"] = anthropic_key
        if pinecone_key:
            data["pinecone_api_key"] = pinecone_key
        save_tenant_settings(db, tenant["id"], data)
        st.success("تم حفظ الإعدادات.")
        st.rerun()


def main():
    init_state()
    try:
        db = get_db()
        ensure_seed_data(db)
    except Exception as exc:
        st.error(f"تعذر الاتصال بـ Firebase: {exc}")
        st.stop()

    if not st.session_state.user:
        login_view(db)
        return

    tenant = sidebar(db)
    if st.session_state.user["role"] == "admin":
        tab_chat, tab_docs, tab_alerts, tab_settings = st.tabs(["الشات", "الكتالوجات", "التنبيهات", "الإعدادات"])
        with tab_chat:
            chat_page(db, tenant)
        with tab_docs:
            documents_page(db, tenant)
        with tab_alerts:
            alerts_page(db, tenant)
        with tab_settings:
            settings_page(db, tenant)
    else:
        chat_page(db, tenant)


if __name__ == "__main__":
    main()

