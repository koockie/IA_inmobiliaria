"""Groq:
python 04_groq_llm.py
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GROQ_API_KEY")
if not API_KEY:
    raise SystemExit("Falta GROQ_API_KEY en .env")

# Mismo formato que OpenAI: /chat/completions
URL = "https://api.groq.com/openai/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
BODY = {
    "model": "llama-3.3-70b-versatile",
    "messages": [
        {"role": "system", "content": "Eres un asesor inmobiliario chileno, responde breve."},
        {"role": "user", "content": "En una frase: ¿qué hace atractiva a una comuna para invertir?"},
    ],
    "temperature": 0.3,
}

print("Llamando a Groq (llama-3.3-70b-versatile)...\n")
resp = httpx.post(URL, json=BODY, headers=HEADERS, timeout=30)
resp.raise_for_status()
data = resp.json()

out_dir = Path(__file__).parent / "outputs"
out_dir.mkdir(exist_ok=True)
(out_dir / "groq.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)

print("== RESPUESTA DEL MODELO ==")
print(data["choices"][0]["message"]["content"])
print("\n== Tokens usados ==", data.get("usage"))
print("== JSON COMPLETO guardado en apis/outputs/groq.json ==")
