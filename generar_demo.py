#!/usr/bin/env python3
"""Genera datos de demo para el dashboard."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BOLETINES = ["BOE", "BDNS", "BOJA", "DOGC", "BOCM", "DOGV", "BOPV"]
COMUNIDADES = {
    "BOE": "Nacional", "BDNS": "Nacional",
    "BOJA": "Andalucía", "DOGC": "Cataluña",
    "BOCM": "Madrid", "DOGV": "Comunitat Valenciana", "BOPV": "País Vasco",
}
ORGANISMOS = [
    "Ministerio de Industria, Comercio y Turismo",
    "Ministerio de Ciencia e Innovación",
    "CDTI – Centro para el Desarrollo Tecnológico Industrial",
    "ENISA – Empresa Nacional de Innovación",
    "Consejería de Economía y Hacienda",
    "Agència per la Competitivitat de l'Empresa (ACCIÓ)",
    "Comunidad de Madrid – Dirección General de Innovación",
    "IVACE – Institut Valencià de Competitivitat Empresarial",
    "SPRI – Agencia de Desarrollo Empresarial País Vasco",
    "Junta de Andalucía – Agencia IDEA",
    "Instituto para la Diversificación y Ahorro de la Energía (IDAE)",
    "Red.es – Entidad Pública Empresarial",
]
TITULOS = [
    "Convocatoria de ayudas para proyectos de I+D+i en empresas industriales",
    "Subvenciones para la digitalización de pymes y autónomos – Kit Digital",
    "Programa de apoyo al emprendimiento y la creación de empresas innovadoras",
    "Ayudas para la contratación de personas con discapacidad en empresas",
    "Convocatoria de becas para proyectos de cooperación empresarial internacional",
    "Incentivos a la inversión empresarial en zonas de especial desarrollo",
    "Financiación para proyectos de eficiencia energética en sector industrial",
    "Subvenciones para la internacionalización de pymes exportadoras",
    "Programa de ayudas a la transformación digital del comercio minorista",
    "Convocatoria de préstamos participativos para startups tecnológicas",
    "Ayudas al empleo joven en empresas con menos de 50 trabajadores",
    "Subvenciones para certificaciones de calidad y normas ISO en pymes",
    "Programa de cofinanciación de proyectos de economía circular",
    "Convocatoria de apoyo a la formación continua en empresas",
    "Incentivos a la creación de empleo estable en sectores estratégicos",
    "Ayudas para la adquisición de maquinaria y equipamiento industrial",
    "Subvenciones para proyectos de accesibilidad e inclusión en empresas",
    "Programa de financiación de proyectos de energía renovable en pymes",
    "Convocatoria de ayudas Next Generation para digitalización empresarial",
    "Apoyo a microempresas en zonas rurales – LEADER 2024",
    "Incentivos a la investigación colaborativa empresa-universidad",
    "Subvenciones a proyectos de ciberseguridad para pymes",
    "Ayudas para planes de igualdad y conciliación en empresas",
    "Financiación de proyectos de movilidad eléctrica en flotas empresariales",
    "Convocatoria de apoyo a empresas exportadoras de servicios digitales",
]
SECTORES = [
    ["Tecnología", "Innovación"],
    ["Industria", "Manufactura"],
    ["Comercio", "Retail"],
    ["Energía", "Sostenibilidad"],
    ["Agroalimentario"],
    ["Turismo", "Hostelería"],
    ["Salud", "Biotecnología"],
    ["Logística", "Transporte"],
    ["Construcción", "Inmobiliario"],
    ["Servicios Profesionales"],
]
IMPORTES = [
    "hasta 50.000 €", "hasta 200.000 €", "hasta 500.000 €",
    "hasta 1.000.000 €", "hasta 2.000.000 €", "hasta 5.000.000 €",
    "3.000 – 25.000 €", "10.000 – 100.000 €", "",
]
BENEFICIARIOS = [
    ["Pymes", "Autónomos"],
    ["Grandes empresas", "Pymes"],
    ["Startups", "Empresas emergentes"],
    ["Microempresas"],
    ["Cualquier empresa"],
    ["Autónomos"],
]

def generar_fecha(dias_atras_max=90):
    delta = random.randint(0, dias_atras_max)
    return (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")

def generar_plazo():
    dias = random.randint(15, 90)
    fecha = datetime.now() + timedelta(days=dias)
    return fecha.strftime("%d/%m/%Y")

def main():
    convocatorias = {}
    random.seed(42)

    for i in range(80):
        boletin = random.choice(BOLETINES)
        titulo = random.choice(TITULOS)
        idx = str(i).zfill(6)
        cid = f"demo{idx}"

        conv = {
            "id": cid,
            "titulo": titulo,
            "organismo": random.choice(ORGANISMOS),
            "boletin": boletin,
            "comunidad": COMUNIDADES[boletin],
            "fecha_publicacion": generar_fecha(),
            "url": f"https://www.boe.es/diario_boe/txt.php?id=BOE-A-2024-{10000+i}",
            "descripcion": (
                f"Se convocan {titulo.lower()} dirigidas a {random.choice(BENEFICIARIOS)[0].lower()} "
                f"con domicilio fiscal en España. La solicitud deberá realizarse "
                f"a través de la sede electrónica del organismo convocante."
            ),
            "plazo_solicitud": f"Hasta el {generar_plazo()}",
            "importe_maximo": random.choice(IMPORTES),
            "sectores": random.choice(SECTORES),
            "tipo_beneficiario": random.choice(BENEFICIARIOS),
            "relevancia": round(random.uniform(0.3, 1.0), 2),
            "fecha_scraping": datetime.now().isoformat(),
        }
        convocatorias[cid] = conv

    db = {
        "convocatorias": convocatorias,
        "ultima_actualizacion": datetime.now().isoformat(),
    }

    out = DATA_DIR / "convocatorias.json"
    out.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ {len(convocatorias)} convocatorias de demo generadas → {out}")

if __name__ == "__main__":
    main()
