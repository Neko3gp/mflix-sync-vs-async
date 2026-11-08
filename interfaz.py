"""Interfaz mínima para demostrar las apps sync y async sobre MongoDB Atlas."""
import asyncio
import json
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bson import ObjectId, json_util

from src.async_app.bulk import load_movies_bulk as async_bulk
from src.async_app.crud import (
    create_movie as async_create,
    delete_movie as async_delete,
    get_movie as async_get,
    update_movie as async_update,
)
from src.async_app.db import get_async_client, get_async_db
from src.async_app.queries import (
    aggregate_movies_by_genre as async_aggregate,
    find_movies_by_year_and_genre as async_find,
    run_independent_queries,
    run_queries_taskgroup,
    search_movies_by_regex as async_regex,
)
from src.common.config import DB_NAME
from src.sync_app.bulk import load_movies_bulk as sync_bulk
from src.sync_app.crud import (
    create_movie as sync_create,
    delete_movie as sync_delete,
    get_movie as sync_get,
    update_movie as sync_update,
)
from src.sync_app.db import get_sync_client, get_sync_db
from src.sync_app.queries import (
    aggregate_movies_by_genre as sync_aggregate,
    find_movies_by_year_and_genre as sync_find,
    search_movies_by_regex as sync_regex,
)

ARCHIVO_POR_DEFECTO = Path("data/movies.json")


