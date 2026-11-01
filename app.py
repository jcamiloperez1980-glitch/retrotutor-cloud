"""
RetroTutor Cloud — Retroalimentación automática de evidencias estudiantiles.
Versión desplegable en Streamlit Cloud. Soporta documentos, texto e imágenes.

La lógica (licencias, extracción, prompt, LLM, exportaciones) vive en core.py.
"""

import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import extra_streamlit_components as stx
import streamlit as st
from extra_streamlit_components.CookieManager import _component_func as _cookie_component

import core

st.set_page_config(page_title="RetroTutor", page_icon="🎓", layout="wide")


# ── Configuración y secretos ─────────────────────────────────────────────────

def leer_secreto(nombre: str) -> str:
    """Lee un secreto de variables de entorno o de .streamlit/secrets.toml.

    Nunca falla: si no existe, devuelve "".
    """
    valor = os.environ.get(nombre, "")
    if valor:
        return valor
    try:
        return str(st.secrets.get(nombre, "") or "")
    except Exception:  # no hay secrets.toml
        return ""


ZP_SECRET = leer_secreto("ZP_SECRET")
COOKIE_DIAS = 400


class CookiesNavegador(stx.CookieManager):
    """CookieManager que distingue «aún no cargó» (None) de «no hay cookies» ({}).

    El CookieManager original devuelve {} en la primera ejecución, antes de que
    el navegador responda; eso hacía que la prueba gratuita se reiniciara en
    cada visita porque la cookie existente se sobrescribía.
    """

    def __init__(self):  # noqa: D401 — no llamamos al __init__ original
        self.cookie_manager = _cookie_component
        self.cookies = _cookie_component(method="getAll", key="init", default=None)

    def guardar(self, nombre: str, valor, key: str):
        self.set(
            nombre, valor, key=key,
            expires_at=datetime.now() + timedelta(days=COOKIE_DIAS),
            max_age=COOKIE_DIAS * 86400,
        )


# ── Estado ────────────────────────────────────────────────────────────────────

for _k, _v in {
    "espacios": [], "espacio_idx": None, "licencia_ok": False,
    "licencia_trial": False, "licencia_days": 0,
}.items():
    st.session_state.setdefault(_k, _v)

cookies = CookiesNavegador()
if cookies.cookies is None:
    # El componente de cookies todavía no respondió; Streamlit vuelve a
    # ejecutar el script automáticamente cuando llega la respuesta.
    st.caption("Cargando RetroTutor…")
    st.stop()


def activar_pro(codigo: str) -> bool:
    resultado = core.zp_validate(codigo, ZP_SECRET)
    if not resultado["valid"]:
        st.error(resultado["reason"])
        return False
    codigo = codigo.strip().upper()
    st.session_state.licencia_ok = True
    st.session_state.licencia_trial = False
    st.session_state.licencia_days = resultado["days_left"]
    # Recordar el código en este navegador para no pedirlo en cada visita.
    cookies.guardar("zpProCode", codigo, key="set_pro")
    return True


if not st.session_state.licencia_ok:
    # 1) Código Pro recordado en este navegador
    codigo_guardado = cookies.cookies.get("zpProCode")
    resultado = core.zp_validate(codigo_guardado, ZP_SECRET) if codigo_guardado else {"valid": False}
    if resultado["valid"]:
        st.session_state.licencia_ok = True
        st.session_state.licencia_days = resultado["days_left"]
    else:
        # 2) Prueba gratuita de 14 días (inicio guardado en cookie)
        inicio = core.parse_trial_cookie(cookies.cookies.get("zpTrialStart"))
        if inicio is None:
            inicio = int(time.time() * 1000)
            cookies.guardar("zpTrialStart", inicio, key="set_trial")
        trial = core.trial_status(inicio)
        if trial["active"]:
            st.session_state.licencia_ok = True
            st.session_state.licencia_trial = True
            st.session_state.licencia_days = trial["days_left"]
        else:
            st.session_state.licencia_trial_expired = True


# ── Gate de licencia ─────────────────────────────────────────────────────────

