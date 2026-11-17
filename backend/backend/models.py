from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from sqlalchemy import CheckConstraint, Column, DateTime
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RolUsuario(str, Enum):
    TRABAJADOR = "trabajador"
    DIRECCION = "direccion"


class OrigenDatos(str, Enum):
    MANUAL = "captura_manual"
    EXCEL = "importacion_excel"
    GOOGLE_SHEETS = "google_sheets"
    ODOO = "odoo_erp"


class Usuario(SQLModel, table=True):
    __tablename__ = "usuarios"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    email: str = Field(unique=True, max_length=120)
    nombre_completo: str = Field(max_length=120)
    hashed_password: str
    rol: RolUsuario = Field(default=RolUsuario.TRABAJADOR)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class RegistroOperativo(SQLModel, table=True):
    __tablename__ = "registros_operativos"
    __table_args__ = (
        CheckConstraint("unidades_meta > 0", name="check_meta_positiva"),
        CheckConstraint("unidades_producidas >= 0", name="check_producidas_no_neg"),
        CheckConstraint("unidades_defectuosas >= 0", name="check_defectos_no_neg"),
        CheckConstraint(
            "unidades_defectuosas <= unidades_producidas",
            name="check_defectos_menor_igual_producidas",
        ),
        CheckConstraint("horas_planificadas > 0", name="check_horas_plan_positivas"),
        CheckConstraint("horas_reales > 0", name="check_horas_reales_positivas"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    codigo_referencia: str = Field(
        index=True, unique=True, max_length=64,
        description="Folio único para impedir registros duplicados"
    )
    area: str = Field(index=True, max_length=80)
    unidades_meta: int
    unidades_producidas: int
    unidades_defectuosas: int = Field(default=0)
    horas_planificadas: float
    horas_reales: float
    origen: OrigenDatos = Field(default=OrigenDatos.MANUAL)
    observaciones: Optional[str] = Field(default=None, max_length=500)

    # Trazabilidad y Auditoría
    creado_por_id: int = Field(foreign_key="usuarios.id")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    accion: str = Field(max_length=100)
    entidad: str = Field(max_length=80)
    detalle: str = Field(max_length=1000)
    timestamp: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
