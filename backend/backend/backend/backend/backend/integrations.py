import io
import os
import xmlrpc.client
from typing import Any, Dict, List
import gspread
import msal
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
import pandas as pd
import requests
from google.oauth2.service_account import Credentials

from backend.config import settings


# =====================================================================
# 1. PROCESADOR EXCEL (Importación validada y Reportes Ejecutivos)
# =====================================================================
class ExcelService:
    REQUIRED_COLUMNS = {
        "codigo_referencia",
        "area",
        "unidades_meta",
        "unidades_producidas",
        "unidades_defectuosas",
        "horas_planificadas",
        "horas_reales",
    }

    @classmethod
    def parse_uploaded_excel(cls, file_bytes: bytes) -> List[Dict[str, Any]]:
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
        df.columns = [str(c).strip().lower() for c in df.columns]

        missing = cls.REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"El archivo Excel no contiene las columnas: {missing}")

        df = df.dropna(subset=["codigo_referencia", "area"])
        registros = []
        for _, row in df.iterrows():
            registros.append({
                "codigo_referencia": str(row["codigo_referencia"]).strip(),
                "area": str(row["area"]).strip(),
                "unidades_meta": int(row["unidades_meta"]),
                "unidades_producidas": int(row["unidades_producidas"]),
                "unidades_defectuosas": int(row.get("unidades_defectuosas", 0)),
                "horas_planificadas": float(row["horas_planificadas"]),
                "horas_reales": float(row["horas_reales"]),
                "observaciones": str(row.get("observaciones", "Importado desde Excel")),
            })
        return registros

    @staticmethod
    def build_executive_report(kpis: Dict[str, Any], registros: List[Dict[str, Any]]) -> bytes:
        wb = openpyxl.Workbook()
        ws_kpi = wb.active
        ws_kpi.title = "Resumen_Direccion"

        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=11)

        ws_kpi["A1"] = "REPORTE EJECUTIVO DE INDICADORES CLAVE (DIRECCIÓN)"
        ws_kpi["A1"].font = Font(bold=True, size=14)

        headers_resumen = ["Indicador", "Valor (%)", "Fórmula Aplicada"]
        ws_kpi.append([])
        ws_kpi.append(headers_resumen)
        for col_num in range(1, 4):
            cell = ws_kpi.cell(row=3, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        filas_kpi = [
            ["Eficacia", kpis["eficacia_pct"], "(Unidades Producidas / Unidades Meta) * 100"],
            ["Eficiencia", kpis["eficiencia_pct"], "( Tasa Real / Tasa Planificada ) * 100"],
            ["Calidad", kpis["calidad_pct"], "((Producidas - Defectuosas) / Producidas) * 100"],
            ["Productividad Global (OEE)", kpis["productividad_global_pct"], "Eficacia * Eficiencia * Calidad"],
        ]
        for fila in filas_kpi:
            ws_kpi.append(fila)

        # Segunda pestaña con el detalle operativo
        ws_det = wb.create_sheet(title="Base_Operativa")
        if registros:
            cols = list(registros[0].keys())
            ws_det.append(cols)
            for col_num in range(1, len(cols) + 1):
                c = ws_det.cell(row=1, column=col_num)
                c.fill = header_fill
                c.font = header_font
            for r in registros:
                ws_det.append([r[k] for k in cols])

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()


# =====================================================================
# 2. CONECTOR ODOO ERP (XML-RPC Nativo)
# =====================================================================
class OdooConnector:
    @staticmethod
    def fetch_production_orders() -> List[Dict[str, Any]]:
        if not all([settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_USER, settings.ODOO_PASSWORD]):
            raise RuntimeError("Credenciales de Odoo no configuradas en el archivo .env")

        common = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(
            settings.ODOO_DB, settings.ODOO_USER, settings.ODOO_PASSWORD, {}
        )
        if not uid:
            raise PermissionError("Fallo de autenticación contra Odoo XML-RPC")

        models = xmlrpc.client.ServerProxy(f"{settings.ODOO_URL}/xmlrpc/2/object")
        records = models.execute_kw(
            settings.ODOO_DB,
            uid,
            settings.ODOO_PASSWORD,
            "mrp.production",
            "search_read",
            [[["state", "=", "done"]]],
            {"fields": ["name", "product_qty", "qty_producing"], "limit": 50},
        )

        resultados = []
        for rec in records:
            meta = max(int(rec.get("product_qty", 1)), 1)
            prod = int(rec.get("qty_producing", meta))
            resultados.append({
                "codigo_referencia": f"ODOO-{rec['name']}",
                "area": "Manufactura Odoo",
                "unidades_meta": meta,
                "unidades_producidas": prod,
                "unidades_defectuosas": 0,
                "horas_planificadas": 8.0,
                "horas_reales": 8.0,
                "observaciones": "Sincronizado vía XML-RPC desde Odoo",
            })
        return resultados


# =====================================================================
# 3. CONECTOR GOOGLE SHEETS (Service Account)
# =====================================================================
class GoogleSheetsConnector:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    @classmethod
    def fetch_sheet_records(cls) -> List[Dict[str, Any]]:
        if not settings.GOOGLE_SHEETS_CREDENTIALS_JSON or not os.path.exists(
            settings.GOOGLE_SHEETS_CREDENTIALS_JSON
        ):
            raise RuntimeError("Archivo JSON de Google Service Account no encontrado")

        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SHEETS_CREDENTIALS_JSON, scopes=cls.SCOPES
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(settings.GOOGLE_SHEET_ID).sheet1
        raw_rows = sheet.get_all_records()

        registros = []
        for row in raw_rows:
            registros.append({
                "codigo_referencia": f"GS-{row['codigo_referencia']}",
                "area": str(row["area"]),
                "unidades_meta": int(row["unidades_meta"]),
                "unidades_producidas": int(row["unidades_producidas"]),
                "unidades_defectuosas": int(row.get("unidades_defectuosas", 0)),
                "horas_planificadas": float(row["horas_planificadas"]),
                "horas_reales": float(row["horas_reales"]),
                "observaciones": "Sincronizado desde Google Sheets",
            })
        return registros


# =====================================================================
# 4. CONECTOR MICROSOFT OUTLOOK (Graph API + OAuth2 MSAL)
# =====================================================================
class OutlookNotifier:
    @staticmethod
    def send_quality_alert(codigo: str, area: str, calidad_obtenida: float) -> bool:
        if not all([
            settings.AZURE_TENANT_ID,
            settings.AZURE_CLIENT_ID,
            settings.AZURE_CLIENT_SECRET,
            settings.OUTLOOK_SENDER_EMAIL,
            settings.OUTLOOK_DIRECTOR_EMAIL,
        ]):
            # Si aún no se dan de alta las credenciales en Azure, registra en consola sin bloquear la app
            print(f"[ALERTA OUTLOOK SIMULADA] Folio {codigo} ({area}) cayó a {calidad_obtenida:.1f}% de calidad.")
            return False

        authority = f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}"
        app = msal.ConfidentialClientApplication(
            settings.AZURE_CLIENT_ID,
            authority=authority,
            client_credential=settings.AZURE_CLIENT_SECRET,
        )
        token_result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        access_token = token_result.get("access_token")
        if not access_token:
            return False

        endpoint = f"https://graph.microsoft.com/v1.0/users/{settings.OUTLOOK_SENDER_EMAIL}/sendMail"
        payload = {
            "message": {
                "subject": f"⚠️ Alerta de Calidad en {area} - Folio {codigo}",
                "body": {
                    "contentType": "HTML",
                    "content": (
                        f"<h3>Alerta Automática del Sistema Central</h3>"
                        f"<p>El registro <b>{codigo}</b> en el área <b>{area}</b> reportó un índice de "
                        f"calidad de <b>{calidad_obtenida:.2f}%</b>, inferior al umbral mínimo aceptable (90%).</p>"
                    ),
                },
                "toRecipients": [
                    {"emailAddress": {"address": settings.OUTLOOK_DIRECTOR_EMAIL}}
                ],
            },
            "saveToSentItems": "true",
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        return resp.status_code == 202
