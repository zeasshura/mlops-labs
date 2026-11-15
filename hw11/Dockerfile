FROM docker.io/library/python:3.12.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements-service.txt /app/
RUN pip install --no-cache-dir -r requirements-service.txt
COPY app.py client.py /app/
COPY artifacts /app/artifacts
USER 10001
EXPOSE 8091
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091", "--timeout-graceful-shutdown", "30", "--no-access-log"]
