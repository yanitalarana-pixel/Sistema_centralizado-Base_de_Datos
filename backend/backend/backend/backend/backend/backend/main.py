from typing import List, Optional
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.database import engine, get_session, init_db
from backend.integrations import (
    ExcelService,
    GoogleSheetsConnector,
    OdooConnector,
    OutlookNotifier,
)
from backend.models import AuditLog, OrigenDatos, RegistroOperativo, RolUsuario, Usuario
from backend.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)

app = FastAPI(
    title="Núcleo Empresarial Centralizado",
    description="Servidor central con RBAC, KPIs de Dirección e Integraciones ERP/Cloud",
    version="1.0.0",
)


# --- Esquemas Pydantic de Entrada / Salida ---
class RegistroCreate(BaseModel):
    codigo_referencia: str = Field(..., min_length=3, max_length=64)
    area: str = Field(..., min_length=2, max_length=80)
    unidades_meta: int = Field(..., gt=0)
    unidades_producidas: int = Field(..., ge=0)
    unidades_defectuosas: int = Field(default=0, ge=0)
    horas_planificadas: float = Field(..., gt=0)
    horas_reales: float = Field(..., gt=0)
    observaciones: Optional[str] = None


class KPIResponse(BaseModel):
    total_registros: int
    unidades_meta_totales: int
    unidades_producidas_totales: int
    unidades_conformes_totales: int
    eficacia_pct: float
    eficiencia_pct: float
    calidad_pct: float
    productividad_global_pct: float
    unidades_por_hora_hombre: float
    desglose_por_area: List[dict]


# --- Evento de Arranque: Creación de Tablas y Semilla Inicial ---
@app.on_event("startup")
def on_startup():
    init_db()
    with Session(engine) as session:
        existe_admin = session.exec(
            select(Usuario).where(Usuario.username == "direccion")
        ).first()
        if not existe_admin:
            usuarios_iniciales = [
                Usuario(
                    username="direccion",
                    email="direccion@empresa.com",
                    nombre_completo="Directora General",
                    hashed_password=hash_password("Direccion2026!"),
                    rol=RolUsuario.DIRECCION,
                ),
                Usuario(
                    username="trabajador",
                    email="operador@empresa.com",
                    nombre_completo="Operador de Planta",
                    hashed_password=hash_password("Trabajador2026!"),
                    rol=RolUsuario.TRABAJADOR,
                ),
            ]
            session.add_all(usuarios_iniciales)
            session.commit()


# --- Función Interna de Auditoría ---
def registrar_auditoria(
    session: Session, usuario_id: int, accion: str, entidad: str, detalle: str
):
    log = AuditLog(
        usuario_id=usuario_id, accion=accion, entidad=entidad, detalle=detalle
    )
    session.add(log)


# =====================================================================
# ENDPOINTS DE AUTENTICACIÓN
# =====================================================================
@app.post("/api/v1/auth/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    user = session.exec(
        select(Usuario).where(Usuario.username == form_data.username)
    ).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = create_access_token(
        data={
            "sub": user.username,
            "rol": user.rol.value,
            "nombre": user.nombre_completo,
        }
    )
    registrar_auditoria(
        session, user.id, "LOGIN", "Usuario", f"Inicio de sesión exitoso ({user.rol.value})"
    )
    session.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "rol": user.rol.value,
        "nombre_completo": user.nombre_completo,
    }


# =====================================================================
# ENDPOINTS OPERATIVOS (Accesibles por Trabajador y Dirección)
# =====================================================================
@app.post("/api/v1/operaciones/registro")
def crear_registro_operativo(
    payload: RegistroCreate,
    background_tasks: BackgroundTasks,
    current_user: Usuario = Depends(
        require_roles([RolUsuario.TRABAJADOR, RolUsuario.DIRECCION])
    ),
    session: Session = Depends(get_session),
):
    if payload.unidades_defectuosas > payload.unidades_producidas:
        raise HTTPException(
            status_code=400,
            detail="Las unidades defectuosas no pueden superar a las unidades producidas.",
        )

    duplicado = session.exec(
        select(RegistroOperativo).where(
            RegistroOperativo.codigo_referencia == payload.codigo_referencia
        )
    ).first()
    if duplicado:
        raise HTTPException(
            status_code=409,
            detail=f"El folio '{payload.codigo_referencia}' ya existe. No se permiten duplicados.",
        )

    nuevo = RegistroOperativo(
        **payload.model_dump(),
        origen=OrigenDatos.MANUAL,
        creado_por_id=current_user.id,
    )
    session.add(nuevo)
    registrar_auditoria(
        session,
        current_user.id,
        "CREAR_REGISTRO",
        "RegistroOperativo",
        f"Folio {nuevo.codigo_referencia} registrado en área {nuevo.area}",
    )
    session.commit()
    session.refresh(nuevo)

    # Verificar calidad y disparar alerta a Outlook en segundo plano si es menor a 90%
    if nuevo.unidades_producidas > 0:
        calidad = (
            (nuevo.unidades_producidas - nuevo.unidades_defectuosas)
            / nuevo.unidades_producidas
        ) * 100
        if calidad < 90.0:
            background_tasks.add_task(
                OutlookNotifier.send_quality_alert,
                nuevo.codigo_referencia,
                nuevo.area,
                calidad,
            )

    return {"mensaje": "Registro guardado con éxito", "id": nuevo.id}


