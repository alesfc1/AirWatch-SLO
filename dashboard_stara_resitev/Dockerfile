FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY dashboard/requirements-docker.txt /app/dashboard/requirements-docker.txt
RUN pip install --no-cache-dir -r /app/dashboard/requirements-docker.txt

COPY dashboard /app/dashboard
COPY outputs /app/outputs
COPY shapefiles /app/shapefiles
COPY scripts/import_to_db.py /app/scripts/import_to_db.py

WORKDIR /app/dashboard

CMD ["sh", "-c", "python /app/scripts/import_to_db.py && python app.py"]
