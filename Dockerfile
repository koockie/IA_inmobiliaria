FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# En DigitalOcean App Platform define las variables de entorno (LLM_PROVIDER=openai,
# LLM_MODEL, OPENAI_API_KEY, TAVILY_API_KEY, NOMINATIM_USER_AGENT).
CMD ["uvicorn", "api:api", "--host", "0.0.0.0", "--port", "8000"]
