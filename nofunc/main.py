#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime
from scripts.monitor import MonitorSubvenciones
from scripts.classes import BOEScraper, RSSScraper, BOJAScraper, DOGCScraper, BOCMScraper, DOGVScraper, BOPVScraper, BDNSScraper

def main():
    # ── Configuración de scrapers ───────────────────────────────
    scrapers = [
        BOEScraper(days_back=3),  # Últimos 3 días del BOE
        BDNSScraper(),
        BOJAScraper(),
        DOGCScraper(),
        BOCMScraper(),
        DOGVScraper(),
        BOPVScraper(),
    ]

    # ── Inicializar monitor ────────────────────────────────────
    monitor = MonitorSubvenciones(scrapers=scrapers)

    # ── Ejecutar scraping ───────────────────────────────────────
    resumen = monitor.ejecutar()
    print(f"\nResumen ejecución:")
    print(f"  Nuevas convocatorias: {resumen['nuevas_esta_ejecucion']}")
    print(f"  Total en base de datos: {resumen['total_db']}")
    if resumen["errores"]:
        print("  Errores durante la ejecución:")
        for e in resumen["errores"]:
            print(f"    - {e['scraper']}: {e['error']}")

    # ── Buscar convocatorias relevantes ────────────────────────
    query = "innovación digital"
    resultados = monitor.buscar(query=query, min_relevancia=0.5)
    print(f"\nConvocatorias filtradas por query='{query}' y relevancia>=0.5:")
    for r in resultados[:5]:
        print(f"- {r['fecha_publicacion']} | {r['titulo']} | {r['url']}")

    # ── Estadísticas ───────────────────────────────────────────
    stats = monitor.estadisticas()
    print("\nEstadísticas generales:")
    print(f"  Total: {stats['total']}")
    print(f"  Por boletín: {stats['por_boletin']}")
    print(f"  Por comunidad: {stats['por_comunidad']}")
    print(f"  Última actualización: {stats['ultima_actualizacion']}")

if __name__ == "__main__":
    main()