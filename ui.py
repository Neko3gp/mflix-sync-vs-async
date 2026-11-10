"""Interfaz gráfica (tkinter) del proyecto: carga masiva, CRUD, consultas y comparación.

Usa sync_app.py (PyMongo) y async_app.py (PyMongo Async) sin modificarlos, y
comparacion.py para la comparación. Cada operación corre en un hilo aparte para que la
ventana no se congele; las operaciones asíncronas ejecutan su propio asyncio.run().
"""
import asyncio
import contextlib
import io
import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

import async_app
import comparacion
import sync_app

SYNC, ASYNC = "sync", "async"
FONT = "Helvetica"
MONO = "Courier"

# Paletas de color. Se aplican a TODOS los widgets (tema "clam"), así la ventana se ve
# igual sin importar el modo claro u oscuro del sistema.
PALETTES = {
    "oscuro": {
        "bg": "#1e1f24", "field": "#2f323b", "text_bg": "#17181c", "fg": "#e6e8ee", "muted": "#9aa0ad",
        "border": "#444956", "btn": "#363a45", "btn_hover": "#434856", "tab": "#2a2d35",
        "head": "#333744", "accent": "#2f6fe0", "accent_hover": "#4a86ee", "accent_fg": "#ffffff",
        "sel": "#35507f", "sel_fg": "#ffffff", "header": "#14233b", "header_sub": "#a9b8d0",
        "ok": "#5fd38d", "err": "#ff7a7a",
    },
    "claro": {
        "bg": "#f2f3f5", "field": "#ffffff", "text_bg": "#fbfbfc", "fg": "#1b1d22", "muted": "#5b6270",
        "border": "#c4c8d0", "btn": "#e4e6ea", "btn_hover": "#d6d9df", "tab": "#e2e4e9",
        "head": "#e4e6ea", "accent": "#2b6cdf", "accent_hover": "#4a84ea", "accent_fg": "#ffffff",
        "sel": "#cfe0ff", "sel_fg": "#111111", "header": "#1f3a5f", "header_sub": "#c9d6e8",
        "ok": "#1b7a34", "err": "#b3261e",
    },
}


# ======================================================================
# Lógica (se ejecuta en hilos de trabajo; no toca widgets)
# ======================================================================
def describe_error(exc):
    """Traduce una excepción a un mensaje entendible."""
    # TaskGroup puede envolver el error original en un grupo; se muestra la
    # primera causa para que el mensaje sea útil y no un resumen ilegible.
    if isinstance(exc, BaseExceptionGroup):
        return describe_error(exc.exceptions[0])
    # Este caso merece instrucciones concretas porque normalmente indica que
    # el contenedor o el servicio local todavía no está iniciado.
    if isinstance(exc, ServerSelectionTimeoutError):
        return ("No se pudo conectar a MongoDB en localhost:27017.\n"
                "¿Está levantado el contenedor? Ejecuta: docker compose up -d")
    # Los errores conocidos de PyMongo se presentan con un prefijo identificable.
    if isinstance(exc, PyMongoError):
        return f"Error de MongoDB: {exc}"
    # Para errores de Python se conserva el texto y, si está vacío, el nombre de clase.
    return str(exc) or exc.__class__.__name__


def run_on_db(kind, sync_fn, async_fn):
    """Abre un cliente (sync o async), ejecuta la función sobre la copia de esa app y lo cierra."""
    # La rama síncrona usa el cliente y callback normales, siempre con cierre garantizado.
    if kind == SYNC:
        client = sync_app.get_client()
        try:
            return sync_fn(client[sync_app.APP_DB])
        finally:
            client.close()

    # La rama asíncrona se encapsula en una corrutina porque asyncio.run necesita
    # un punto de entrada completo para gestionar el ciclo de eventos.
    async def main():
        client = async_app.get_client()
        try:
            return await async_fn(client[async_app.APP_DB])
        finally:
            await client.close()

    # La GUI permanece síncrona; asyncio.run contiene la parte asíncrona del backend.
    return asyncio.run(main())


def backend_status():
    """Cuenta los documentos de la base original y de las dos copias."""
    # El ping falla explícitamente si MongoDB no está disponible.
    client = sync_app.get_client()
    try:
        client.admin.command("ping")
        # Se consulta cada base para que el estado de la interfaz refleje las tres colecciones.
        return {
            f"{sync_app.SOURCE_DB}.movies (original)": client[sync_app.SOURCE_DB].movies.count_documents({}),
            f"{sync_app.APP_DB}.movies (app síncrona)": client[sync_app.APP_DB].movies.count_documents({}),
            f"{async_app.APP_DB}.movies (app asíncrona)": client[async_app.APP_DB].movies.count_documents({}),
        }
    finally:
        client.close()


