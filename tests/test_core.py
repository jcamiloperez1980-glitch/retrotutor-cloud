import io
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import core

SECRET = "secreto-de-prueba"


def emitir_codigo(dias_desde_epoch: int, rand: str = "AB12", secret: str = SECRET) -> str:
    """Genera un código como lo haría Zajuna Panel (solo para pruebas)."""
    alfabeto = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    n, exp = dias_desde_epoch, ""
    for _ in range(3):
        exp = alfabeto[n % 36] + exp
        n //= 36
    return f"ZP-{exp}-{rand}-{core.zp_sign(secret, f'{exp}-{rand}')}"


AHORA = datetime(2026, 11, 1, tzinfo=timezone.utc)
DIAS_HOY = (AHORA - core.ZP_EPOCH).days


class TestLicencia:
    def test_codigo_valido(self):
        r = core.zp_validate(emitir_codigo(DIAS_HOY + 30), SECRET, now=AHORA)
        assert r["valid"] and r["days_left"] == 30

    def test_minusculas_y_espacios(self):
        assert core.zp_validate("  " + emitir_codigo(DIAS_HOY + 5).lower() + " ", SECRET, now=AHORA)["valid"]

    def test_codigo_vencido(self):
        r = core.zp_validate(emitir_codigo(DIAS_HOY - 1), SECRET, now=AHORA)
        assert not r["valid"] and "venció" in r["reason"]

    def test_firma_incorrecta(self):
        r = core.zp_validate(emitir_codigo(DIAS_HOY + 30, secret="otro"), SECRET, now=AHORA)
        assert not r["valid"] and r["reason"] == "Código no válido."

    @pytest.mark.parametrize("codigo", ["", None, "ZP-123", "XX-ABC-ABCD-ABCDEF"])
    def test_formato_invalido(self, codigo):
        assert "Formato" in core.zp_validate(codigo, SECRET)["reason"]

    def test_sin_secreto_no_activa(self):
        r = core.zp_validate(emitir_codigo(DIAS_HOY + 30), "", now=AHORA)
        assert not r["valid"] and "configurada" in r["reason"]


class TestPrueba:
    def test_recien_iniciada(self):
        inicio = int(AHORA.timestamp() * 1000)
        r = core.trial_status(inicio, now=AHORA)
        assert r["active"] and r["days_left"] == 14

    def test_vencida(self):
        inicio = int((AHORA - timedelta(days=20)).timestamp() * 1000)
        assert not core.trial_status(inicio, now=AHORA)["active"]

    @pytest.mark.parametrize("raw,esperado", [("1793530812832", 1793530812832), (None, None), ("abc", None), ("-5", None)])
    def test_parse_cookie(self, raw, esperado):
        assert core.parse_trial_cookie(raw) == esperado


class TestExtraccion:
    def test_txt(self):
        assert core.extraer_texto("Hola ñandú".encode(), "a.txt") == "Hola ñandú"

    def test_docx_con_tabla(self):
        from docx import Document

        doc = Document()
        doc.add_paragraph("Introducción del ensayo")
        tabla = doc.add_table(rows=1, cols=2)
        tabla.rows[0].cells[0].text = "Criterio"
        tabla.rows[0].cells[1].text = "Excelente"
        buf = io.BytesIO()
        doc.save(buf)
        texto = core.extraer_texto(buf.getvalue(), "Ana_Perez.docx")
        assert "Introducción del ensayo" in texto and "Criterio | Excelente" in texto

    def test_pptx(self):
        from pptx import Presentation

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Mi presentación"
        buf = io.BytesIO()
        prs.save(buf)
        assert "Mi presentación" in core.extraer_texto(buf.getvalue(), "x.pptx")

    def test_pdf_corrupto_lanza_valueerror(self):
        with pytest.raises(ValueError, match="No se pudo leer"):
            core.extraer_texto(b"no soy un pdf", "roto.pdf")

    def test_clasificar(self):
        assert core.clasificar_archivo("foto.JPG") == "imagen"
        assert core.clasificar_archivo("ensayo.pdf") == "documento"


class TestPrompt:
    def test_pide_espanol_e_incluye_datos(self):
        p = core.construir_prompt("Ana Pérez", "Guía X", "Rúbrica Y", "Texto Z", "documento", "Aprobado")
        assert "Spanish" in p and "Ana Pérez" in p and "Guía X" in p and "Rúbrica Y" in p
        assert core.VEREDICTO_APROBADO in p

    def test_deficiente_sin_guia(self):
        p = core.construir_prompt("", "", "", "Texto", "texto", "Deficiente")
        assert core.VEREDICTO_DEFICIENTE in p and "ACTIVITY GUIDE" not in p and "Estudiante" in p

    def test_contenido_imagen(self):
        e = {"tipo": "imagen", "contenido": "ocr", "observaciones": "nota"}
        assert core.contenido_para_llm(e) == "[OCR text from image]: ocr\n[Instructor notes]: nota"
        assert core.contenido_para_llm({"tipo": "imagen"}) == "No description provided."


class FakeClient:
    def __init__(self, contenido):
        self.contenido = contenido
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        msg = type("M", (), {"content": self.contenido})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


def test_generar_feedback(monkeypatch):
    creados = {}

    def fake_openai(**kwargs):
        creados.update(kwargs)
        return FakeClient("  ¡Buen trabajo, Ana!  ")

    monkeypatch.setattr("openai.OpenAI", fake_openai)
    assert core.generar_feedback("k", "OpenRouter", "m", "p") == "¡Buen trabajo, Ana!"
    assert creados["base_url"] == "https://openrouter.ai/api/v1"


def test_generar_feedback_vacio(monkeypatch):
    monkeypatch.setattr("openai.OpenAI", lambda **kw: FakeClient(None))
    with pytest.raises(RuntimeError):
        core.generar_feedback("k", "OpenAI", "gpt-4o-mini", "p")


def entrega(nombre, retro):
    return {"estudiante": nombre, "archivo_nombre": "a.pdf", "tipo": "documento",
            "veredicto": "Aprobado", "retroalimentacion": retro, "observaciones": ""}


def test_zip_nombres_unicos():
    datos = core.zip_entregas([entrega("Ana Pérez", "Bien"), entrega("Ana Pérez", "Bien 2"), entrega("Luis", None)])
    nombres = zipfile.ZipFile(io.BytesIO(datos)).namelist()
    assert nombres == ["Ana_Pérez.txt", "Ana_Pérez_1.txt"]


def test_excel():
    df = pd.read_excel(io.BytesIO(core.excel_entregas([entrega("Ana", "Bien")])))
    assert list(df.columns)[:2] == ["Estudiante", "Archivo"] and df.loc[0, "Retroalimentación"] == "Bien"


def test_nombre_seguro():
    assert core.nombre_seguro("Ensayo: final/2") == "Ensayo_final2"
    assert core.nombre_seguro("***") == "entrega"