class AsyncWorker:
    """Hilo con un event loop y un AsyncMongoClient reutilizables."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.client = get_async_client()
        self.db = get_async_db(DB_NAME, self.client)
        self.work_db = get_async_db(f"{DB_NAME}_async", self.client)
        self.ready.set()
        self.loop.run_forever()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def close(self):
        self.submit(self.client.close()).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


class Interfaz:
    def __init__(self, root):
        self.root = root
        root.title("Mflix | PyMongo Sync vs Async")
        root.geometry("980x640")
        self.sync_client = get_sync_client()
        self.sync_db = get_sync_db(DB_NAME, self.sync_client)
        self.sync_work_db = get_sync_db(f"{DB_NAME}_sync", self.sync_client)
        self.worker = AsyncWorker()
        self.campos = {}
        self.archivo = None
        self._crear_widgets()
        root.protocol("WM_DELETE_WINDOW", self.cerrar)

    # ---------- Construcción de la ventana ----------
    def _crear_widgets(self):
        lateral = ttk.LabelFrame(self.root, text="Datos de la película")
        lateral.pack(side="left", fill="y", padx=10, pady=10)
        for clave, etiqueta in (("title", "Título"), ("year", "Año"),
                                ("genre", "Género"), ("id", "ObjectId")):
            ttk.Label(lateral, text=etiqueta).pack(anchor="w", padx=8, pady=(8, 0))
            entrada = ttk.Entry(lateral, width=28)
            entrada.pack(padx=8)
            self.campos[clave] = entrada
        ttk.Label(lateral, text=f"Base activa: {DB_NAME}").pack(anchor="w", padx=8, pady=16)

        pestañas = ttk.Notebook(self.root)
        pestañas.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)
        self.sync_texto = self._pestaña(pestañas, "SYNC (PyMongo)", (
            ("Crear", self.sync_crear),
            ("Buscar ID", lambda: self._sync(lambda: sync_get(self.sync_db, self._id()))),
            ("Actualizar año", lambda: self._sync(lambda: sync_update(self.sync_db, self._id(), {"year": self._año()}))),
            ("Eliminar", lambda: self._sync(lambda: {"eliminadas": sync_delete(self.sync_db, self._id())})),
            ("Buscar título", lambda: self._sync(lambda: sync_regex(self.sync_db, self._valor("title")))),
            ("Año + género", lambda: self._sync(lambda: sync_find(self.sync_db, self._año(), self._valor("genre")))),
            ("Top géneros", lambda: self._sync(lambda: sync_aggregate(self.sync_db))),
            ("Carga bulk_write", self.sync_carga),
        ))
        self.async_texto = self._pestaña(pestañas, "ASYNC (AsyncMongoClient)", (
            ("Crear", lambda: self._async(lambda: self._async_crear(self._documento()))),
            ("Buscar ID", lambda: self._async(lambda: async_get(self.worker.db, self._id()))),
            ("Actualizar año", lambda: self._async(lambda: async_update(self.worker.db, self._id(), {"year": self._año()}))),
            ("Eliminar", lambda: self._async(lambda: self._async_eliminar(self._id()))),
            ("Buscar título", lambda: self._async(lambda: async_regex(self.worker.db, self._valor("title")))),
            ("Año + género", lambda: self._async(lambda: async_find(self.worker.db, self._año(), self._valor("genre")))),
            ("Top géneros", lambda: self._async(lambda: async_aggregate(self.worker.db))),
            ("Consultas gather()", lambda: self._async(lambda: run_independent_queries(self.worker.db))),
            ("Consultas TaskGroup", lambda: self._async(lambda: run_queries_taskgroup(self.worker.db))),
            ("Carga bulk_write", self.async_carga),
        ))
        self.comparacion_texto = self._pestaña(pestañas, "COMPARACIÓN", (
            ("Ejecutar comparación", self.comparar),
        ))

    def _pestaña(self, pestañas, titulo, botones):
        marco = ttk.Frame(pestañas)
        pestañas.add(marco, text=titulo)
        barra = ttk.Frame(marco)
        barra.pack(fill="x", padx=8, pady=8)
        for i, (texto, comando) in enumerate(botones):
            ttk.Button(barra, text=texto, command=comando).grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="ew")
        texto_resultado = tk.Text(marco, wrap="word", font=("Courier", 11))
        texto_resultado.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        return texto_resultado

    # ---------- Lectura de campos y resultados ----------
    def _valor(self, clave):
        return self.campos[clave].get().strip()

    def _año(self):
        return int(self._valor("year"))

    def _id(self):
        valor = self._valor("id")
        if not ObjectId.is_valid(valor):
            raise ValueError("Error: El '_id' debe ser válido.")
        return ObjectId(valor)

    def _documento(self):
        titulo = self._valor("title")
        if not titulo:
            raise ValueError("Error: El documento debe contener al menos un 'title'.")
        documento = {"title": titulo}
        if self._valor("year"):
            documento["year"] = self._año()
        if self._valor("genre"):
            documento["genres"] = [self._valor("genre")]
        return documento

    def _mostrar(self, widget, datos):
        if isinstance(datos, dict) and "creada" in datos:
            self.campos["id"].delete(0, "end")
            self.campos["id"].insert(0, str(datos["creada"]))
        widget.delete("1.0", "end")
        widget.insert("end", json.dumps(datos, default=str, indent=2, ensure_ascii=False))

    def _error(self, error):
        messagebox.showerror("Operación no completada", str(error))

    # ---------- App síncrona (se ejecuta en el hilo de la interfaz) ----------
    def _sync(self, funcion):
        try:
            self._mostrar(self.sync_texto, funcion())
        except Exception as error:
            self._error(error)

    def sync_crear(self):
        self._sync(lambda: {"creada": sync_create(self.sync_db, self._documento())})

    def sync_carga(self):
        movies = self._preparar_carga("sync")
        if movies is None:
            return
        self._mostrar(self.sync_texto, {"estado": "Cargando..."})

        def trabajo():
            try:
                self.sync_work_db.movies.drop()
                inicio = time.perf_counter()
                resultado = sync_bulk(self.sync_work_db, movies, batch_size=100)
                resultado["segundos"] = round(time.perf_counter() - inicio, 4)
                self.root.after(0, lambda: self._mostrar(self.sync_texto, resultado))
            except Exception as error:
                self.root.after(0, lambda: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    # ---------- App asíncrona (corre en el event loop del worker) ----------
    def _async(self, fabrica):
        try:
            coroutine = fabrica()  # lee los campos en el hilo de la interfaz
        except Exception as error:
            self._error(error)
            return
        futuro = self.worker.submit(coroutine)
        futuro.add_done_callback(lambda f: self.root.after(0, lambda: self._terminar(f)))

    def _terminar(self, futuro):
        try:
            self._mostrar(self.async_texto, futuro.result())
        except Exception as error:
            self._error(error)

    async def _async_crear(self, documento):
        return {"creada": await async_create(self.worker.db, documento)}

    async def _async_eliminar(self, movie_id):
        return {"eliminadas": await async_delete(self.worker.db, movie_id)}

    def async_carga(self):
        movies = self._preparar_carga("async")
        if movies is None:
            return
        self._mostrar(self.async_texto, {"estado": "Cargando..."})
        self._async(lambda: self._cargar_async(movies))

    async def _cargar_async(self, movies):
        await self.worker.work_db.movies.drop()
        inicio = time.perf_counter()
        resultado = await async_bulk(self.worker.work_db, movies, batch_size=100, concurrency=10)
        resultado["segundos"] = round(time.perf_counter() - inicio, 4)
        return resultado

    # ---------- Carga masiva (archivo) ----------
    def _preparar_carga(self, nombre):
        """Lee movies.json y pide confirmación antes de vaciar la colección de trabajo."""
        try:
            if not self.archivo:
                if ARCHIVO_POR_DEFECTO.exists():
                    self.archivo = str(ARCHIVO_POR_DEFECTO)
                else:
                    self.archivo = filedialog.askopenfilename(
                        title="Selecciona movies.json", filetypes=(("JSON", "*.json"),))
            if not self.archivo:
                raise ValueError("Selecciona un archivo movies.json para la carga masiva.")
            contenido = Path(self.archivo).read_text(encoding="utf-8").strip()
            if contenido.startswith("["):
                movies = json_util.loads(contenido)
            else:
                movies = [json_util.loads(linea) for linea in contenido.splitlines() if linea.strip()]
            if not messagebox.askyesno(
                    "Carga masiva",
                    f"¿Vaciar {DB_NAME}_{nombre}.movies y cargar {len(movies)} documentos?"):
                return None
            return movies
        except Exception as error:
            self._error(error)
            return None

    # ---------- Comparación ----------
    def comparar(self):
        self._mostrar(self.comparacion_texto, {"estado": "Ejecutando..."})

        def trabajo():
            try:
                inicio = time.perf_counter()
                sync_resultado = [sync_find(self.sync_db, 1999, "Action"), sync_aggregate(self.sync_db),
                                  sync_regex(self.sync_db, "Matrix")]
                sync_tiempo = time.perf_counter() - inicio

                async def consultas():
                    inicio_async = time.perf_counter()
                    resultado = await run_independent_queries(self.worker.db)
                    return resultado, time.perf_counter() - inicio_async

                async_resultado, async_tiempo = self.worker.submit(consultas()).result()
                datos = {
                    "sync_secuencial": {"segundos": round(sync_tiempo, 4),
                                        "resultados": [len(r) for r in sync_resultado]},
                    "async_gather": {"segundos": round(async_tiempo, 4),
                                     "resultados": [len(r) for r in async_resultado]},
                }
                self.root.after(0, lambda: self._mostrar(self.comparacion_texto, datos))
            except Exception as error:
                self.root.after(0, lambda: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    def cerrar(self):
        self.sync_client.close()
        self.worker.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    Interfaz(root)
    root.mainloop()


if __name__ == "__main__":
    main()