FROM python:3.12-slim

# Sin .pyc y con salida sin buffer, que es lo que quieres en los logs de Docker.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RC_DATA_DIR=/data

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# El usuario lo fija docker-compose (user: "1001:1001", el uid de rcraft en la Pi)
# para que los ficheros del volumen pertenezcan a quien debe y no a root.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
