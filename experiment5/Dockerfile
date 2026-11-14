FROM python:3.12-slim
WORKDIR /app/TCMP-300
COPY TCMP-300/requirements-api.txt TCMP-300/requirements-agent.txt TCMP-300/requirements-mysql.txt ./
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements-api.txt
COPY TCMP-300/ ./
EXPOSE 8000
CMD ["uvicorn","api:app","--host","0.0.0.0","--port","8000"]
