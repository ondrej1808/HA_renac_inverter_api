FROM python:3.12-slim
RUN pip install --no-cache-dir "aiohttp>=3.9"
WORKDIR /app
COPY tests/mock_server/server.py /app/server.py
COPY tests/fixtures/renac_api /app/fixtures
EXPOSE 8084
CMD ["python", "/app/server.py"]
