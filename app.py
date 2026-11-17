import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime

st.set_page_config(page_title="Sistema Centralizado", layout="wide")

# 1. Base de Datos Automática
def obtener_conexion():
    return sqlite3.connect("sistema_central.db", check_same_thread=False)

def inicializar_bd():
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registros (
            folio TEXT PRIMARY KEY,
            area TEXT,
            meta INTEGER,
            producidas INTEGER,
            defectuosas INTEGER,
            fecha TEXT
        )
    ''')
    conn.commit()
    conn.close()

inicializar_bd()

# 2. Control de Acceso
if "rol" not in st.session_state:
    st.session_state["rol"] = None

# 3. Pantalla de Iniciar Sesión
if st.session_state["rol"] is None:
    st.title("🔐 Acceso al Sistema Central")
    usuario = st.text_input("Usuario (Prueba con: direccion o trabajador)")
    clave = st.text_input("Contraseña (Prueba con: 1234)", type="password")
    
    if st.button("Entrar al Sistema"):
        if usuario == "direccion" and clave == "1234":
            st.session_state["rol"] = "direccion"
            st.rerun()
        elif usuario == "trabajador" and clave == "1234":
            st.session_state["rol"] = "trabajador"
            st.rerun()
        else:
            st.error("Credenciales incorrectas")

# 4. Pantallas de Trabajo
else:
    st.sidebar.write(f"👤 Conectado como: **{st.session_state['rol'].upper()}**")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state["rol"] = None
        st.rerun()

    # MÓDULO TRABAJADOR (Ambos lo ven)
    st.title("🛠️ Captura de Productividad")
    with st.form("registro"):
        c1, c2 = st.columns(2)
        folio = c1.text_input("Folio Único (Ej. F-001)")
        area = c2.selectbox("Área", ["Ensamble", "Calidad", "Empaque"])
        
        c3, c4, c5 = st.columns(3)
        meta = c3.number_input("Unidades Meta", min_value=1, value=100)
        prod = c4.number_input("Unidades Producidas", min_value=0, value=90)
        defec = c5.number_input("Unidades Defectuosas", min_value=0, value=2)
        
        if st.form_submit_button("Guardar en Base de Datos"):
            if folio:
                try:
                    conn = obtener_conexion()
                    cursor = conn.cursor()
                    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
                    cursor.execute("INSERT INTO registros VALUES (?,?,?,?,?,?)", 
                                 (folio, area, meta, prod, defec, fecha))
                    conn.commit()
                    st.success(f"✅ Registro {folio} guardado exitosamente.")
                except sqlite3.IntegrityError:
                    st.error("❌ Error: Ese folio ya existe. Evitando duplicados.")
                finally:
                    conn.close()
            else:
                st.warning("Escribe un número de folio")

    # MÓDULO DIRECCIÓN (Oculto para el trabajador)
    if st.session_state["rol"] == "direccion":
        st.divider()
        st.title("📊 Panel Directivo (KPIs)")
        
        conn = obtener_conexion()
        df = pd.read_sql_query("SELECT * FROM registros", conn)
        conn.close()
        
        if not df.empty:
            meta_total = df["meta"].sum()
            prod_total = df["producidas"].sum()
            defec_total = df["defectuosas"].sum()
            
            eficacia = (prod_total / meta_total * 100) if meta_total > 0 else 0
            calidad = ((prod_total - defec_total) / prod_total * 100) if prod_total > 0 else 0
            
            k1, k2, k3 = st.columns(3)
            k1.metric("🎯 Eficacia Global", f"{eficacia:.1f}%")
            k2.metric("💎 Calidad Global", f"{calidad:.1f}%")
            k3.metric("📋 Total de Registros", len(df))
            
            st.subheader("Base de Datos en Tiempo Real")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Aún no hay datos para calcular indicadores.")
