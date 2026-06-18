# Métricas de evaluación del agente de IA

Marco de evaluación para medir el rendimiento del agente cualitativo de recomendación
inmobiliaria, con rigor apropiado para una **tesis universitaria**. Cubre calidad de las
respuestas, consistencia, fiabilidad de las fuentes, robustez, comparación entre modelos LLM,
sesgo y aspectos operacionales.

Las métricas se agrupan por **dimensión**. Para cada una: qué mide, cómo se calcula/instrumenta,
y una meta sugerida que se puede ajustar al definir el protocolo experimental.

---

## 1. Calidad de la respuesta

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Fidelidad (groundedness) | Que cada afirmación se sustente en los datos recolectados (POIs, censo, CEAD, Tavily) y no sea inventada | LLM-as-judge que verifica afirmación↔evidencia; o anotación humana frase a frase | ≥ 0,90 afirmaciones sustentadas |
| Tasa de alucinación | Proporción de afirmaciones sin respaldo en las fuentes | 1 − fidelidad; conteo de afirmaciones no verificables | ≤ 5% |
| Relevancia | Qué tan pertinente es la respuesta a la consulta y a la propiedad | Rúbrica 1-5 (humano) o juez LLM con referencia | ≥ 4 / 5 |
| Completitud | Cubre los aspectos esperados (entorno, sector, seguridad, factores) | Checklist de cobertura sobre secciones esperadas | ≥ 0,85 cobertura |
| Coherencia | Ausencia de contradicciones internas | Revisión por juez LLM + muestreo humano | ≥ 4 / 5 |
| Utilidad accionable | Si ayuda a decidir a un usuario no técnico | Encuesta a usuarios / rúbrica de utilidad | ≥ 4 / 5 |

---

## 2. Consistencia (estabilidad de las respuestas)

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Consistencia test-retest | Estabilidad ante la MISMA entrada repetida | N corridas idénticas; similitud semántica media (embeddings / BERTScore) entre pares | ≥ 0,85 |
| Varianza inter-ejecución | Dispersión de conclusiones clave (factores, veredicto) entre corridas | Entropía / desviación de las etiquetas extraídas del informe | Baja (definir umbral) |
| Estabilidad ante temperatura | Cómo cambia la consistencia al subir la temperatura | Repetir el protocolo con T = 0, 0,3, 0,7 y comparar | Documentar curva |
| Auto-consistencia | Acuerdo entre múltiples muestreos antes de consolidar | Self-consistency: votación sobre conclusiones | ≥ 0,8 acuerdo |

---

## 3. Fiabilidad de las fuentes

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Precisión de atribución (citas) | Que la URL/fuente citada respalde realmente la afirmación | Verificación humana o juez LLM sobre pares (afirmación, fuente) | ≥ 0,90 |
| Cobertura de fuentes | Proporción de afirmaciones con fuente cuando corresponde | Afirmaciones citadas / afirmaciones que requieren cita | ≥ 0,80 |
| Frescura | Vigencia temporal de los datos usados (noticias, censo, CEAD) | Antigüedad media de las fuentes citadas | Definir por tipo de dato |
| Verificabilidad | Que las fuentes sean accesibles y reproducibles | % de URLs válidas/resolubles | ≥ 0,95 |
| Concordancia entre fuentes | Acuerdo entre fuentes independientes sobre un mismo hecho | Conteo de conflictos detectados y cómo los resuelve el agente | Reportar |

---

## 4. Robustez

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Invariancia a la reformulación | Misma propiedad descrita de formas distintas → misma conclusión | Parafrasear la entrada N formas; medir estabilidad de la salida | ≥ 0,85 |
| Sensibilidad al prompt | Cuánto cambia la salida ante variaciones menores del prompt de sistema | Ablation de prompts; delta en métricas de calidad | Baja sensibilidad |
| Manejo de datos faltantes | Comportamiento cuando falta geocoding, censo o POIs | Casos con fuentes caídas; ¿lo informa honestamente sin inventar? | 100% lo declara |
| Resistencia a entradas ambiguas | Direcciones incompletas o erróneas | Set de entradas difíciles; tasa de degradación elegante | Sin alucinación |

---

