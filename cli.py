
from __future__ import annotations

import json

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

from app.graph import graph  


def main() -> None:
    print("Asistente de inversión inmobiliaria (POC). Escribe 'salir' para terminar.\n")
    while True:
        try:
            user = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in {"salir", "exit", "quit"}:
            break

        state = graph.invoke({"messages": [HumanMessage(content=user)]})

        # Última respuesta del asistente
        ai_msgs = [m for m in state["messages"] if isinstance(m, AIMessage)]
        if ai_msgs:
            print(f"\nAsistente: {ai_msgs[-1].content}\n")

        # Si hubo análisis, mostrar el informe estructurado
        if state.get("report") and "error" not in state["report"]:
            print("--- Informe estructurado ---")
            print(json.dumps(state["report"], ensure_ascii=False, indent=2))
            print("----------------------------\n")


if __name__ == "__main__":
    main()
