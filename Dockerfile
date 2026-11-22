# Один образ на монолит, сервис доставки и все consumer'ы: в compose они
# отличаются только командой.
FROM mirror.gcr.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home sirius && mkdir -p receipts && chown sirius receipts
USER sirius

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
