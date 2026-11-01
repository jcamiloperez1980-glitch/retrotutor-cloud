"""
Lógica de RetroTutor sin dependencia de Streamlit (testeable con pytest).

Incluye: licencias Zajuna Panel (HMAC), prueba gratuita, extracción de texto
de archivos, construcción del prompt, llamada al LLM y exportaciones.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import math
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# ── Tipos de archivo ─────────────────────────────────────────────────────────

EXT_DOCUMENTO = ["pdf", "docx", "pptx", "txt", "md"]
EXT_IMAGEN = ["png", "jpg", "jpeg", "gif", "webp", "bmp"]
TODAS_EXT = EXT_DOCUMENTO + EXT_IMAGEN

# ── Proveedores y modelos LLM ────────────────────────────────────────────────

PROVEEDORES = {
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "modelos": [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "deepseek/deepseek-r1-0528:free",
            "google/gemma-3-27b-it:free",
            "meta-llama/llama-4-maverick:free",
        ],
    },
    "OpenAI": {
        "base_url": None,
        "env_key": "OPENAI_API_KEY",
        "modelos": ["gpt-4o-mini", "gpt-4o"],
    },
}

# ── Prompt ───────────────────────────────────────────────────────────────────

PROMPT = """You are an instructor giving feedback on a learner's assignment (for example, at SENA in Colombia). Write SHORT personalized feedback (MAX 150 words, this is critical — never exceed it).

LANGUAGE: Write the feedback in Spanish (Colombia), using "tú". Never answer in English.

Student: {nombre}
{bloque_guia}
{bloque_rubrica}
VERDICT: {veredicto_texto}
{bloque_contenido}
{bloque_observaciones}

Structure (no headers, no bullets, plain text only):
- Greet by first name
- ONE paragraph: what they did well/poorly, be specific about their content
- TWO concrete suggestions (most impactful)
- Brief encouraging closing