def mostrar_gate() -> bool:
    """Muestra la pantalla de activación. Devuelve True si se activó en esta ejecución."""
    st.title("🎓 RetroTutor")
    st.markdown(
        "Retroalimentación automática con IA para evidencias estudiantiles. "
        "Disponible para suscriptores de **Zajuna Panel Pro**."
    )
    if st.session_state.get("licencia_trial_expired"):
        st.info("Tu prueba gratuita de 14 días terminó. Activa tu código Pro para seguir usando RetroTutor.")
    st.divider()

    col1, col2 = st.columns([2, 1])
    activado = False
    with col1:
        st.subheader("Activa tu acceso")
        st.markdown(
            "Ingresa el código de licencia que recibiste con tu suscripción a Zajuna Panel. "
            "El mismo código que activa la extensión funciona aquí."
        )
        code = st.text_input(
            "Código de licencia", placeholder="ZP-XXX-XXXX-XXXXXX",
            help="Formato: ZP seguido de tres grupos separados por guiones",
        )
        if st.button("Activar", type="primary", disabled=not code):
            activado = activar_pro(code)
            if activado:
                st.success("¡Licencia activada!")

    with col2:
        st.subheader("¿No tienes código?")
        st.markdown(
            "Adquiere **Zajuna Panel Pro** y obtén acceso a:\n"
            "- Dashboard de calificaciones\n"
            "- Portal del Aprendiz\n"
            "- **RetroTutor** (retroalimentación IA)\n"
            "- Exportación CSV\n\n"
            "Desde **$10.000 COP/mes**"
        )
    return activado


if not st.session_state.licencia_ok:
    if not mostrar_gate():
        st.stop()
    st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# App principal (solo si la licencia es válida)
# ══════════════════════════════════════════════════════════════════════════════

# ── Barra lateral ────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Configuración")

    days_left = st.session_state.licencia_days
    if st.session_state.licencia_trial:
        if days_left <= 3:
            st.warning(f"🎟️ Prueba gratuita: te quedan {days_left} día(s).")
        else:
            st.info(f"🎟️ Prueba gratuita: te quedan {days_left} día(s) de acceso completo.")
        with st.expander("¿Ya tienes tu código Pro?"):
            trial_code = st.text_input(
                "Código de licencia", placeholder="ZP-XXX-XXXX-XXXXXX", key="trial_upgrade_code",
            )
            if st.button("Activar", key="trial_upgrade_btn", disabled=not trial_code):
                if activar_pro(trial_code):
                    st.success("¡Licencia Pro activada!")
    elif days_left <= 7:
        st.warning(f"Tu licencia vence en {days_left} día(s).")
    else:
        st.success(f"Licencia activa ({days_left} días restantes)")

    st.subheader("Retroalimentación IA")
    proveedor = st.selectbox("Proveedor", list(core.PROVEEDORES))
    conf = core.PROVEEDORES[proveedor]
    clave_servidor = leer_secreto(conf["env_key"])
    if clave_servidor:
        st.caption("✅ Este servidor ya tiene una API Key configurada.")
        clave_usuario = st.text_input(
            "Usar mi propia API Key (opcional)", type="password", key=f"key_{proveedor}",
        )
        api_key = clave_usuario or clave_servidor
    else:
        api_key = st.text_input(
            f"API Key {proveedor}", type="password", key=f"key_{proveedor}",
            help="Obtén una gratis en openrouter.ai" if proveedor == "OpenRouter" else "platform.openai.com",
        )
    modelo_llm = st.selectbox(
        "Modelo LLM", conf["modelos"],
        help="Los modelos :free no tienen costo en OpenRouter (con límites de uso)",
    )


def generar_para(entrega: dict, espacio: dict) -> bool:
    """Genera la retroalimentación de una entrega. Devuelve False si falló."""
    prompt = core.construir_prompt(
        entrega["estudiante"], espacio["guia"], espacio["rubrica"],
        core.contenido_para_llm(entrega), entrega["tipo"], entrega["veredicto"],
        entrega.get("observaciones", ""),
    )
    try:
        entrega["retroalimentacion"] = core.generar_feedback(api_key, proveedor, modelo_llm, prompt)
        entrega.pop("error", None)
        # Descartar el texto editado anterior para que se muestre el nuevo.
        st.session_state.pop(f"retro_{entrega['id']}", None)
        return True
    except Exception as exc:  # errores de red, clave inválida, límite de uso…
        entrega["error"] = f"No se pudo generar: {exc}"
        return False


