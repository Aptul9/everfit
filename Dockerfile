FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin fit
WORKDIR /app
COPY app/server ./server
COPY app/public ./public
USER 10001:10001
EXPOSE 8080
CMD ["python", "-u", "server/server.py", "--root", "/app/public", "--data", "/data", "--host", "0.0.0.0", "--port", "8080"]
