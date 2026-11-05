FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home bot \
    && mkdir -p /app/data \
    && chown -R 10001:10001 /app
COPY --chown=10001:10001 logistika_bot ./logistika_bot
USER 10001:10001
CMD ["python", "-m", "logistika_bot", "run"]
