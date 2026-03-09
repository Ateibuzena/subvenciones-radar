# ── Monitor de Subvenciones Mejorado ──────────────────────────────────────────
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, time, logging
from pathlib import Path
from datetime import datetime
from typing import List

log = logging.getLogger(__name__)
DATA_DIR = Path("data")  # Ajusta según tu proyecto
DATA_DIR.mkdir(exist_ok=True)

class MonitorSubvenciones:
    """Orquesta todos los scrapers y persiste los resultados."""

    DB_FILE = DATA_DIR / "convocatorias.json"
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
            futures = {executor.submit(self._scrape_scraper, s): s for s in self.scrapers}
            for fut in as_completed(futures):
                nombre = getattr(futures[fut], "NOMBRE", getattr(futures[fut], "nombre", "?"))
                try:
                    nuevas_scraper = fut.result()
                    nuevas.extend(nuevas_scraper)
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

    def _scrape_scraper(self, scraper) -> List:
        nombre = getattr(scraper, "NOMBRE", getattr(scraper, "nombre", "?"))
        try:
            log.info(f"Iniciando scraper {nombre}...")
            results = scraper.scrape()
            time.sleep(1)  # Respeto básico de servidores
            return results
        except Exception as e:
            log.error(f"Fallo completo en scraper {nombre}: {e}")
            return []

    def _deduplicar(self, nuevas: List) -> List:
        existing_ids = set(self.db["convocatorias"])
        results = []
        for c in nuevas:
            if c.id in existing_ids:
                continue
            # Deduplicación semántica simple por título
            if any(self._similar(c.title, e["title"]) > 0.9 for e in self.db["convocatorias"].values()):
                continue
            results.append(c)
        return results

    @staticmethod
    def _similar(a: str, b: str) -> float:
        # Ratio simple de similitud, usar SequenceMatcher o más avanzado si quieres
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()

    def _guardar_alertas(self, nuevas: List):
        alertas = []
        if self.ALERTAS_FILE.exists():
            try:
                alertas = json.loads(self.ALERTAS_FILE.read_text("utf-8"))
            except Exception:
                log.warning("No se pudo cargar alertas existentes, creando nueva lista.")

        for conv in nuevas:
            if getattr(conv, "relevance", 0) >= 0.5:
                alertas.append({
                    "fecha": datetime.now().isoformat(),
                    "convocatoria": conv.to_dict(),
                })

        # Mantener solo últimas 200 alertas
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
        min_relevance: float = 0.0,
    ) -> List[dict]:
        resultados = []
        query_lower = query.lower()

        for conv in self.db["convocatorias"].values():
            if comunidad and conv.get("community", "") != comunidad:
                continue
            if boletin and conv.get("bulletin", "") != boletin:
                continue
            if desde and conv.get("date", "") < desde:
                continue
            if conv.get("relevance", 0) < min_relevance:
                continue
            if query_lower:
                haystack = (
                    f"{conv.get('title','')} {conv.get('body','')} "
                    f"{conv.get('organism','')}".lower()
                )
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
        por_boletin = {}
        por_comunidad = {}
        por_mes = {}

        for conv in self.db["convocatorias"].values():
            b = conv.get("boletin", "?")
            por_boletin[b] = por_boletin.get(b, 0) + 1
            c = conv.get("comunidad", "?")
            por_comunidad[c] = por_comunidad.get(c, 0) + 1
            fecha = conv.get("fecha_publicacion", "")
            mes = fecha[:7] if fecha else "?"
            por_mes[mes] = por_mes.get(mes, 0) + 1

        return {
            "total": total,
            "por_boletin": por_boletin,
            "por_comunidad": por_comunidad,
            "por_mes": dict(sorted(por_mes.items())[-6:]),
            "ultima_actualizacion": self.db.get("ultima_actualizacion"),
        }