import datetime
import os
import subprocess
from pathlib import Path

BACKUP_DIR = Path("./backups")
CONTAINER_NAME = "nucleo_postgres"
DB_USER = "admin_empresa"
DB_NAME = "nucleo_empresarial"


def ejecutar_respaldo():
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo_destino = BACKUP_DIR / f"respaldo_{DB_NAME}_{timestamp}.sql"

    comando = [
        "docker",
        "exec",
        "-t",
        CONTAINER_NAME,
        "pg_dump",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "--clean",
        "--if-exists",
    ]

    with open(archivo_destino, "w", encoding="utf-8") as salida:
        resultado = subprocess.run(comando, stdout=salida, stderr=subprocess.PIPE, text=True)

    if resultado.returncode == 0 and os.path.getsize(archivo_destino) > 0:
        print(f"[OK] Respaldo exitoso creado en: {archivo_destino}")
    else:
        print(f"[ERROR] Fallo en el respaldo: {resultado.stderr}")


if __name__ == "__main__":
    ejecutar_respaldo()
