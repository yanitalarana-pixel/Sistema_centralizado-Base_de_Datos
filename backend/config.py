from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://admin_empresa:ClaveSegura2026!@localhost:5432/nucleo_empresarial"
    JWT_SECRET_KEY: str = "clave_por_defecto_cambiar_en_produccion_inmediatamente"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Odoo
    ODOO_URL: str = ""
    ODOO_DB: str = ""
    ODOO_USER: str = ""
    ODOO_PASSWORD: str = ""

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_JSON: str = ""
    GOOGLE_SHEET_ID: str = ""

    # Outlook (Microsoft Graph)
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    OUTLOOK_SENDER_EMAIL: str = ""
    OUTLOOK_DIRECTOR_EMAIL: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
