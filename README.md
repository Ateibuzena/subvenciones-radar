# subvenciones-radar

> Vigilancia automática de ayudas y subvenciones públicas para empresas en España.  
> Rastrea el BOE, la BDNS y 5 boletines autonómicos cada día y lo presenta en un dashboard visual.

---

## ¿Qué problema resuelve?

En España hay cientos de convocatorias de subvenciones activas en cada momento: dinero público para digitalizar tu empresa, contratar empleados, hacer I+D, exportar, invertir en energía renovable...

El problema es que **nadie te avisa**. Están publicadas en boletines oficiales que nadie lee, en un lenguaje jurídico denso, repartidas entre el BOE, la BDNS y los 17 boletines autonómicos.

Este proyecto automatiza esa vigilancia. Cada día escanea las fuentes oficiales, filtra el ruido y presenta solo lo relevante para empresas.

---

## Cómo funciona

```
Boletines oficiales  →  Scrapers  →  Filtrado por relevancia  →  Dashboard
(BOE, BDNS, BOJA…)     (Python)      (algoritmo palabras clave)   (HTML/JS)
```

1. Los **scrapers** se conectan a 7 fuentes oficiales usando sus APIs y feeds RSS
2. Cada resultado es **puntuado automáticamente** según la probabilidad de ser una ayuda para empresas
3. Los resultados se guardan en una **base de datos local** (JSON) sin necesidad de servidor externo
4. El **dashboard** muestra todo de forma visual: filtros, gráficas, detalle de cada convocatoria

---

## Fuentes monitorizadas

| Boletín | Ámbito | Método de extracción |
|---------|--------|----------------------|
| **BOE** | Nacional | API REST JSON oficial |
| **BDNS** | Nacional (solo subvenciones) | API REST oficial |
| **BOJA** | Andalucía | Feed RSS |
| **DOGC** | Cataluña | Feed RSS |
| **BOCM** | Madrid | Feed RSS |
| **DOGV** | Comunitat Valenciana | Feed RSS |
| **BOPV** | País Vasco | Feed RSS |

---

## Instalación y uso

No requiere librerías externas. Solo Python 3.10+.

```bash
# Clonar el repositorio
git clone https://github.com/Ateibuzena/subvenciones-radar.git
cd subvenciones-radar

# Probar con datos de demo (sin conexión a internet)
python3 generar_demo.py
open dashboard.html

# Ejecutar los scrapers reales
python3 scraper.py scrape

# Buscar en los resultados
python3 scraper.py buscar "digitalización pyme"
python3 scraper.py buscar --comunidad "Andalucía" --relevancia 0.5

# Ver estadísticas
python3 scraper.py stats
```

---

## Dashboard

Abre `dashboard.html` en cualquier navegador después de ejecutar el scraper.

- **Filtros en tiempo real** por texto, boletín, comunidad autónoma y relevancia
- **Panel de detalle** con plazo de solicitud, importe máximo, sectores y enlace al boletín original
- **Gráficas** de distribución por fuente, por comunidad y evolución mensual
- Sin servidor. Sin dependencias. Funciona abriendo el archivo directamente.

---

## Automatización

Para ejecutarlo cada día de forma automática (Mac / Linux):

```bash
# Editar el cron
crontab -e

# Añadir esta línea para ejecutarlo de lunes a viernes a las 9:00
0 9 * * 1-5 cd /ruta/al/proyecto && python3 scraper.py scrape
```

---

## Estructura del proyecto

```
subvenciones-radar/
├── scraper.py          # Motor principal: scrapers, filtrado, base de datos
├── generar_demo.py     # Genera datos ficticios para probar sin internet
├── dashboard.html      # Panel visual interactivo (abrir en navegador)
└── data/
    ├── convocatorias.json  # Base de datos local con todas las convocatorias
    ├── alertas.json        # Convocatorias de alta relevancia (score ≥ 0.5)
    └── scraper.log         # Registro de ejecuciones y errores
```

---

## Añadir más boletines

El sistema es extensible. Para añadir cualquier boletín con feed RSS:

```python
# En scraper.py, añadir en la lista SCRAPERS:
ScraperRSS(
    nombre="BORM",
    comunidad="Murcia",
    rss_url="https://www.borm.es/services/anuncio/rss",
),
```

Boletines autonómicos pendientes de añadir: BOA (Aragón), BOCYL (Castilla y León), DOCM (Castilla-La Mancha), DOE (Extremadura), BOR (La Rioja), BOIB (Illes Balears), BOC (Canarias).

---

## Decisiones técnicas

**¿Por qué Python puro sin dependencias?** Para que cualquiera pueda clonarlo y ejecutarlo sin instalar nada más. No hay `requirements.txt` porque no hace falta.

**¿Por qué JSON en lugar de una base de datos?** Para mantenerlo simple y portátil. Con volúmenes de hasta ~10.000 convocatorias el rendimiento es perfectamente aceptable.

**¿Por qué un HTML estático en lugar de una app web?** Porque el objetivo es que funcione en cualquier ordenador sin configuración. Abrir un archivo es más accesible que levantar un servidor.

**¿Por qué palabras clave en lugar de IA para el filtrado?** El algoritmo actual es simple, auditable y predecible. Una mejora natural sería incorporar un clasificador entrenado con convocatorias reales o usar la API de un LLM para el análisis semántico.

---

## Posibles mejoras

- [ ] Alertas por email o Telegram cuando aparece una convocatoria nueva
- [ ] Perfil de empresa configurable para filtrar automáticamente por sector y tamaño
- [ ] Calendario de plazos con avisos antes de que cierren las solicitudes
- [ ] Clasificador semántico con NLP para reducir falsos positivos
- [ ] Cobertura de los 17 boletines autonómicos
- [ ] Exportación de resultados a CSV/Excel

---

## Contexto

Proyecto personal desarrollado para explorar la automatización de la vigilancia de información pública. Combina extracción de datos de APIs y RSS gubernamentales, procesamiento de texto y visualización sin frameworks.

Las fuentes utilizadas son todas públicas y oficiales. El scraper respeta los servidores con pausas entre peticiones y no guarda más datos de los publicados en los propios boletines.
