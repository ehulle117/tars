FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN apk add --no-cache tzdata && pip install --no-cache-dir -r requirements.txt
COPY . .
ENV MEAD_DB=/data/mead.db
USER 1000:1000
EXPOSE 8770
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8770"]
