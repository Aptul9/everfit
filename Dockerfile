FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin fit
WORKDIR /app
COPY app/server ./server
COPY app/public ./public
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 \
  CMD ["python", "-c", "import sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8080/api/health', timeout=3).status == 200 else 1)"]
CMD ["python", "-u", "server/server.py", "--root", "/app/public", "--data", "/data", "--host", "0.0.0.0", "--port", "8080"]