STRICT LIMIT: 150 words maximum. Be concise."""

VEREDICTO_APROBADO = (
    "APPROVED — the student met the requirements. Focus on strengths, "
    "celebrate what they did well, and offer minor suggestions for excellence."
)
VEREDICTO_DEFICIENTE = (
    "NEEDS IMPROVEMENT — the student did not meet the requirements. "
    "Be constructive: clearly state what fell short, give specific actionable "
    "steps to improve, and maintain an encouraging tone. Motivate them to try again."
)

# ── Licencia (compatible con Zajuna Panel) ───────────────────────────────────

ZP_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
ZP_TRIAL_DAYS = 14
_CODIGO_RE = re.compile(r"^ZP-([0-9A-Z]{3})-([0-9A-Z]{4})-([0-9A-Z]{6})$")


def zp_sign(secret: str, payload: str) -> str:
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return sig[:6].upper()


def zp_validate(code: str, secret: str, now: datetime | None = None) -> dict:
    """Valida un código ZP-XXX-XXXX-XXXXXX firmado con HMAC-SHA256."""
    if not secret:
        return {"valid": False, "reason": "La activación Pro no está configurada en este servidor."}
    code = (code or "").strip().upper()
    m = _CODIGO_RE.match(code)
    if not m:
        return {"valid": False, "reason": "Formato inválido. Ejemplo: ZP-XXX-XXXX-XXXXXX"}
    exp, rand, sig = m.group(1), m.group(2), m.group(3)
    if not hmac.compare_digest(sig, zp_sign(secret, f"{exp}-{rand}")):
        return {"valid": False, "reason": "Código no válido."}
    expires_dt = ZP_EPOCH + timedelta(days=int(exp, 36))
    now = now or datetime.now(timezone.utc)
    days_left = (expires_dt.date() - now.date()).days
    if days_left <= 0:
        return {"valid": False, "reason": f"Este código venció el {expires_dt.strftime('%d/%m/%Y')}."}
    return {"valid": True, "expires": expires_dt, "days_left": days_left}


def trial_status(start_ms: int, now: datetime | None = None) -> dict:
    """Estado de la prueba gratuita a partir del inicio (milisegundos epoch)."""
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    ends_at = start + timedelta(days=ZP_TRIAL_DAYS)
    now = now or datetime.now(timezone.utc)
    days_left = max(0, math.ceil((ends_at - now).total_seconds() / 86400))
    return {"active": days_left > 0, "days_left": days_left, "ends_at": ends_at}


def parse_trial_cookie(raw) -> int | None:
    """Convierte el valor de la cookie a milisegundos; None si no es válido."""
    try:
        valor = int(raw)
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None


# ── Extracción de texto ──────────────────────────────────────────────────────

def clasificar_archivo(nombre: str) -> str:
    ext = Path(nombre).suffix.lower().lstrip(".")
    return "imagen" if ext in EXT_IMAGEN else "documento"


def ocr_imagen(datos: bytes) -> str:
    """OCR con Tesseract (eng+spa). Devuelve "" si Tesseract no está disponible."""
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(datos))
        return pytesseract.image_to_string(img, lang="eng+spa").strip()
    except Exception:
        return ""


def extraer_texto(datos: bytes, nombre: str) -> str:
    """Extrae texto de PDF, DOCX, PPTX, TXT o MD. Lanza ValueError si el archivo está dañado."""
    ext = Path(nombre).suffix.lower()
    if ext in (".txt", ".md"):
        return datos.decode("utf-8", errors="ignore")
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(datos)).pages)
        if ext == ".docx":
            from docx import Document

            doc = Document(io.BytesIO(datos))
            partes = [p.text for p in doc.paragraphs]
            for tabla in doc.tables:
                for fila in tabla.rows:
                    partes.append(" | ".join(c.text for c in fila.cells))
            return "\n".join(partes)
        if ext == ".pptx":
            from pptx import Presentation

            textos = []
            for slide in Presentation(io.BytesIO(datos)).slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        textos.append(shape.text_frame.text)
            return "\n".join(textos)
    except Exception as exc:  # archivos corruptos o protegidos
        raise ValueError(f"No se pudo leer «{nombre}»: {exc}") from exc
    return datos.decode("utf-8", errors="ignore")


# ── Prompt y LLM ─────────────────────────────────────────────────────────────

def contenido_para_llm(entrega: dict) -> str:
    """Para imágenes combina OCR + notas del instructor; para el resto, el texto."""
    if entrega["tipo"] != "imagen":
        return entrega.get("contenido") or ""
    partes = []
    if entrega.get("contenido"):
        partes.append(f"[OCR text from image]: {entrega['contenido']}")
    if entrega.get("observaciones"):
        partes.append(f"[Instructor notes]: {entrega['observaciones']}")
    return "\n".join(partes) or "No description provided."


def construir_prompt(
    nombre: str, guia: str, rubrica: str, contenido: str, tipo: str,
    veredicto: str, observaciones: str = "",
) -> str:
    bloque_guia = f"ACTIVITY GUIDE:\n---\n{guia}\n---" if guia.strip() else ""
    bloque_rubrica = f"EVALUATION RUBRIC:\n---\n{rubrica}\n---" if rubrica.strip() else ""
    etiqueta = "image" if tipo == "imagen" else "text/document"
    bloque_contenido = f"STUDENT'S SUBMISSION ({etiqueta}):\n---\n{contenido}\n---"
    bloque_obs = f"INSTRUCTOR'S ADDITIONAL NOTES:\n{observaciones}" if observaciones.strip() else ""
    return PROMPT.format(
        nombre=nombre or "Estudiante",
        bloque_guia=bloque_guia,
        bloque_rubrica=bloque_rubrica,
        veredicto_texto=VEREDICTO_APROBADO if veredicto == "Aprobado" else VEREDICTO_DEFICIENTE,
        bloque_contenido=bloque_contenido,
        bloque_observaciones=bloque_obs,
    )


def generar_feedback(api_key: str, proveedor: str, modelo_llm: str, prompt: str) -> str:
    """Llama al proveedor (API compatible con OpenAI) y devuelve el texto generado."""
    from openai import OpenAI

    base_url = PROVEEDORES[proveedor]["base_url"]
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=modelo_llm,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=1500,
    )
    texto = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not texto:
        raise RuntimeError("El modelo devolvió una respuesta vacía. Intenta de nuevo o cambia de modelo.")
    return texto


# ── Exportaciones ────────────────────────────────────────────────────────────

def nombre_seguro(texto: str) -> str:
    limpio = re.sub(r"[^\w\s.-]", "", texto or "").strip()
    return re.sub(r"\s+", "_", limpio)[:80] or "entrega"


def zip_entregas(entregas: list[dict]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        usados: set[str] = set()
        for e in entregas:
            if not e.get("retroalimentacion"):
                continue
            base = nombre_seguro(e["estudiante"])
            nombre, c = base, 1
            while nombre in usados:
                nombre = f"{base}_{c}"
                c += 1
            usados.add(nombre)
            z.writestr(
                f"{nombre}.txt",
                f"Estudiante: {e['estudiante']}\n"
                f"Archivo: {e['archivo_nombre']}\n"
                f"Veredicto: {e['veredicto']}\n\n"
                f"Retroalimentación:\n{e['retroalimentacion']}\n",
            )
    return buffer.getvalue()


def excel_entregas(entregas: list[dict]) -> bytes:
    filas = [
        {
            "Estudiante": e["estudiante"],
            "Archivo": e["archivo_nombre"],
            "Tipo": e["tipo"],
            "Veredicto": e.get("veredicto") or "",
            "Retroalimentación": e.get("retroalimentacion") or "",
            "Observaciones": e.get("observaciones") or "",
        }
        for e in entregas
    ]
    buf = io.BytesIO()
    pd.DataFrame(filas).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()