@app.get("/api/v1/operaciones/mis-registros")
def listar_mis_registros(
    current_user: Usuario = Depends(
        require_roles([RolUsuario.TRABAJADOR, RolUsuario.DIRECCION])
    ),
    session: Session = Depends(get_session),
):
    stmt = (
        select(RegistroOperativo)
        .where(
            RegistroOperativo.creado_por_id == current_user.id,
            RegistroOperativo.is_active == True,
        )
        .order_by(RegistroOperativo.created_at.desc())
    )
    return session.exec(stmt).all()


@app.post("/api/v1/operaciones/importar-excel")
async def importar_excel(
    file: UploadFile = File(...),
    current_user: Usuario = Depends(
        require_roles([RolUsuario.TRABAJADOR, RolUsuario.DIRECCION])
    ),
    session: Session = Depends(get_session),
):
    contenido = await file.read()
    try:
        filas = ExcelService.parse_uploaded_excel(contenido)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    insertados = 0
    omitidos = 0
    for item in filas:
        existe = session.exec(
            select(RegistroOperativo).where(
                RegistroOperativo.codigo_referencia == item["codigo_referencia"]
            )
        ).first()
        if existe:
            omitidos += 1
            continue
        reg = RegistroOperativo(
            **item, origen=OrigenDatos.EXCEL, creado_por_id=current_user.id
        )
        session.add(reg)
        insertados += 1

    registrar_auditoria(
        session,
        current_user.id,
        "IMPORTACION_EXCEL",
        "RegistroOperativo",
        f"Insertados: {insertados}, Omitidos por duplicidad: {omitidos}",
    )
    session.commit()
    return {"insertados": insertados, "omitidos_por_duplicidad": omitidos}


# =====================================================================
# ENDPOINTS EXCLUSIVOS DE DIRECCIÓN (KPIs, Auditoría, Sincronizaciones)
# =====================================================================
def _calcular_kpis_internos(registros: List[RegistroOperativo]) -> KPIResponse:
    if not registros:
        return KPIResponse(
            total_registros=0,
            unidades_meta_totales=0,
            unidades_producidas_totales=0,
            unidades_conformes_totales=0,
            eficacia_pct=0.0,
            eficiencia_pct=0.0,
            calidad_pct=0.0,
            productividad_global_pct=0.0,
            unidades_por_hora_hombre=0.0,
            desglose_por_area=[],
        )

    meta_total = sum(r.unidades_meta for r in registros)
    prod_total = sum(r.unidades_producidas for r in registros)
    def_total = sum(r.unidades_defectuosas for r in registros)
    conformes_total = prod_total - def_total
    h_plan = sum(r.horas_planificadas for r in registros)
    h_real = sum(r.horas_reales for r in registros)

    # 1. Eficacia: Logro de producción respecto a la meta
    eficacia = (prod_total / meta_total) * 100 if meta_total > 0 else 0.0

    # 2. Eficiencia: Velocidad real comparada con velocidad estándar planificada
    tasa_real = prod_total / h_real if h_real > 0 else 0.0
    tasa_ideal = meta_total / h_plan if h_plan > 0 else 0.0
    eficiencia = (tasa_real / tasa_ideal) * 100 if tasa_ideal > 0 else 0.0

    # 3. Calidad: Proporción de unidades libres de defectos
    calidad = (conformes_total / prod_total) * 100 if prod_total > 0 else 0.0

    # 4. Productividad Global (OEE): Eficacia x Eficiencia x Calidad
    productividad = ((eficacia / 100.0) * (eficiencia / 100.0) * (calidad / 100.0)) * 100

    # Agrupación por área
    areas_dict = {}
    for r in registros:
        a = areas_dict.setdefault(
            r.area, {"meta": 0, "prod": 0, "def": 0, "h_plan": 0.0, "h_real": 0.0}
        )
        a["meta"] += r.unidades_meta
        a["prod"] += r.unidades_producidas
        a["def"] += r.unidades_defectuosas
        a["h_plan"] += r.horas_planificadas
        a["h_real"] += r.horas_reales

    desglose = []
    for nombre_area, vals in areas_dict.items():
        ef_area = (vals["prod"] / vals["meta"] * 100) if vals["meta"] > 0 else 0.0
        cal_area = (
            ((vals["prod"] - vals["def"]) / vals["prod"] * 100)
            if vals["prod"] > 0
            else 0.0
        )
        t_real_a = vals["prod"] / vals["h_real"] if vals["h_real"] > 0 else 0.0
        t_plan_a = vals["meta"] / vals["h_plan"] if vals["h_plan"] > 0 else 0.0
        efic_area = (t_real_a / t_plan_a * 100) if t_plan_a > 0 else 0.0
        desglose.append({
            "area": nombre_area,
            "unidades_producidas": vals["prod"],
            "eficacia_pct": round(ef_area, 2),
            "eficiencia_pct": round(efic_area, 2),
            "calidad_pct": round(cal_area, 2),
        })

    return KPIResponse(
        total_registros=len(registros),
        unidades_meta_totales=meta_total,
        unidades_producidas_totales=prod_total,
        unidades_conformes_totales=conformes_total,
        eficacia_pct=round(eficacia, 2),
        eficiencia_pct=round(eficiencia, 2),
        calidad_pct=round(calidad, 2),
        productividad_global_pct=round(productividad, 2),
        unidades_por_hora_hombre=round(conformes_total / h_real, 2) if h_real > 0 else 0.0,
        desglose_por_area=desglose,
    )


