FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8080
# FLAG is injected at pod creation time by the Kubernetes scenario (env var)
CMD ["python", "app.py"]
