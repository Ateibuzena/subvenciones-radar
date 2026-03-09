from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import List

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


class MonitorSubvenciones:
    """Orquesta todos los scrapers y persiste los resultados."""

    DB_FILE     = DATA_DIR / "convocatorias.json"
    ALERTAS_FILE = DATA_DIR / "alertas.json"

    def __init__(self, scrapers: List = None, max_threads: int = 4):
        self.scrapers = scrapers or []
        self.max_threads = max_threads
        self.db = self._cargar_db()

    def _cargar_db(self) -> dict:
        if self.DB_FILE.exists():
            try:
                return json.loads(self.DB_FILE.read_text("utf-8"))
            except Exception:
                log.warning("No se pudo cargar la DB, creando nueva.")
        return {"convocatorias": {}, "ultima_actualizacion": None}

    def _guardar_db(self):
        self.db["ultima_actualizacion"] = datetime.now().isoformat()
        self.DB_FILE.write_text(
            json.dumps(self.db, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def ejecutar(self) -> dict:
        nuevas = []
        errores = []

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {executor.submit(self._run_scraper, s): s for s in self.scrapers}
            for fut in as_completed(futures):
                scraper = futures[fut]
                nombre = getattr(scraper, "NAME", getattr(scraper, "name", "?"))
                try:
                    nuevas.extend(fut.result())
                except Exception as e:
                    log.error(f"Error en scraper {nombre}: {e}")
                    errores.append({"scraper": nombre, "error": str(e)})

        nuevas = self._deduplicar(nuevas)
        for conv in nuevas:
            self.db["convocatorias"][conv.id] = conv.to_dict()

        self._guardar_db()
        self._guardar_alertas(nuevas)

        resumen = {
            "fecha": datetime.now().isoformat(),
            "total_db": len(self.db["convocatorias"]),
            "nuevas_esta_ejecucion": len(nuevas),
            "errores": errores,
            "nuevas": [c.to_dict() for c in nuevas[:20]],
        }
        log.info(
            f"Ejecución completada: {len(nuevas)} nuevas, "
            f"{len(self.db['convocatorias'])} en DB total"
        )
        return resumen

    def _run_scraper(self, scraper) -> List:
        nombre = getattr(scraper, "NAME", getattr(scraper, "name", "?"))
        try:
            log.info(f"Iniciando scraper {nombre}...")
            results = scraper.scrape()
            time.sleep(1)
            return results
        except Exception as e:
            log.error(f"Fallo en scraper {nombre}: {e}")
            return []

    def _deduplicar(self, nuevas: List) -> List:
        from difflib import SequenceMatcher
        existing_ids = set(self.db["convocatorias"])
        seen_titles = [v.get("title", "") for v in self.db["convocatorias"].values()]
        results = []
        for conv in nuevas:
            if conv.id in existing_ids:
                continue
            # Deduplicación semántica: descartar si hay un título muy similar ya guardado
            if any(
                SequenceMatcher(None, conv.title, t).ratio() > 0.9
                for t in seen_titles
            ):
                continue
            results.append(conv)
            seen_titles.append(conv.title)  # evitar duplicados dentro del mismo lote
        return results

    def _guardar_alertas(self, nuevas: List):
        alertas = []
        if self.ALERTAS_FILE.exists():
            try:
                alertas = json.loads(self.ALERTAS_FILE.read_text("utf-8"))
            except Exception:
                pass
        for conv in nuevas:
            if getattr(conv, "relevance", 0) >= 0.5:
                alertas.append({
                    "fecha": datetime.now().isoformat(),
                    "convocatoria": conv.to_dict(),
                })
        alertas = alertas[-200:]
        self.ALERTAS_FILE.write_text(
            json.dumps(alertas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def buscar(
        self,
        query: str = "",
        comunidad: str = "",
        boletin: str = "",
        desde: str = "",
        min_relevancia: float = 0.0,
    ) -> List[dict]:
        resultados = []
        query_lower = query.lower()

        for conv in self.db["convocatorias"].values():
            # FIX: el campo se llama "community" en Convocation, no "comunidad"
            if comunidad and conv.get("community", "") != comunidad:
                continue
            # FIX: el campo se llama "bulletin", no "boletin"
            if boletin and conv.get("bulletin", "") != boletin:
                continue
            # FIX: el campo se llama "date", no "fecha_publicacion"
            if desde and conv.get("date", "") < desde:
                continue
            if conv.get("relevance", 0) < min_relevancia:
                continue
            if query_lower:
                haystack = " ".join([
                    conv.get("title", ""),
                    conv.get("description", "") or "",
                    conv.get("body", ""),
                ]).lower()
                if not all(w in haystack for w in query_lower.split()):
                    continue
            resultados.append(conv)

        return sorted(
            resultados,
            key=lambda x: (x.get("date", ""), x.get("relevance", 0)),
            reverse=True,
        )

    def estadisticas(self) -> dict:
        total = len(self.db["convocatorias"])
        por_boletin   = {}
        por_comunidad = {}
        por_mes       = {}

        for conv in self.db["convocatorias"].values():
            # FIX: nombres de campo correctos
            b = conv.get("bulletin", "?")
            por_boletin[b] = por_boletin.get(b, 0) + 1

            c = conv.get("community", "?")
            por_comunidad[c] = por_comunidad.get(c, 0) + 1

            fecha = conv.get("date", "")
            mes = fecha[:7] if fecha else "?"
            por_mes[mes] = por_mes.get(mes, 0) + 1

        return {
            "total": total,
            "por_boletin": por_boletin,
            "por_comunidad": por_comunidad,
            "por_mes": dict(sorted(por_mes.items())[-6:]),
            "ultima_actualizacion": self.db.get("ultima_actualizacion"),
        }