def nueva_entrega(**campos) -> dict:
    base = {
        "id": uuid.uuid4().hex, "veredicto": None, "retroalimentacion": None,
        "observaciones": "", "imagen_bytes": None, "archivo_bytes": None, "archivo_mime": None,
    }
    base.update(campos)
    return base


# ── Navegación ───────────────────────────────────────────────────────────────

idx = st.session_state.espacio_idx

if idx is None:
    # ── Vista HOME ───────────────────────────────────────────────────────
    st.title("🎓 RetroTutor")
    st.markdown(
        "**Retroalimentación automática para cualquier evidencia estudiantil:** "
        "documentos, texto, imágenes e infografías."
    )
    st.caption(
        "Los datos viven solo en esta sesión del navegador: al cerrar la pestaña se pierden. "
        "Descarga el .zip o el .xlsx antes de salir."
    )

    with st.expander(
        "➕ Crear espacio de retroalimentación",
        expanded=len(st.session_state.espacios) == 0,
    ):
        nombre_ev = st.text_input(
            "Nombre de la evidencia",
            placeholder="Ej: Infografía Unidad 2, Presentación oral, Ensayo final…",
        )
        tab_file, tab_text = st.tabs(["📎 Subir archivos", "✏️ Escribir texto"])

        with tab_file:
            guia_file = st.file_uploader("Guía de la actividad", type=core.EXT_DOCUMENTO, key="guia_f_crear")
            rubrica_file = st.file_uploader(
                "Rúbrica de evaluación (opcional)", type=core.EXT_DOCUMENTO, key="rub_f_crear",
            )
        with tab_text:
            guia_txt = st.text_area(
                "Guía de la actividad", height=100, key="guia_txt_crear",
                placeholder="Describe la actividad y lo que se espera del estudiante…",
            )
            rubrica_txt = st.text_area(
                "Rúbrica (opcional)", height=100, key="rubrica_txt_crear",
                placeholder="Criterios de evaluación y niveles de desempeño…",
            )

        if st.button("✅ Crear espacio", type="primary", width="stretch", disabled=not nombre_ev):
            try:
                guia = core.extraer_texto(guia_file.getvalue(), guia_file.name) if guia_file else guia_txt
                rubrica = (
                    core.extraer_texto(rubrica_file.getvalue(), rubrica_file.name)
                    if rubrica_file else rubrica_txt
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.espacios.append({
                    "nombre": nombre_ev, "guia": guia or "", "rubrica": rubrica or "", "entregas": [],
                })
                st.session_state.espacio_idx = len(st.session_state.espacios) - 1
                st.rerun()

    if st.session_state.espacios:
        st.divider()
        st.subheader("Tus espacios")
        for i, esp in enumerate(st.session_state.espacios):
            n_ent = len(esp["entregas"])
            n_retro = sum(1 for e in esp["entregas"] if e.get("retroalimentacion"))
            col_name, col_btn = st.columns([4, 1])
            with col_name:
                st.markdown(f"**{esp['nombre']}** — {n_ent} entregas, {n_retro} retroalimentadas")
            with col_btn:
                if st.button("Abrir", key=f"abrir_{i}"):
                    st.session_state.espacio_idx = i
                    st.rerun()

else:
    # ── Vista ESPACIO ────────────────────────────────────────────────────
    espacio = st.session_state.espacios[idx]

    if st.button("← Volver"):
        st.session_state.espacio_idx = None
        st.rerun()

    st.title(f"🎓 {espacio['nombre']}")
    st.caption(
        f"Guía: {'✅' if espacio['guia'].strip() else '❌'} · "
        f"Rúbrica: {'✅' if espacio['rubrica'].strip() else '—'} · "
        f"{len(espacio['entregas'])} entregas"
    )

    # ── Agregar entregas ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Agregar entregas")

    tab_archivos, tab_texto_ev = st.tabs(["📎 Subir archivos", "✏️ Pegar texto"])

    with tab_archivos:
        archivos = st.file_uploader(
            "Subir entregas de estudiantes",
            type=core.TODAS_EXT,
            accept_multiple_files=True,
            key=f"upload_{idx}",
            help="PDF, DOCX, PPTX, TXT, imágenes con OCR (PNG, JPG). "
                 "El nombre del archivo se usa como nombre del estudiante.",
        )
        if archivos and st.button(f"➕ Agregar {len(archivos)} entregas", type="primary", key=f"agregar_{idx}"):
            barra = st.progress(0, text="Procesando entregas…")
            fallidos = []
            for i, arch in enumerate(archivos):
                barra.progress(i / len(archivos), text=f"Procesando {arch.name}…")
                tipo = core.clasificar_archivo(arch.name)
                raw = arch.getvalue()
                try:
                    contenido = core.ocr_imagen(raw) if tipo == "imagen" else core.extraer_texto(raw, arch.name)
                except ValueError as exc:
                    fallidos.append(str(exc))
                    contenido = ""
                espacio["entregas"].append(nueva_entrega(
                    estudiante=Path(arch.name).stem.replace("_", " "),
                    tipo=tipo, contenido=contenido, archivo_nombre=arch.name,
                    imagen_bytes=raw if tipo == "imagen" else None,
                    archivo_bytes=raw, archivo_mime=arch.type or "application/octet-stream",
                ))
            barra.progress(1.0, text="✅ Entregas agregadas")
            if fallidos:
                st.session_state.avisos_carga = fallidos
            st.rerun()
        for aviso in st.session_state.pop("avisos_carga", []):
            st.warning(aviso + " Se agregó sin texto; puedes escribir observaciones manualmente.")

    with tab_texto_ev:
        nombre_txt = st.text_input("Nombre del estudiante", key=f"nom_txt_{idx}", placeholder="Ej: María García")
        texto_pegado = st.text_area(
            "Pegar la entrega del estudiante", height=200, key=f"txt_{idx}",
            placeholder="Pega aquí el texto que el estudiante envió…",
        )
        if st.button("➕ Agregar entrega", key=f"add_txt_{idx}") and texto_pegado:
            espacio["entregas"].append(nueva_entrega(
                estudiante=nombre_txt or "Estudiante", tipo="texto",
                contenido=texto_pegado, archivo_nombre="texto pegado",
            ))
            # Limpiar el formulario para la siguiente entrega
            st.session_state.pop(f"nom_txt_{idx}", None)
            st.session_state.pop(f"txt_{idx}", None)
            st.rerun()

    # ── Lista de entregas ────────────────────────────────────────────────
    if not espacio["entregas"]:
        st.info("Aún no hay entregas. Sube archivos o pega texto.")
    else:
        st.divider()
        sin_veredicto = sum(1 for e in espacio["entregas"] if not e.get("veredicto"))

        st.subheader(f"Calificar entregas ({len(espacio['entregas'])})")
        st.info(
            "**Paso 1:** Revisa cada entrega y marca **Aprobado** o **Deficiente**. "
            "**Paso 2:** Haz clic en **Generar retroalimentación**.",
            icon="👇",
        )

        tipo_label = {"documento": "📄 Documento", "texto": "📝 Texto", "imagen": "🖼️ Imagen"}

        for ent in list(espacio["entregas"]):
            uid = ent["id"]  # clave estable: no se corre al eliminar entregas
            icono = "✅" if ent.get("retroalimentacion") else "⏳" if ent.get("veredicto") else "⬜"

            with st.expander(
                f"{icono} {ent['estudiante']} — {ent['archivo_nombre']}",
                expanded=not ent.get("retroalimentacion"),
            ):
                col_prev, col_ctrl = st.columns([3, 2])

                with col_prev:
                    st.caption(tipo_label.get(ent["tipo"], ent["tipo"]))
                    if ent.get("archivo_bytes"):
                        st.download_button(
                            f"📥 Descargar {ent['archivo_nombre']}",
                            data=ent["archivo_bytes"], file_name=ent["archivo_nombre"],
                            mime=ent.get("archivo_mime") or "application/octet-stream",
                            key=f"dl_{uid}",
                        )
                    if ent["tipo"] == "imagen" and ent.get("imagen_bytes"):
                        st.image(ent["imagen_bytes"], width=400)
                        if ent.get("contenido"):
                            with st.container(border=True):
                                st.caption("Texto extraído (OCR)")
                                st.write(ent["contenido"][:3000])
                    else:
                        with st.container(border=True):
                            st.caption("Contenido extraído")
                            st.write(ent["contenido"][:3000] or "*Sin contenido*")

                with col_ctrl:
                    ent["estudiante"] = st.text_input("Nombre", value=ent["estudiante"], key=f"est_{uid}")

                    st.markdown("**Veredicto** *(requerido)*")
                    ent["veredicto"] = st.radio(
                        "Veredicto", ["Aprobado", "Deficiente"],
                        index={"Aprobado": 0, "Deficiente": 1}.get(ent.get("veredicto")),
                        key=f"ver_{uid}", horizontal=True, label_visibility="collapsed",
                    )

                    if ent["tipo"] == "imagen":
                        ent["observaciones"] = st.text_area(
                            "Describe lo que ves en la imagen", value=ent.get("observaciones", ""),
                            key=f"obs_{uid}", height=80,
                            placeholder="Ej: Buen diseño visual, falta citar fuentes…",
                        )
                    else:
                        ent["observaciones"] = st.text_area(
                            "Observaciones del instructor (opcional)", value=ent.get("observaciones", ""),
                            key=f"obs_{uid}", height=68, placeholder="Notas adicionales…",
                        )

                    btn_label = "🔄 Regenerar" if ent.get("retroalimentacion") else "🚀 Generar retroalimentación"
                    if st.button(
                        btn_label, key=f"gen1_{uid}", width="stretch",
                        disabled=not ent.get("veredicto"),
                        type="primary" if ent.get("veredicto") and not ent.get("retroalimentacion") else "secondary",
                    ):
                        if not api_key:
                            st.error("Ingresa tu API Key en la barra lateral.")
                        else:
                            with st.spinner("Generando…"):
                                generar_para(ent, espacio)
                            st.rerun()

                    if not ent.get("veredicto"):
                        st.caption("↑ Selecciona Aprobado o Deficiente para habilitar")

                if ent.get("error"):
                    st.error(ent["error"])

                if ent.get("retroalimentacion"):
                    st.divider()
                    st.markdown("**Retroalimentación generada** (puedes editarla antes de exportar):")
                    ent["retroalimentacion"] = st.text_area(
                        "Retroalimentación", value=ent["retroalimentacion"], key=f"retro_{uid}",
                        height=200, label_visibility="collapsed",
                    )

                if st.button("🗑️ Eliminar entrega", key=f"del_{uid}"):
                    espacio["entregas"].remove(ent)
                    st.rerun()

        # ── Acciones en lote ─────────────────────────────────────────────
        st.divider()
        pendientes = [e for e in espacio["entregas"] if e.get("veredicto") and not e.get("retroalimentacion")]
        con_retro = [e for e in espacio["entregas"] if e.get("retroalimentacion")]

        if sin_veredicto > 0:
            st.warning(
                f"**{sin_veredicto} entrega(s) sin veredicto.** "
                "Marca Aprobado o Deficiente en cada una para poder generar retroalimentación.",
                icon="⚠️",
            )

        col_gen, col_zip, col_xls = st.columns(3)

        with col_gen:
            if st.button(
                f"🚀 Generar {len(pendientes)} pendientes", type="primary", width="stretch",
                disabled=not pendientes or not api_key,
            ):
                barra = st.progress(0, text="Generando retroalimentaciones…")
                for j, e in enumerate(pendientes):
                    barra.progress(j / len(pendientes), text=f"Retroalimentando {e['estudiante']}…")
                    generar_para(e, espacio)
                barra.progress(1.0, text="✅ Listo")
                st.rerun()

        with col_zip:
            if con_retro:
                st.download_button(
                    f"📦 Descargar .zip ({len(con_retro)})",
                    core.zip_entregas(con_retro),
                    file_name=f"retro_{core.nombre_seguro(espacio['nombre'])}.zip",
                    mime="application/zip", width="stretch",
                )

        with col_xls:
            if con_retro:
                st.download_button(
                    f"📊 Descargar .xlsx ({len(con_retro)})",
                    core.excel_entregas(espacio["entregas"]),
                    file_name=f"retro_{core.nombre_seguro(espacio['nombre'])}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )

        con_error = sum(1 for e in espacio["entregas"] if e.get("error"))
        if con_error:
            st.error(f"{con_error} entrega(s) fallaron al generar. Revisa la clave, el modelo o intenta de nuevo.")
        if not api_key and pendientes:
            st.warning("Ingresa tu API Key en la barra lateral para generar retroalimentaciones.")
