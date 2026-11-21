FROM python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd
WORKDIR /app
COPY requirements.txt .
RUN apk add --no-cache tzdata && pip install --no-cache-dir -r requirements.txt
COPY . .
ENV MEAD_DB=/data/mead.db
USER 1000:1000
EXPOSE 8770
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8770"]
