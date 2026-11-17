import os
import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Sistema Empresarial Centralizado",
    page_icon="🏢",
    layout="wide",
)

# Inicializar estado de sesión
for key in ["token", "rol", "nombre_completo"]:
    if key not in st.session_state:
        st.session_state[key] = None


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state['token']}"}


def cerrar_sesion():
    st.session_state["token"] = None
    st.session_state["rol"] = None
    st.session_state["nombre_completo"] = None
    st.rerun()


# =====================================================================
# VISTA 1: INICIO DE SESIÓN UNIFICADO
# =====================================================================
def vista_login():
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.title("🔐 Acceso al Núcleo Empresarial")
        st.caption("Autenticación centralizada con Control de Acceso Basado en Roles (RBAC)")

        with st.form("form_login"):
            username = st.text_input("Usuario", placeholder="Ej. direccion o trabajador")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Ingresar al Sistema", use_container_width=True)

            if submit:
                try:
                    resp = requests.post(
                        f"{API_BASE_URL}/api/v1/auth/login",
                        data={"username": username, "password": password},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state["token"] = data["access_token"]
                        st.session_state["rol"] = data["rol"]
                        st.session_state["nombre_completo"] = data["nombre_completo"]
                        st.rerun()
                    else:
                        st.error(resp.json().get("detail", "Error de autenticación"))
                except requests.RequestException:
                    st.error("No se pudo conectar con el Servidor Central (FastAPI).")

        st.info(
            "**Credenciales de prueba preconfiguradas:**\n"
            "- **Dirección:** Usuario `direccion` / Clave `Direccion2026!`\n"
            "- **Trabajador:** Usuario `trabajador` / Clave `Trabajador2026!`"
        )


# =====================================================================
# VISTA 2: PANEL OPERATIVO (Para Trabajadores y Dirección)
# =====================================================================
def vista_operaciones():
    st.title("🛠️ Módulo de Operaciones Diarias")
    st.write(f"Operador activo: **{st.session_state['nombre_completo']}**")

    tab_captura, tab_excel, tab_historial = st.tabs([
        "📝 Registrar Orden / Lote",
        "📥 Importación Masiva Excel",
        "📋 Mis Registros Capturados",
    ])

    with tab_captura:
        with st.form("form_registro_operativo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            codigo = c1.text_input("Folio / Código de Referencia Único *", placeholder="PROD-2026-001")
            area = c2.selectbox(
                "Área Operativa *",
                ["Ensamble", "Logística", "Control de Calidad", "Empaque", "Mantenimiento"],
            )

            c3, c4, c5 = st.columns(3)
            u_meta = c3.number_input("Unidades Meta *", min_value=1, value=100)
            u_prod = c4.number_input("Unidades Producidas *", min_value=0, value=95)
            u_def = c5.number_input("Unidades Defectuosas", min_value=0, value=2)

            c6, c7 = st.columns(2)
            h_plan = c6.number_input("Horas Planificadas *", min_value=0.5, value=8.0, step=0.5)
            h_real = c7.number_input("Horas Reales Invertidas *", min_value=0.5, value=7.5, step=0.5)

            obs = st.text_area("Observaciones de turno")
            guardar = st.form_submit_button("Guardar en Base de Datos Central", use_container_width=True)

            if guardar:
                payload = {
                    "codigo_referencia": codigo.strip(),
                    "area": area,
                    "unidades_meta": u_meta,
                    "unidades_producidas": u_prod,
                    "unidades_defectuosas": u_def,
                    "horas_planificadas": h_plan,
                    "horas_reales": h_real,
                    "observaciones": obs,
                }
                r = requests.post(
                    f"{API_BASE_URL}/api/v1/operaciones/registro",
                    json=payload,
                    headers=auth_headers(),
                    timeout=10,
                )
                if r.status_code == 200:
                    st.success("✅ Registro almacenado con integridad ACID en PostgreSQL.")
                else:
                    st.error(f"❌ Error: {r.json().get('detail', 'Fallo desconocido')}")

    with tab_excel:
        st.subheader("Carga de Plantillas Operativas (.xlsx)")
        st.caption(
            "Columnas requeridas: codigo_referencia, area, unidades_meta, "
            "unidades_producidas, unidades_defectuosas, horas_planificadas, horas_reales"
        )
        archivo = st.file_uploader("Selecciona un archivo Excel", type=["xlsx"])
        if archivo and st.button("Procesar e Insertar en PostgreSQL"):
            files = {"file": (archivo.name, archivo.getvalue(), archivo.type)}
            r = requests.post(
                f"{API_BASE_URL}/api/v1/operaciones/importar-excel",
                files=files,
                headers=auth_headers(),
                timeout=30,
            )
            if r.status_code == 200:
                res = r.json()
                st.success(
                    f"Importación completada: {res['insertados']} nuevos registros insertados "
                    f"({res['omitidos_por_duplicidad']} omitidos por folio duplicado)."
                )
            else:
                st.error(r.json().get("detail", "Error al procesar el archivo Excel"))

    with tab_historial:
        r = requests.get(
            f"{API_BASE_URL}/api/v1/operaciones/mis-registros",
            headers=auth_headers(),
            timeout=10,
        )
        if r.status_code == 200:
            datos = r.json()
            if datos:
                df = pd.DataFrame(datos)[
                    [
                        "codigo_referencia",
                        "area",
                        "unidades_meta",
                        "unidades_producidas",
                        "unidades_defectuosas",
                        "horas_reales",
                        "origen",
                        "created_at",
                    ]
                ]
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Aún no has capturado registros operativos.")


# =====================================================================
# VISTA 3: PANEL DE CONTROL DE DIRECCIÓN (Oculto para Trabajadores)
# =====================================================================
def vista_direccion_kpis():
    st.title("📊 Centro de Mando Directivo: Indicadores e Integraciones")
    st.caption(
        "Vista restringida exclusivamente al rol Dirección. Monitoreo en tiempo real de "
        "Productividad, Eficacia, Eficiencia y Calidad."
    )

    resp = requests.get(
        f"{API_BASE_URL}/api/v1/direccion/kpis", headers=auth_headers(), timeout=10
    )
    if resp.status_code != 200:
        st.error("Acceso denegado o error al consultar KPIs.")
        return

    kpis = resp.json()

    # --- Tarjetas de Indicadores Principales ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        label="🎯 Eficacia (Cumplimiento Meta)",
        value=f"{kpis['eficacia_pct']}%",
        help="(Unidades Producidas / Unidades Meta) × 100",
    )
    k2.metric(
        label="⚡ Eficiencia (Uso del Tiempo)",
        value=f"{kpis['eficiencia_pct']}%",
        help="(Velocidad Real / Velocidad Planificada) × 100",
    )
    k3.metric(
        label="💎 Calidad (Piezas Conformes)",
        value=f"{kpis['calidad_pct']}%",
        help="((Producidas - Defectuosas) / Producidas) × 100",
    )
    k4.metric(
        label="🚀 Productividad Global (OEE)",
        value=f"{kpis['productividad_global_pct']}%",
        delta=f"{kpis['unidades_por_hora_hombre']} u. conformes / hora",
        help="Eficacia × Eficiencia × Calidad",
    )

    st.divider()

    # --- Gráficos Comparativos por Área ---
    col_graf, col_sync = st.columns([2, 1])

    with col_graf:
        st.subheader("Desempeño Comparativo por Área Operativa")
        if kpis["desglose_por_area"]:
            df_areas = pd.DataFrame(kpis["desglose_por_area"]).set_index("area")
            st.bar_chart(df_areas[["eficacia_pct", "eficiencia_pct", "calidad_pct"]])
            st.dataframe(df_areas, use_container_width=True)
        else:
            st.warning("No hay datos registrados todavía para graficar indicadores.")

    with col_sync:
        st.subheader("🔗 Ecosistema de Integraciones")

        if st.button("🔄 Sincronizar Órdenes desde Odoo ERP", use_container_width=True):
            r_odoo = requests.post(
                f"{API_BASE_URL}/api/v1/direccion/sincronizar/odoo",
                headers=auth_headers(),
                timeout=20,
            )
            if r_odoo.status_code == 200:
                st.success(f"Nuevos de Odoo: {r_odoo.json()['nuevos_registros_sincronizados']}")
            else:
                st.warning(r_odoo.json().get("detail"))

        if st.button("📗 Sincronizar desde Google Sheets", use_container_width=True):
            r_gs = requests.post(
                f"{API_BASE_URL}/api/v1/direccion/sincronizar/google_sheets",
                headers=auth_headers(),
                timeout=20,
            )
            if r_gs.status_code == 200:
                st.success(f"Nuevos de Sheets: {r_gs.json()['nuevos_registros_sincronizados']}")
            else:
                st.warning(r_gs.json().get("detail"))

        st.markdown("---")
        st.subheader("📤 Exportación Ejecutiva")
        r_excel = requests.get(
            f"{API_BASE_URL}/api/v1/direccion/exportar-excel",
            headers=auth_headers(),
            timeout=15,
        )
        if r_excel.status_code == 200:
            st.download_button(
                label="📊 Descargar Reporte Oficial (.xlsx)",
                data=r_excel.content,
                file_name="Reporte_Direccion_KPIs.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.divider()

    # --- Inspector de Auditoría y Seguridad ---
    with st.expander("🛡️ Bitácora de Auditoría y Trazabilidad del Servidor"):
        r_logs = requests.get(
            f"{API_BASE_URL}/api/v1/direccion/auditoria",
            headers=auth_headers(),
            timeout=10,
        )
        if r_logs.status_code == 200 and r_logs.json():
            st.dataframe(pd.DataFrame(r_logs.json()), use_container_width=True)


# =====================================================================
# ENRUTADOR PRINCIPAL POR ROLES (st.navigation)
# =====================================================================
if st.session_state["token"] is None:
    pg = st.navigation([st.Page(vista_login, title="Iniciar Sesión", icon="🔐")])
else:
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state['nombre_completo']}")
        st.caption(f"Rol activo: **{st.session_state['rol'].upper()}**")
        if st.button("Cerrar Sesión", use_container_width=True):
            cerrar_sesion()

    if st.session_state["rol"] == "trabajador":
        # El trabajador jamás ve ni puede navegar al panel de KPIs de dirección
        pg = st.navigation([
            st.Page(vista_operaciones, title="Operaciones de Planta", icon="🛠️"),
        ])
    elif st.session_state["rol"] == "direccion":
        pg = st.navigation([
            st.Page(vista_direccion_kpis, title="KPIs de Dirección", icon="📊"),
            st.Page(vista_operaciones, title="Captura e Importación", icon="🛠️"),
        ])

pg.run()
