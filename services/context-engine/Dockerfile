FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY services/context-engine/requirements.txt .
RUN pip install --only-binary=:all: --requirement requirements.txt

COPY services/context-engine/ .
RUN chown -R app:app /app

USER app
EXPOSE 5555

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5555"]
