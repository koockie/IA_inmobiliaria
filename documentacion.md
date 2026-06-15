# Documentación POC — Agentes de Recomendación Inmobiliaria

Sistema de agentes con **LangGraph** que enriquece el análisis de una oferta inmobiliaria
con información cualitativa del entorno. LLM: **Groq gratis** en local → **OpenAI GPT**
en producción (DigitalOcean), cambiable con una variable de entorno.

---

## 1. Flujo principal del grafo

```mermaid
flowchart TD
    START([Mensaje del usuario]) --> router

    router{{" router"}}

    router -- saludo / ayuda --> conversational
    router -- dirección / propiedad --> extract

    conversational[" conversational\nSaluda y explica para qué sirve"]
    conversational --> END_CHAT([Fin])

    extract[" extract + geocode\nExtrae dirección y obtiene lat/lon/comuna"]

    extract --> fetch_pois
    extract --> fetch_crime
    extract --> query_planner

    subgraph ESTRUCTURADA [" Rama estructurada — sin LLM"]
        direction TB
        fetch_pois[" fetch_pois\nPOIs cercanos vía Overpass"]
        fetch_crime[" fetch_crime\nDelincuencia comunal vía CEAD"]
    end

    subgraph INVESTIGACION ["🔍 Rama investigación — web"]
        direction TB
        query_planner[" query_planner\nLLM genera 3-4 queries"]
        tavily_researcher[" tavily_researcher\nBusca y recolecta contexto"]
        query_planner --> tavily_researcher
    end

    fetch_pois --> synthesizer
    fetch_crime --> synthesizer
    tavily_researcher --> synthesizer

    synthesizer[" synthesizer\nLLM redacta el informe cualitativo final"]
    synthesizer --> END_ANALYSIS([Informe final])
```

---

## 2. Detalle de cada nodo

```mermaid
flowchart TD
    R[" **router**
    ───────────────────────────
    Entrada  → mensaje del usuario
    Proceso  → LLM clasifica intención
    Salida   → intent: chat o analyze"]

    C[" **conversational**
    ───────────────────────────
    Entrada  → historial de mensajes
    Proceso  → LLM responde con contexto
    Salida   → respuesta de texto
    Tools    → ninguna"]

    E[" **extract**
    ───────────────────────────
    Entrada  → mensaje del usuario
    Proceso  → LLM extrae PropertyInput
               + llama a Nominatim
    Salida   → property + geo {lat, lon, comuna}"]

    FP[" **fetch_pois**
    ───────────────────────────
    Entrada  → geo {lat, lon}
    Proceso  → consulta Overpass API
    Sin LLM
    Salida   → conteo + distancia mínima
               por categoría de POI"]

    FC[" **fetch_crime**
    ───────────────────────────
    Entrada  → geo {comuna}
    Proceso  → lookup en CSV CEAD local
    Sin LLM
    Salida   → tasa/100k + comparación
               + disclaimer obligatorio"]

    QP[" **query_planner**
    ───────────────────────────
    Entrada  → dirección + comuna
    Proceso  → LLM con structured_output
    Salida   → lista de 3-4 queries
               de búsqueda específicas"]

    TR[" **tavily_researcher**
    ───────────────────────────
    Entrada  → lista de queries
    Proceso  → llama a Tavily por c/query
    Sin LLM
    Salida   → snippets + URLs
               deduplicados"]

    SY[" **synthesizer**
    ───────────────────────────
    Entrada  → todo el estado del grafo
    Proceso  → LLM redacta informe
    Salida   → QualitativeReport
               {factores_a_favor,
                factores_de_atención,
                contexto_seguridad,
                disclaimers, narrativa}"]

    R --> C
    R --> E
    E --> FP
    E --> FC
    E --> QP
    QP --> TR
    FP --> SY
    FC --> SY
    TR --> SY
```

---

## 3. APIs y herramientas — qué se envía y qué devuelven

```mermaid
flowchart TD

    subgraph NOM [" Nominatim — OpenStreetMap"]
        direction TB
        N_IN["Entrada\nDirección en texto + país=cl"]
        N_OUT["Salida\nlat / lon\nsuburb → comuna\nstate → región\ndisplay_name"]
        N_IN --> N_OUT
    end

    subgraph OVR [" Overpass — OpenStreetMap"]
        direction TB
        O_IN["Entrada\nlat / lon + radio en metros"]
        O_OUT["Salida por categoría\ncolegios → conteo + m al más cercano\nlocomoción → buses y metro\nabastecimiento → supermercados\náreas_verdes → parques\nsalud → hospitales y farmacias"]
        O_IN --> O_OUT
    end

    subgraph TAV [" Tavily — Búsqueda web IA"]
        direction TB
        T_IN["Entrada\nQuery en texto libre\nmax_results: 3"]
        T_OUT["Salida por resultado\ntitle\ncontent (snippet limpio)\nurl (fuente)"]
        T_IN --> T_OUT
    end

    subgraph GRQ [" Groq — LLM local/gratis"]
        direction TB
        G_IN["Entrada\nsystem prompt\nmessages\ntemperatura"]
        G_OUT["Salida\nmessage.content\nusage {tokens usados}\nCon structured_output:\nobjeto Pydantic validado"]
        G_IN --> G_OUT
    end

    subgraph CEA [" CEAD — Dataset comunal"]
        direction TB
        C_IN["Entrada\nnombre de comuna"]
        C_OUT["Salida\ntasa delitos / 100k hab.\naño del dato\ncomparación vs promedio\ndisclaimer obligatorio"]
        C_IN --> C_OUT
    end

    subgraph MIN [" mindicador.cl — Indicadores Chile"]
        direction TB
        M_IN["Entrada\nSin parámetros — sin API key"]
        M_OUT["Salida\nUF valor en pesos\nUTM valor en pesos\nDólar observado\nEuro\nIPC %"]
        M_IN --> M_OUT
    end
```

---





## 7. Pendientes

```mermaid
flowchart TD
    subgraph A [" Alta prioridad"]
        A1["Reemplazar crime_by_comuna.csv\npor descarga oficial de CEAD\ncead.spd.gov.cl"]
    end

    subgraph B [" Media — variables cuantitativas con el equipo"]
        B1["Cap rate y rentabilidad bruta"]
        B2["Precio por m² vs promedio comuna"]
        B3["UF en tiempo real — mindicador.cl\nya integrado en apis/05"]
        B4["Tasa hipotecaria — Banco Central / CMF"]
        B5["Permisos edificación INE — señal de sobreoferta"]
    end

    subgraph C [" Futuro"]
        C1["Caché persistente para Nominatim y Overpass"]
        C2["Actualización automática del dataset CEAD"]
        C3["Migración a geocoder de pago para alta carga"]
    end
```