def backend_load(kind, batch_size, concurrency):
    """Lee sample_mflix.movies, recrea la copia de la app elegida y la carga por lotes."""
    # La implementación síncrona lee, borra y carga todo dentro del mismo cliente.
    if kind == SYNC:
        client = sync_app.get_client()
        try:
            # La fuente es común a ambas aplicaciones y nunca se modifica.
            movies = list(client[sync_app.SOURCE_DB].movies.find())
            # Sin datos de origen no se puede completar la carga.
            if not movies:
                raise RuntimeError(f"{sync_app.SOURCE_DB}.movies está vacía o no existe.")
            # Se reinicia la copia para que la comparación no mezcle ejecuciones.
            db = client[sync_app.APP_DB]
            db.movies.drop()
            start = time.perf_counter()
            result = sync_app.load_movies_bulk(db, movies, batch_size)
            elapsed = time.perf_counter() - start
        finally:
            client.close()
    else:
        # En async se repite el mismo flujo usando await para cada operación de red.
        async def main():
            client = async_app.get_client()
            try:
                # to_list consume el cursor asíncrono y obtiene todos los documentos.
                movies = await client[async_app.SOURCE_DB].movies.find().to_list()
                # La validación evita borrar o medir una carga inexistente.
                if not movies:
                    raise RuntimeError(f"{async_app.SOURCE_DB}.movies está vacía o no existe.")
                # La copia async se limpia antes de insertar los nuevos lotes.
                db = client[async_app.APP_DB]
                await db.movies.drop()
                start = time.perf_counter()
                result = await async_app.load_movies_bulk(db, movies, batch_size, concurrency)
                return len(movies), result, time.perf_counter() - start
            finally:
                await client.close()

        # Se normaliza el resultado async al formato que espera la GUI.
        total, result, elapsed = asyncio.run(main())
        return {**result, "total": total, "seconds": elapsed}
    # El resultado sync usa el mismo esquema que el resultado async.
    return {**result, "total": len(movies), "seconds": elapsed}


def parse_id(text):
    # strip permite pegar un ID con espacios; ObjectId valida longitud y hexadecimal.
    try:
        return ObjectId(text.strip())
    except (InvalidId, TypeError, AttributeError):
        # Se traduce el error de librería a un mensaje de validación para la GUI.
        raise ValueError("El ID no es válido (debe ser un ObjectId de 24 caracteres hexadecimales).")


def backend_crud(kind, action, movie_id=None, movie=None, changes=None):
    # Cada acción delega en la implementación correspondiente sin duplicar la lógica
    # de conexión ni la conversión entre sync y async.
    if action == "create":
        return run_on_db(kind,
                         lambda db: sync_app.create_movie(db, movie),
                         lambda db: async_app.create_movie(db, movie))
    if action == "read":
        return run_on_db(kind,
                         lambda db: sync_app.get_movie(db, movie_id),
                         lambda db: async_app.get_movie(db, movie_id))
    if action == "update":
        return run_on_db(kind,
                         lambda db: sync_app.update_movie(db, movie_id, changes),
                         lambda db: async_app.update_movie(db, movie_id, changes))
    if action == "delete":
        return run_on_db(kind,
                         lambda db: sync_app.delete_movie(db, movie_id),
                         lambda db: async_app.delete_movie(db, movie_id))
    # Evita que una acción mal formada falle silenciosamente.
    raise ValueError(f"Acción desconocida: {action}")


def backend_queries(mode, year, genre, text):
    """mode: 'sync' (secuencial), 'gather' o 'taskgroup'. Devuelve (resultados, segundos)."""
    def sync_fn(db):
        # En sync las tres consultas se ejecutan deliberadamente una detrás de otra.
        start = time.perf_counter()
        results = [sync_app.find_movies_by_year_and_genre(db, year, genre),
                   sync_app.aggregate_movies_by_genre(db),
                   sync_app.search_movies_by_regex(db, text)]
        return results, time.perf_counter() - start

    async def async_fn(db):
        start = time.perf_counter()
        # gather y TaskGroup representan dos estrategias async diferentes.
        if mode == "gather":
            results = await asyncio.gather(
                async_app.find_movies_by_year_and_genre(db, year, genre),
                async_app.aggregate_movies_by_genre(db),
                async_app.search_movies_by_regex(db, text),
            )
        else:
            async with asyncio.TaskGroup() as group:
                # TaskGroup administra el ciclo de vida de las tres tareas.
                tasks = [
                    group.create_task(async_app.find_movies_by_year_and_genre(db, year, genre)),
                    group.create_task(async_app.aggregate_movies_by_genre(db)),
                    group.create_task(async_app.search_movies_by_regex(db, text)),
                ]
            # Al salir del grupo todas las tareas ya finalizaron.
            results = [task.result() for task in tasks]
        # Se devuelve una lista común y el tiempo total de las tres consultas.
        return list(results), time.perf_counter() - start

    # Solo las consultas async usan ASYNC; el modo sync conserva el cliente normal.
    return run_on_db(SYNC if mode == "sync" else ASYNC, sync_fn, async_fn)


