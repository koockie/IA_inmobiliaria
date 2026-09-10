# Imagen de la API de tasacion inmobiliaria (sirve los dos modelos ML).
#   docker build -t tasacion .
#   docker run -p 8080:8080 tasacion
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# libgomp lo necesita XGBoost para OpenMP; sin el, el import falla en runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

COPY api/ /app/api/
# Los .joblib pesan ~10 MB entre los dos y van dentro de la imagen: la alternativa
# (bajarlos al arrancar) anade un punto de fallo en el arranque a cambio de nada.
COPY modelos/ /app/modelos/

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/salud').status==200 else 1)"

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
