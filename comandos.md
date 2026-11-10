# Comandos para levantar el proyecto

Requisitos: Python 3.11 o superior y Docker con Docker Compose.
Todos los comandos se ejecutan desde la carpeta del proyecto (`Async-DataBase`).

## 1. Entorno de Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Levantar MongoDB con los datos

```bash
docker compose up -d
```

Ver el avance de la carga (la primera vez descarga unos 380 MB). Termina con
`21349 document(s) restored successfully`; sal con `Ctrl+C`:

```bash
docker compose logs -f loader
```

Verificar que quedaron los datos (debe imprimir `21349`):

```bash
docker exec mongo-mflix mongosh --quiet --eval 'db.getSiblingDB("sample_mflix").movies.countDocuments()'
```

## 3. Ejecutar el proyecto

```bash
python sync_app.py
python async_app.py
python comparacion.py
```

Opcional: abrir la interfaz gráfica con todas las funciones:

```bash
python ui.py
```

Si aparece `No module named '_tkinter'` (pasa con Python de Homebrew en Mac):

```bash
brew install python-tk
```

## 4. Apagar y limpiar

Apagar el servidor (los datos se conservan):

```bash
docker compose down
```

Volver a levantarlo sin descargar nada:

```bash
docker compose up -d
```

Borrar todo, incluidos los datos y el archivo descargado:

```bash
docker compose down -v
```

## Si algo falla

Si aparece `Conflict. The container name "/mongo-mflix" is already in use`, hay un
contenedor viejo con ese nombre. Bórralo y vuelve a levantar:

```bash
docker rm -f mongo-mflix
docker compose up -d
```