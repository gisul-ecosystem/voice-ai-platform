FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY services/backend-api/requirements.txt .
RUN pip install --requirement requirements.txt

COPY services/backend-api/ .
RUN chown -R app:app /app

USER app
EXPOSE 5554

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5554", "--proxy-headers", "--forwarded-allow-ips=*"]
