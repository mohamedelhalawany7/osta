FROM python:3.10-slim

WORKDIR /app

# نسخ ملفات المشروع
COPY requirements.txt .

# تسطيب المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الكود
COPY . .

# تشغيل التطبيق (Hugging Face Spaces بيستخدم بورت 7860 افتراضياً)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
