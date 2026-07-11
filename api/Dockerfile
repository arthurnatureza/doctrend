FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY doctrend_ingestor ./doctrend_ingestor

CMD ["python", "-m", "doctrend_ingestor.scheduler"]