class QueueWriter(io.TextIOBase):
    """Recibe lo que imprime comparacion.py y lo manda a la ventana."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        # stdout puede escribir cadenas vacías; no se envían eventos innecesarios.
        if text:
            self.q.put(("out", text))
        # TextIOBase espera que write informe cuántos caracteres consumió.
        return len(text)


def backend_compare(q):
    # La salida de comparacion.py se redirige a la cola para actualizar widgets
    # únicamente desde el hilo principal.
    with contextlib.redirect_stdout(QueueWriter(q)):
        asyncio.run(comparacion.main())


# ======================================================================
# Interfaz
# ======================================================================
class App(tk.Tk):
    def __init__(self):
        # Se inicializa primero Tk para que todos los widgets tengan una raíz válida.
        super().__init__()
        self.title("Proyecto 2a Evaluación: MongoDB síncrono vs asíncrono")
        self.geometry("1040x760")
        self.minsize(900, 640)
        # La cola es el puente seguro entre trabajadores y el hilo de tkinter.
        self.q = queue.Queue()
        self.busy = False
        self.status = tk.StringVar(value="Listo")
        self.theme = "oscuro"
        self.conn_state = None      # None, "ok" o "err": color del texto de conexión
        self.text_widgets = []      # widgets tk.Text, que no siguen al tema por sí solos

        self.style = ttk.Style(self)
        self.style.theme_use("clam")  # el único tema en el que se pueden controlar todos los colores

        # Se construye la interfaz antes de aplicar colores y programar callbacks.
        self._build_header()
        self._build_tabs()
        self._build_footer()
        self.apply_theme(self.theme)
        self.after(100, self._poll)
        self.after(400, self.check_status)

    # ------------------------------------------------------------ estructura
    def _build_header(self):
        # El encabezado contiene el título, la descripción y el control del tema.
        self.header = tk.Frame(self)
        self.header.pack(fill="x")
        self.header_title = tk.Label(self.header, text="MongoDB: aplicación síncrona vs asíncrona",
                                     fg="white", font=(FONT, 17, "bold"))
        self.header_title.pack(anchor="w", padx=18, pady=(12, 0))
        self.header_sub = tk.Label(self.header, font=(FONT, 10),
                                   text="PyMongo · PyMongo Async · asyncio (gather, TaskGroup, Semaphore) · bulk_write")
        self.header_sub.pack(anchor="w", padx=18, pady=(0, 12))
        self.theme_btn = ttk.Button(self.header, text="Modo claro", command=self.toggle_theme)
        self.theme_btn.place(relx=1.0, x=-18, y=14, anchor="ne")

    def _build_tabs(self):
        # Cada tupla asocia el texto visible con el método que crea esa pestaña.
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        for title, builder in (("Estado", self._tab_status), ("Carga masiva", self._tab_load),
                               ("CRUD", self._tab_crud), ("Consultas", self._tab_queries),
                               ("Comparación", self._tab_compare)):
            frame = ttk.Frame(self.tabs, padding=14)
            # Se crea un frame independiente para evitar mezclar controles entre pestañas.
            self.tabs.add(frame, text=title)
            builder(frame)

    def _build_footer(self):
        # El pie muestra el estado, el progreso y el registro de operaciones.
        footer = ttk.Frame(self, padding=(10, 0, 10, 8))
        footer.pack(fill="x")
        bar = ttk.Frame(footer)
        bar.pack(fill="x")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=140)
        self.progress.pack(side="right")
        ttk.Label(bar, textvariable=self.status, font=(FONT, 10, "bold")).pack(side="left")
        self.log_text = tk.Text(footer, height=6, font=(MONO, 10), state="disabled", relief="flat")
        self.log_text.pack(fill="x", pady=(6, 0))
        self.text_widgets.append(self.log_text)

    # ------------------------------------------------------------ tema
    def toggle_theme(self):
        # El tema se alterna únicamente entre las dos paletas declaradas.
        self.apply_theme("claro" if self.theme == "oscuro" else "oscuro")

    def apply_theme(self, name):
        """Aplica la paleta a los widgets ttk (estilos) y a los tk (directamente)."""
        # Se guarda el nombre para que futuros widgets y mensajes usen la misma paleta.
        self.theme = name
        p = PALETTES[name]
        s = self.style
        self.configure(bg=p["bg"])

        s.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                    bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                    troughcolor=p["field"], focuscolor=p["accent"], insertcolor=p["fg"])
        s.configure("TFrame", background=p["bg"])
        s.configure("TLabel", background=p["bg"], foreground=p["fg"])
        s.configure("TLabelframe", background=p["bg"], bordercolor=p["border"],
                    lightcolor=p["bg"], darkcolor=p["bg"])
        s.configure("TLabelframe.Label", background=p["bg"], foreground=p["fg"], font=(FONT, 10, "bold"))

        s.configure("TButton", background=p["btn"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["btn"], darkcolor=p["btn"], padding=(10, 5), font=(FONT, 11))
        s.map("TButton", background=[("pressed", p["accent"]), ("active", p["btn_hover"])],
              foreground=[("disabled", p["muted"])])
        s.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    lightcolor=p["accent"], darkcolor=p["accent"], bordercolor=p["accent"],
                    font=(FONT, 11, "bold"))
        s.map("Accent.TButton", background=[("pressed", p["accent_hover"]), ("active", p["accent_hover"])],
              foreground=[("disabled", p["muted"])])

        s.configure("TRadiobutton", background=p["bg"], foreground=p["fg"], font=(FONT, 11),
                    indicatorbackground=p["field"], indicatorforeground=p["accent"])
        s.map("TRadiobutton", background=[("active", p["bg"])], foreground=[("active", p["fg"])],
              indicatorbackground=[("selected", p["accent"]), ("!selected", p["field"])],
              indicatorforeground=[("selected", p["accent_fg"])])

        for widget in ("TEntry", "TSpinbox"):
            # Ambos controles comparten colores de campo y estados deshabilitados.
            s.configure(widget, fieldbackground=p["field"], foreground=p["fg"], insertcolor=p["fg"],
                        bordercolor=p["border"], lightcolor=p["field"], darkcolor=p["field"],
                        background=p["btn"], arrowcolor=p["fg"])
            s.map(widget, fieldbackground=[("readonly", p["field"]), ("disabled", p["bg"])],
                  foreground=[("disabled", p["muted"])])

        s.configure("TNotebook", background=p["bg"], bordercolor=p["border"], tabmargins=(2, 4, 2, 0))
        s.configure("TNotebook.Tab", background=p["tab"], foreground=p["muted"], padding=(14, 6),
                    bordercolor=p["border"], lightcolor=p["tab"], darkcolor=p["tab"], font=(FONT, 11))
        s.map("TNotebook.Tab", background=[("selected", p["bg"]), ("active", p["btn_hover"])],
              foreground=[("selected", p["fg"]), ("active", p["fg"])],
              lightcolor=[("selected", p["bg"])], darkcolor=[("selected", p["bg"])])

        s.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["field"], darkcolor=p["field"], rowheight=24,
                    font=(FONT, 11))
        s.map("Treeview", background=[("selected", p["sel"])], foreground=[("selected", p["sel_fg"])])
        s.configure("Treeview.Heading", background=p["head"], foreground=p["fg"], relief="flat",
                    bordercolor=p["border"], lightcolor=p["head"], darkcolor=p["head"],
                    font=(FONT, 10, "bold"))
        s.map("Treeview.Heading", background=[("active", p["btn_hover"])])

        s.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["field"],
                    bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"])
        for orient in ("Horizontal.TScrollbar", "Vertical.TScrollbar"):
            # La misma configuración visual se aplica a ambas orientaciones.
            s.configure(orient, background=p["btn"], troughcolor=p["field"], bordercolor=p["border"],
                        lightcolor=p["btn"], darkcolor=p["btn"], arrowcolor=p["fg"])

        # widgets tk clásicos: no usan los estilos ttk
        self.header.configure(bg=p["header"])
        self.header_title.configure(bg=p["header"], fg="#ffffff")
        self.header_sub.configure(bg=p["header"], fg=p["header_sub"])
        self.theme_btn.configure(text="Modo claro" if name == "oscuro" else "Modo oscuro")
        for text in self.text_widgets:
            text.configure(bg=p["text_bg"], fg=p["fg"], insertbackground=p["fg"],
                           selectbackground=p["sel"], selectforeground=p["sel_fg"], relief="flat",
                           highlightthickness=1, highlightbackground=p["border"], highlightcolor=p["border"])
        colors = {"ok": p["ok"], "err": p["err"]}
        self.conn_label.configure(foreground=colors.get(self.conn_state, p["fg"]))

    # ------------------------------------------------------------ utilidades
    def log(self, message):
        # El widget está bloqueado normalmente; se habilita solo durante la escritura.
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def set_text(widget, text):
        # Se reemplaza todo el contenido y después se vuelve a bloquear el Text.
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def run_task(self, label, fn, on_done):
        """Ejecuta fn en un hilo; on_done(resultado) se llama en el hilo de la ventana."""
        # Tkinter no debe ejecutar dos operaciones backend al mismo tiempo desde esta GUI.
        if self.busy:
            messagebox.showinfo("Operación en curso", "Espera a que termine la operación actual.")
            return
        # El estado ocupado y la barra se activan antes de iniciar el hilo.
        self.busy = True
        self.progress.start(12)
        self.status.set(f"{label}…")
        self.log(f"{label}…")

        def worker():
            try:
                # La función potencialmente lenta corre fuera del hilo de tkinter.
                result = fn()
            except Exception as exc:  # noqa: BLE001 (se muestra al usuario)
                # El error se entrega a _poll para mostrarlo en el hilo seguro de la GUI.
                self.q.put(("error", label, exc))
            else:
                # Solo los resultados correctos llegan como evento "done".
                self.q.put(("done", label, on_done, result))

        # daemon evita que un hilo de backend impida cerrar la aplicación.
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        # after vuelve a ejecutar este método; así la cola se revisa sin bloquear la ventana.
        try:
            while True:
                # Se vacían todos los eventos disponibles en esta pasada.
                message = self.q.get_nowait()
                kind = message[0]
                if kind == "out":
                    # La comparación escribe directamente en su panel de salida.
                    self.compare_text.configure(state="normal")
                    self.compare_text.insert("end", message[1])
                    self.compare_text.see("end")
                    self.compare_text.configure(state="disabled")
                elif kind == "done":
                    # Un resultado exitoso detiene el progreso y ejecuta el callback de UI.
                    _, label, on_done, result = message
                    self._finish()
                    self.status.set(f"{label}: terminado")
                    self.log(f"{label}: terminado")
                    on_done(result)
                elif kind == "error":
                    # Los errores también liberan el estado ocupado antes de notificarse.
                    _, label, exc = message
                    self._finish()
                    text = describe_error(exc)
                    self.status.set(f"{label}: error")
                    self.log(f"{label}: ERROR - {text.splitlines()[0]}")
                    if label == "Verificar conexión":
                        # Solo la verificación cambia el indicador persistente de conexión.
                        self.conn_state = "err"
                        self.conn_label.configure(text="Sin conexión con MongoDB",
                                                  foreground=PALETTES[self.theme]["err"])
                    messagebox.showerror(label, text)
        except queue.Empty:
            # Una cola vacía es normal: significa que no hay eventos pendientes.
            pass
        # Se programa la siguiente revisión aunque esta no haya encontrado mensajes.
        self.after(100, self._poll)

    def _finish(self):
        # Todas las rutas de finalización pasan por aquí para restaurar el estado inicial.
        self.busy = False
        self.progress.stop()

    @staticmethod
    def app_selector(parent, variable, with_modes=None):
        # Si no se proporcionan modos, se muestran las dos aplicaciones disponibles.
        box = ttk.LabelFrame(parent, text="Aplicación", padding=8)
        options = with_modes or [("Síncrona (PyMongo)", SYNC), ("Asíncrona (PyMongo Async)", ASYNC)]
        for text, value in options:
            # Cada radio comparte variable para que solo una opción quede seleccionada.
            ttk.Radiobutton(box, text=text, value=value, variable=variable).pack(anchor="w")
        return box

    @staticmethod
    def int_value(text, name, minimum=None, required=True):
        # Se eliminan espacios antes de validar para aceptar entradas pegadas.
        text = text.strip()
        if not text:
            # Los campos opcionales pueden quedar vacíos y producir None.
            if required:
                raise ValueError(f"Escribe un valor para «{name}».")
            return None
        try:
            # int comprueba que la entrada sea un número entero real.
            value = int(text)
        except ValueError:
            # Se reemplaza el mensaje técnico por uno específico del campo.
            raise ValueError(f"«{name}» debe ser un número entero.")
        if minimum is not None and value < minimum:
            # El límite se valida después de convertir el texto a número.
            raise ValueError(f"«{name}» debe ser {minimum} o mayor.")
        # Se devuelve el valor ya convertido para evitar repetir la conversión.
        return value

    def safe(self, fn):
        """Ejecuta una acción de la ventana mostrando los errores de validación."""
        try:
            # Las acciones de botones pueden lanzar errores de validación controlados.
            fn()
        except ValueError as exc:
            # Los errores de entrada se muestran como advertencias, no como fallos técnicos.
            messagebox.showwarning("Datos incorrectos", str(exc))

    # ------------------------------------------------------------ pestaña Estado
    def _tab_status(self, tab):
        # Esta pestaña presenta una vista resumida de la conexión y de las tres copias.
        ttk.Label(tab, text="Conexión y datos", font=(FONT, 14, "bold")).pack(anchor="w")
        ttk.Label(tab, wraplength=900, justify="left", text=(
            "Las dos apps se conectan a mongodb://localhost:27017. Cada una lee sample_mflix.movies "
            "(solo lectura) y trabaja en su propia copia, para poder compararlas en igualdad de condiciones."
        )).pack(anchor="w", pady=(4, 12))
        self.status_rows = ttk.Treeview(tab, columns=("coleccion", "docs"), show="headings", height=4)
        self.status_rows.heading("coleccion", text="Colección")
        self.status_rows.heading("docs", text="Documentos")
        self.status_rows.column("coleccion", width=420)
        self.status_rows.column("docs", width=140, anchor="e")
        self.status_rows.pack(anchor="w")
        self.conn_label = ttk.Label(tab, text="Sin verificar", font=(FONT, 11, "bold"))
        self.conn_label.pack(anchor="w", pady=10)
        ttk.Button(tab, text="Verificar conexión", style="Accent.TButton",
                   command=self.check_status).pack(anchor="w")

    def check_status(self):
        # La consulta se ejecuta en segundo plano para que el ping no congele la GUI.
        self.run_task("Verificar conexión", backend_status, self._show_status)

    def _show_status(self, info):
        # Primero se eliminan filas antiguas para no duplicar datos al actualizar.
        self.status_rows.delete(*self.status_rows.get_children())
        for name, count in info.items():
            # Cada entrada del backend se convierte en una fila visible.
            self.status_rows.insert("", "end", values=(name, f"{count:,}"))
        # Solo se marca como conectado después de recibir una respuesta válida.
        self.conn_state = "ok"
        self.conn_label.configure(text="Conectado a MongoDB (localhost:27017)",
                                  foreground=PALETTES[self.theme]["ok"])

    # ------------------------------------------------------------ pestaña Carga masiva
    def _tab_load(self, tab):
        # La pestaña reúne la selección de app, parámetros y resultado de la carga.
        ttk.Label(tab, text="Carga masiva con bulk_write()", font=(FONT, 14, "bold")).pack(anchor="w")
        ttk.Label(tab, wraplength=900, justify="left", text=(
            "Lee todas las películas de sample_mflix, borra y recrea la copia de la app elegida y las inserta "
            "por lotes. La síncrona envía un lote tras otro; la asíncrona usa TaskGroup para lanzar un lote por "
            "tarea y un Semaphore para limitar cuántos escriben a la vez."
        )).pack(anchor="w", pady=(4, 12))

        row = ttk.Frame(tab)
        row.pack(anchor="w")
        self.load_kind = tk.StringVar(value=ASYNC)
        self.app_selector(row, self.load_kind).pack(side="left", padx=(0, 16))
        params = ttk.LabelFrame(row, text="Parámetros", padding=8)
        params.pack(side="left")
        self.load_batch = tk.StringVar(value="1000")
        self.load_conc = tk.StringVar(value="10")
        ttk.Label(params, text="Tamaño de lote").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Spinbox(params, from_=1, to=20000, textvariable=self.load_batch, width=8).grid(row=0, column=1, padx=8)
        ttk.Label(params, text="Lotes a la vez (Semaphore, solo async)").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Spinbox(params, from_=1, to=100, textvariable=self.load_conc, width=8).grid(row=1, column=1, padx=8)

        ttk.Button(tab, text="Cargar datos", style="Accent.TButton",
                   command=lambda: self.safe(self.do_load)).pack(anchor="w", pady=14)

        result = ttk.LabelFrame(tab, text="Resultado", padding=10)
        result.pack(anchor="w", fill="x")
        self.load_result = tk.StringVar(value="Aún no se ha ejecutado.")
        ttk.Label(result, textvariable=self.load_result, font=(FONT, 12), justify="left").pack(anchor="w")

    def do_load(self):
        # Los valores de los controles se validan antes de iniciar el hilo de trabajo.
        kind = self.load_kind.get()
        batch = self.int_value(self.load_batch.get(), "Tamaño de lote", 1)
        conc = self.int_value(self.load_conc.get(), "Lotes a la vez", 1)
        name = "síncrona" if kind == SYNC else "asíncrona"
        # El callback actualiza el resultado y después refresca los contadores de estado.
        self.run_task(f"Carga masiva ({name})", lambda: backend_load(kind, batch, conc),
                      lambda r: (self.load_result.set(
                          f"App {name}: {r['inserted']:,} insertados de {r['total']:,} · "
                          f"{r['failed']} fallidos · {r['seconds']:.2f} s"), self.check_status()))

    # ------------------------------------------------------------ pestaña CRUD
    def _tab_crud(self, tab):
        # El formulario comparte campos entre crear, leer, actualizar y eliminar.
        ttk.Label(tab, text="CRUD sobre la copia de la app elegida", font=(FONT, 14, "bold")).pack(anchor="w")
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(8, 8))
        self.crud_kind = tk.StringVar(value=ASYNC)
        self.app_selector(top, self.crud_kind).pack(side="left", padx=(0, 16), anchor="n")

        form = ttk.LabelFrame(top, text="Película", padding=8)
        form.pack(side="left", anchor="n")
        self.f_title, self.f_year = tk.StringVar(), tk.StringVar()
        self.f_genres, self.f_id = tk.StringVar(), tk.StringVar()
        for i, (label, var, width) in enumerate((("Título", self.f_title, 34), ("Año", self.f_year, 10),
                                                 ("Géneros (separados por coma)", self.f_genres, 34),
                                                 ("ID (para leer, actualizar y eliminar)", self.f_id, 34))):
            # enumerate conserva la fila del formulario y la tupla define su etiqueta,
            # variable asociada y ancho visual.
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=var, width=width).grid(row=i, column=1, padx=8, pady=3, sticky="w")

        buttons = ttk.Frame(tab)
        buttons.pack(anchor="w", pady=6)
        for text, action in (("Crear", "create"), ("Leer", "read"), ("Actualizar", "update"), ("Eliminar", "delete")):
            # El argumento por defecto de la lambda fija la acción de cada botón.
            ttk.Button(buttons, text=text, command=lambda a=action: self.safe(lambda: self.do_crud(a))
                       ).pack(side="left", padx=(0, 8))
        ttk.Label(tab, text="Actualizar cambia el título y/o el año que estén escritos arriba.",
                  font=(FONT, 9)).pack(anchor="w")

        self.crud_out = tk.Text(tab, height=12, font=(MONO, 11), state="disabled")
        self.crud_out.pack(fill="both", expand=True, pady=(8, 0))
        self.text_widgets.append(self.crud_out)
        self.set_text(self.crud_out, "Carga primero los datos en la pestaña «Carga masiva» si la copia está vacía.")

    def do_crud(self, action):
        # La aplicación seleccionada determina qué backend ejecutará la operación.
        kind = self.crud_kind.get()
        name = "síncrona" if kind == SYNC else "asíncrona"
        kwargs = {}
        if action == "create":
            # Crear construye un documento nuevo a partir de los campos del formulario.
            title = self.f_title.get().strip()
            if not title:
                # El título es el único campo obligatorio del documento.
                raise ValueError("La película debe tener título.")
            movie = {"title": title}
            year = self.int_value(self.f_year.get(), "Año", required=False)
            if year is not None:
                # Los campos opcionales solo se agregan cuando el usuario escribió un valor.
                movie["year"] = year
            genres = [g.strip() for g in self.f_genres.get().split(",") if g.strip()]
            if genres:
                # Se descartan géneros vacíos producidos por comas consecutivas.
                movie["genres"] = genres
            kwargs["movie"] = movie
        else:
            # Las operaciones distintas de crear necesitan un ObjectId existente.
            kwargs["movie_id"] = parse_id(self.f_id.get())
            if action == "update":
                # Update envía únicamente los campos realmente rellenados.
                changes = {}
                if self.f_title.get().strip():
                    changes["title"] = self.f_title.get().strip()
                year = self.int_value(self.f_year.get(), "Año", required=False)
                if year is not None:
                    changes["year"] = year
                if not changes:
                    # Evita ejecutar un update vacío que no produciría un cambio útil.
                    raise ValueError("Escribe un título y/o un año nuevo para actualizar.")
                kwargs["changes"] = changes

        def done(result):
            # El formato de salida depende de la operación y de su resultado.
            if action == "create":
                self.f_id.set(str(result))
                text = f"Película creada.\nID: {result}"
            elif action == "read":
                # None significa que el ID es válido pero no existe en la colección.
                text = ("No existe una película con ese ID." if result is None
                        else json.dumps(result, indent=2, ensure_ascii=False, default=str))
            elif action == "update":
                # modified_count igual a cero puede significar ID inexistente o valores iguales.
                text = f"Documentos modificados: {result}" + ("" if result else "\n(no existe el ID o no hubo cambios)")
            else:
                # delete devuelve cero cuando no encontró el documento.
                text = f"Documentos eliminados: {result}" + ("" if result else "\n(no existe ese ID)")
            self.set_text(self.crud_out, text)

        labels = {"create": "Crear", "read": "Leer", "update": "Actualizar", "delete": "Eliminar"}
        # El callback solo toca widgets y por eso se ejecuta desde _poll en el hilo de Tk.
        self.run_task(f"{labels[action]} ({name})", lambda: backend_crud(kind, action, **kwargs), done)

    # ------------------------------------------------------------ pestaña Consultas
    def _tab_queries(self, tab):
        # La pestaña permite comparar consulta secuencial, gather y TaskGroup.
        ttk.Label(tab, text="Consultas: filtro + proyección + orden, agregación y regex",
                  font=(FONT, 14, "bold")).pack(anchor="w")
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(8, 8))
        self.q_mode = tk.StringVar(value="gather")
        self.app_selector(top, self.q_mode, with_modes=[
            ("Síncrona: una consulta tras otra", "sync"),
            ("Asíncrona con asyncio.gather()", "gather"),
            ("Asíncrona con asyncio.TaskGroup()", "taskgroup")]).pack(side="left", padx=(0, 16), anchor="n")
        params = ttk.LabelFrame(top, text="Parámetros", padding=8)
        params.pack(side="left", anchor="n")
        self.q_year, self.q_genre, self.q_text = tk.StringVar(value="1999"), tk.StringVar(value="Action"), tk.StringVar(value="Matrix")
        for i, (label, var) in enumerate((("Año", self.q_year), ("Género", self.q_genre), ("Texto en el título", self.q_text))):
            # Cada parámetro se coloca en su propia fila y queda ligado a un StringVar.
            ttk.Label(params, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(params, textvariable=var, width=18).grid(row=i, column=1, padx=8, pady=3)
        ttk.Button(top, text="Ejecutar las 3 consultas", style="Accent.TButton",
                   command=lambda: self.safe(self.do_queries)).pack(side="left", padx=16, anchor="n")

        self.q_time = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.q_time, font=(FONT, 12, "bold")).pack(anchor="w", pady=(0, 6))

        grid = ttk.Frame(tab)
        grid.pack(fill="both", expand=True)
        self.trees = []
        for i, (title, cols) in enumerate((("Año + género (orden por título)", ("title", "year")),
                                           ("Top 5 de géneros", ("genre", "count")),
                                           ("Títulos con el texto (máx. 5)", ("title",)))):
            # Cada consulta tiene un Treeview independiente para no mezclar formatos.
            box = ttk.LabelFrame(grid, text=title, padding=6)
            box.grid(row=0, column=i, sticky="nsew", padx=4)
            grid.columnconfigure(i, weight=1)
            tree = ttk.Treeview(box, columns=cols, show="headings", height=12)
            for c in cols:
                # La configuración de cada columna se deriva de su nombre lógico.
                tree.heading(c, text={"title": "Título", "year": "Año", "genre": "Género", "count": "Películas"}[c])
                tree.column(c, width=60 if c in ("year", "count") else 170, anchor="e" if c in ("year", "count") else "w")
            tree.pack(fill="both", expand=True)
            self.trees.append(tree)
        grid.rowconfigure(0, weight=1)

    def do_queries(self):
        # Se validan y normalizan los tres valores antes de contactar MongoDB.
        mode = self.q_mode.get()
        year = self.int_value(self.q_year.get(), "Año", 0)
        genre = self.q_genre.get().strip()
        text = self.q_text.get().strip()
        if not genre or not text:
            # Sin género o texto las consultas no tienen un criterio útil.
            raise ValueError("Escribe un género y un texto para buscar.")
        names = {"sync": "síncrona, en secuencia", "gather": "asíncrona con gather()", "taskgroup": "asíncrona con TaskGroup()"}

        def done(result):
            # El backend devuelve tres resultados y el tiempo total de ejecución.
            (by_year, top, search), seconds = result
            # Se limpian las tres tablas antes de pintar la nueva ejecución.
            for tree in self.trees:
                tree.delete(*tree.get_children())
            for m in by_year:
                # get evita fallar si un documento no contiene un campo proyectado.
                self.trees[0].insert("", "end", values=(m.get("title", ""), m.get("year", "")))
            for g in top:
                # La agregación entrega el género en _id y el total en count.
                self.trees[1].insert("", "end", values=(g["_id"], f"{g['count']:,}"))
            for m in search:
                # La búsqueda solo proyecta el título.
                self.trees[2].insert("", "end", values=(m.get("title", ""),))
            # Se convierte a milisegundos para que el tiempo sea fácil de leer.
            self.q_time.set(f"{names[mode].capitalize()}: {seconds * 1000:.1f} ms para las 3 consultas")

        # El callback rellena las tablas únicamente cuando el backend termina.
        self.run_task(f"Consultas ({names[mode]})", lambda: backend_queries(mode, year, genre, text), done)

    # ------------------------------------------------------------ pestaña Comparación
    def _tab_compare(self, tab):
        # Esta pestaña muestra la salida textual de la comparación independiente.
        ttk.Label(tab, text="Comparación sync vs async (comparacion.py)", font=(FONT, 14, "bold")).pack(anchor="w")
        ttk.Label(tab, wraplength=900, justify="left", text=(
            "Mide carga masiva (2000 documentos en lotes de 100), CRUD y consultas con 1, 10, 50 y 100 peticiones "
            "simultáneas. Cada escenario se corre una vez de calentamiento y tres medidas. Usa una base temporal "
            "(mflix_bench) que se borra al terminar. Puede tardar unos segundos."
        )).pack(anchor="w", pady=(4, 10))
        ttk.Button(tab, text="Ejecutar comparación", style="Accent.TButton",
                   command=self.do_compare).pack(anchor="w")
        self.compare_text = tk.Text(tab, font=(MONO, 10), state="disabled", wrap="none")
        self.compare_text.pack(fill="both", expand=True, pady=(10, 0))
        self.text_widgets.append(self.compare_text)
        scroll = ttk.Scrollbar(self.compare_text, command=self.compare_text.xview, orient="horizontal")
        self.compare_text.configure(xscrollcommand=scroll.set)
        scroll.pack(side="bottom", fill="x")

    def do_compare(self):
        # Se limpia la comparación anterior para que la nueva salida empiece vacía.
        self.set_text(self.compare_text, "")
        # backend_compare publica sus líneas en la cola y _poll las va mostrando.
        self.run_task("Comparación sync vs async", lambda: backend_compare(self.q), lambda _: None)


if __name__ == "__main__":
    App().mainloop()