## 5. Comparación entre modelos LLM (Groq vs GPT u otros)

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Calidad relativa | Diferencia de calidad entre modelos con el mismo input | Mismo set de pruebas, mismas métricas de §1; comparación pareada | Reportar ranking |
| Acuerdo inter-modelo | Cuánto coinciden los modelos en conclusiones | Similitud semántica + acuerdo de etiquetas entre modelos | Reportar |
| Latencia | Tiempo de respuesta por modelo | Medición p50/p95 de extremo a extremo | Comparar |
| Costo por consulta | Costo monetario por análisis completo | Tokens × tarifa del proveedor | Comparar |
| Estabilidad de formato | Fiabilidad del structured output (Pydantic) por modelo | % de salidas que validan al esquema sin reintento | ≥ 0,98 |

---

## 6. Sesgo y ética

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Lenguaje estigmatizante | Uso de términos peyorativos al hablar de seguridad/zonas | Clasificador + revisión humana sobre el campo de seguridad | 0 casos |
| Equidad entre comunas | Que comunas de distinto nivel socioeconómico reciban trato comparable en tono y profundidad | Comparar métricas de calidad y sentimiento entre estratos GSE | Sin brecha significativa |
| Balance de factores | Que el informe presente factores a favor y de atención de forma equilibrada | Ratio factores positivos/negativos y revisión | Equilibrado |
| Cumplimiento de disclaimers | Presencia de las advertencias obligatorias (CEAD referencial, etc.) | Verificación automática de presencia de disclaimers | 100% |

---

## 7. Operacionales

| Métrica | Qué mide | Cómo se mide / método | Meta sugerida |
|---|---|---|---|
| Latencia extremo a extremo | Tiempo total por consulta | p50 / p95 en el grafo completo | Definir SLA |
| Costo por consulta | Costo combinado de LLM + APIs | Suma de costos por corrida | Minimizar |
| Tasa de error / fallback de APIs | Frecuencia con que una fuente falla y se degrada | Errores por fuente / total de llamadas | ≤ umbral |
| Disponibilidad | Que el flujo no se caiga ante una fuente caída | Pruebas de caos: tumbar una fuente y verificar respuesta | 100% responde |
| Uso de caché | Efectividad de la caché en reducir llamadas externas | Hit rate de la caché | Reportar |

---

## 8. Métodos de evaluación (instrumentos)

| Método | Para qué sirve | Notas de implementación |
|---|---|---|
| LLM-as-judge | Calidad, fidelidad, atribución a escala | Usar un modelo distinto al evaluado para evitar sesgo; prompt con rúbrica explícita |
| Evaluación humana con rúbrica | Patrón de oro para calidad y utilidad | Definir escala 1-5 y guía de anotación clara |
| Acuerdo inter-evaluador | Fiabilidad de las anotaciones humanas | Cohen's kappa / Krippendorff sobre una muestra doble-anotada |
| Métricas estilo RAGAS | Fidelidad, relevancia y precisión de contexto en flujos con recuperación | Adaptar a las fuentes del agente (POIs, censo, CEAD, web) |
| Similitud semántica | Consistencia e invariancia | Embeddings + coseno, o BERTScore entre salidas |
| Dataset ground-truth | Base estable de comparación y regresión | Conjunto curado de propiedades con su análisis esperado |

---

## Nota metodológica (protocolo experimental sugerido)

1. **Set de pruebas**: construir un conjunto curado de propiedades (p. ej. 30-50) que cubra
   distintas comunas, niveles socioeconómicos y disponibilidad de datos (algunas con fuentes
   incompletas a propósito). Documentar la entrada exacta de cada caso.
2. **Reproducibilidad**: fijar semillas y `temperature=0` para las mediciones de calidad base;
   repetir con temperaturas mayores solo para el análisis de consistencia.
3. **Repeticiones**: cada caso se corre N veces (p. ej. N=5) para estimar varianza y consistencia.
4. **Comparación entre modelos**: ejecutar el mismo set con Groq y con GPT manteniendo todo lo
   demás constante; comparar calidad, acuerdo, latencia y costo.
5. **Doble anotación**: una submuestra evaluada por dos personas para reportar acuerdo inter-evaluador.
6. **Juez LLM independiente**: usar un modelo distinto al evaluado como juez, validando su criterio
   contra las anotaciones humanas en la submuestra.
7. **Reporte**: media e intervalo de confianza por métrica; análisis de errores cualitativo de los
   peores casos.