@app.get("/api/v1/direccion/kpis", response_model=KPIResponse)
def obtener_kpis_direccion(
    current_user: Usuario = Depends(require_roles([RolUsuario.DIRECCION])),
    session: Session = Depends(get_session),
):
    registros = session.exec(
        select(RegistroOperativo).where(RegistroOperativo.is_active == True)
    ).all()
    return _calcular_kpis_internos(registros)


@app.get("/api/v1/direccion/exportar-excel")
def exportar_reporte_ejecutivo(
    current_user: Usuario = Depends(require_roles([RolUsuario.DIRECCION])),
    session: Session = Depends(get_session),
):
    registros = session.exec(
        select(RegistroOperativo).where(RegistroOperativo.is_active == True)
    ).all()
    kpis = _calcular_kpis_internos(registros).model_dump()
    filas_dict = [r.model_dump() for r in registros]
    archivo_bytes = ExcelService.build_executive_report(kpis, filas_dict)

    registrar_auditoria(
        session,
        current_user.id,
        "EXPORTAR_EXCEL_EJECUTIVO",
        "Reporte",
        "Descarga de reporte ejecutivo de KPIs",
    )
    session.commit()

    return StreamingResponse(
        iter([archivo_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Reporte_Direccion_KPIs.xlsx"},
    )


@app.post("/api/v1/direccion/sincronizar/{fuente}")
def sincronizar_fuente_externa(
    fuente: str,
    current_user: Usuario = Depends(require_roles([RolUsuario.DIRECCION])),
    session: Session = Depends(get_session),
):
    try:
        if fuente == "odoo":
            datos = OdooConnector.fetch_production_orders()
            origen_enum = OrigenDatos.ODOO
        elif fuente == "google_sheets":
            datos = GoogleSheetsConnector.fetch_sheet_records()
            origen_enum = OrigenDatos.GOOGLE_SHEETS
        else:
            raise HTTPException(status_code=400, detail="Fuente externa no soportada")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al conectar con {fuente}: {exc}")

    nuevos = 0
    for d in datos:
        existe = session.exec(
            select(RegistroOperativo).where(
                RegistroOperativo.codigo_referencia == d["codigo_referencia"]
            )
        ).first()
        if not existe:
            session.add(
                RegistroOperativo(**d, origen=origen_enum, creado_por_id=current_user.id)
            )
            nuevos += 1

    registrar_auditoria(
        session,
        current_user.id,
        f"SYNC_{fuente.upper()}",
        "IntegracionExterna",
        f"Se importaron {nuevos} registros nuevos desde {fuente}",
    )
    session.commit()
    return {"fuente": fuente, "nuevos_registros_sincronizados": nuevos}


@app.get("/api/v1/direccion/auditoria")
def consultar_bitacora_auditoria(
    current_user: Usuario = Depends(require_roles([RolUsuario.DIRECCION])),
    session: Session = Depends(get_session),
):
    logs = session.exec(
        select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(100)
    ).all()
    return logs
