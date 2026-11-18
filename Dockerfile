FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
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
