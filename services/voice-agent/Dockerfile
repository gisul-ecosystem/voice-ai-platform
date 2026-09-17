FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app app

COPY services/voice-agent/requirements.txt .
RUN pip install --only-binary=:all: --requirement requirements.txt

COPY services/voice-agent/ .
RUN chown -R app:app /app /home/app

USER app
EXPOSE 8081

CMD ["python", "aaptor_agent.py", "start"]
