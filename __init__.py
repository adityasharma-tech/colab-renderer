import os
import bpy
import cgi
import json
import time
import zipfile
import mimetypes
import threading
import subprocess
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

bl_info = {
    "name": "Colab Render Bridge",
    "author": "Aditya Sharma",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "category": "Render",
}

STATE = {
    "available": True,
    "action": "render",
    "data": {
        "cpu_enabled": False,
        "gpu_enabled": True,
        "optix_enabled": False,
        "filepath": "golden_hour.blend",
        "start_frame": 1,
        "refetch": False
    },
    "status": "idle",  # 'rendering', 'idle'
}

def load_image(image_path):
    if not os.path.exists(image_path):
        print("Image not found:", image_path)
        return None

    image_name = os.path.basename(image_path)
    image = bpy.data.images.get(image_name)

    if image is None:
        image = bpy.data.images.load(image_path)

    return image

def show_image_in_editor(image):
    try:
        for area in bpy.context.window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = image
                return True
        return False
    except Exception as e:
        print(e)
        return False
def open_image_in_new_window(image):
    try:
        bpy.ops.screen.area_dupli('INVOKE_DEFAULT')

        area = bpy.context.window.screen.areas[-1]
        area.type = 'IMAGE_EDITOR'
        area.spaces.active.image = image
    except Exception as e:
        print(e)
        
def create_project_zip():
    if not bpy.context.blend_data.filepath:
        return None

    blend_path = bpy.context.blend_data.filepath
    project_dir = os.path.dirname(blend_path)
    project_name = os.path.basename(project_dir.rstrip(os.sep))
    zip_name = f"{project_name}.zip"
    zip_path = os.path.join(project_dir, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            for file in files:
                if file == zip_name:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, project_dir)
                zf.write(full_path, arcname=rel_path)

    return zip_name


class SimpleHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/render":
            # self.send_response(200)
            # self.send_header("Content-Type", "application/json")
            # self.end_headers()

            # self.wfile.write(
            #     json.dumps({"status": "saved", "path": ""}).encode("utf-8")
            # )
            self.handle_render_post()
        else:
            self.send_response(404)
            self.end_headers()    

    def do_GET(self):
        if self.path == "/available":
            self.handle_available()
        elif self.path.startswith("/download"):
            self.handle_download()
        elif self.path == "/refresh":
            self.handle_refresh()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_available(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        STATE["data"]["filepath"] = os.path.basename(bpy.context.blend_data.filepath)

        if STATE["action"] == "zip" and "zip_file" not in STATE["data"]:
            zip_name = create_project_zip()
            STATE["data"]["zip_file"] = zip_name

        response = {
            "available": STATE["available"],
            "action": STATE["action"],
            "data": STATE["data"],
        }

        self.wfile.write(json.dumps(response).encode("utf-8"))

    def handle_render_post(self):
        if not bpy.context.blend_data.filepath:
            self.send_response(400)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type")
        if not content_type:
            self.send_response(400)
            self.end_headers()
            return
        
        content_length = int(self.headers.get("Content-Length", 0))

        form = cgi.FieldStorage(
        fp=self.rfile,
        headers=self.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": content_length,
            },
        )

        if "image" not in form:
            self.send_response(400)
            self.end_headers()
            return

        image_field = form["image"]
        image_data = image_field.file.read()
        filename = image_field.filename or "render.png"

        blend_dir = os.path.dirname(bpy.context.blend_data.filepath)
        render_dir = os.path.join(blend_dir, "renders")
        os.makedirs(render_dir, exist_ok=True)

        image_path = os.path.join(render_dir, filename)

        with open(image_path, "wb") as f:
            f.write(image_data)

        image = load_image(image_path)

        if not show_image_in_editor(image):
            open_image_in_new_window(image)

        STATE["status"] = "done"
        STATE["available"] = False
        STATE["action"] = None

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        self.wfile.write(
            json.dumps({"status": "saved", "path": image_path}).encode("utf-8")
        )


    def handle_refresh(self):
        if not bpy.context.blend_data.filepath:
            self.send_response(404)
            self.end_headers()
            return

        blend_path = bpy.context.blend_data.filepath
        filename = os.path.basename(blend_path)
        file_size = os.path.getsize(blend_path)

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(file_size))
        self.end_headers()

        with open(blend_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)


    def handle_download(self):
        zip_file = STATE["data"].get("zip_file")

        if not zip_file:
            self.send_response(404)
            self.end_headers()
            return

        blend_path = bpy.context.blend_data.filepath
        project_dir = os.path.dirname(blend_path)
        file_path = os.path.join(project_dir, zip_file)

        if not os.path.exists(file_path):
            self.send_response(404)
            self.end_headers()
            return

        mime_type, _ = mimetypes.guess_type(file_path)
        file_size = os.path.getsize(file_path)

        self.send_response(200)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{zip_file}"')
        self.send_header("Content-Length", str(file_size))
        self.end_headers()

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)

        STATE["available"] = False

    def log_message(self, format, *args):
        return


httpd = None
server_thread = None
ngrok_process = None


def start_http_server(port):
    global httpd
    httpd = HTTPServer(("127.0.0.1", port), SimpleHandler)
    httpd.serve_forever()


def stop_http_server():
    global httpd
    if httpd:
        httpd.shutdown()
        httpd = None


def start_ngrok_cli(port):
    global ngrok_process
    ngrok_process = subprocess.Popen(
        ["ngrok", "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_ngrok_cli():
    global ngrok_process
    if ngrok_process:
        ngrok_process.terminate()
        ngrok_process = None


def get_ngrok_url(retries=10, delay=0.5):
    for _ in range(retries):
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as resp:
                data = json.loads(resp.read().decode())
                for tunnel in data.get("tunnels", []):
                    if tunnel.get("proto") == "https":
                        return tunnel.get("public_url")
        except Exception:
            pass
        time.sleep(delay)
    return ""


class ColabRenderProperties(bpy.types.PropertyGroup):
    server_url: bpy.props.StringProperty(
        name="Server URL",
        default="",
    )

    server_running: bpy.props.BoolProperty(default=False)

    gpu_enable: bpy.props.BoolProperty(default=True)
    cpu_enable: bpy.props.BoolProperty(default=False)
    optix_enable: bpy.props.BoolProperty(default=False)
    refetch: bpy.props.BoolProperty(default=False)


class COLABRENDER_PT_panel(bpy.types.Panel):
    bl_label = "Colab Renderer"
    bl_idname = "COLABRENDER_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Colab Renderer"

    def draw(self, context):
        layout = self.layout
        props = context.scene.colab_render

        layout.label(text="Server URL")
        row = layout.row()
        row.enabled = False
        row.prop(props, "server_url")

        layout.operator(
            "colab.copy_server_url", text="Copy Server URL", icon="COPYDOWN"
        )

        layout.separator()
        layout.prop(props, "gpu_enable")
        layout.prop(props, "cpu_enable")
        layout.prop(props, "optix_enable")

        layout.separator()
        layout.prop(props, "refetch")

        layout.separator()
        layout.operator("colab.render", icon="EXPORT")

        if props.server_running:
            layout.operator("colab.toggle_server", text="Stop Server", icon="CANCEL")
        else:
            layout.operator("colab.toggle_server", text="Start Server", icon="PLAY")


class COLABRENDER_OT_render(bpy.types.Operator):
    bl_idname = "colab.render"
    bl_label = "Render Current Frame"

    def execute(self, context):
        props = context.scene.colab_render
        STATE["action"] = "render"
        STATE["data"] = {
            "optix_enabled": props.optix_enable,
            "gpu_enabled": props.gpu_enable,
            "cpu_enabled": props.cpu_enable,
            "filename": os.path.basename(bpy.context.blend_data.filepath),
            "start_frame": 1,
            "refetch": props.refetch
        }
        STATE["available"] = True
        self.report({"INFO"}, "Rendering current frame")
        return {"FINISHED"}


class COLABRENDER_OT_copy_url(bpy.types.Operator):
    bl_idname = "colab.copy_server_url"
    bl_label = "Copy Server URL"

    def execute(self, context):
        bpy.context.window_manager.clipboard = context.scene.colab_render.server_url
        self.report({"INFO"}, "Server URL copied to clipboard")
        return {"FINISHED"}


class COLABRENDER_OT_toggle_server(bpy.types.Operator):
    bl_idname = "colab.toggle_server"
    bl_label = "Toggle Server"

    def execute(self, context):
        props = context.scene.colab_render
        port = 48729

        if not props.server_running:
            global server_thread
            server_thread = threading.Thread(
                target=start_http_server, args=(port,), daemon=True
            )
            server_thread.start()

            start_ngrok_cli(port)
            props.server_url = get_ngrok_url()
            props.server_running = True
            self.report({"INFO"}, "Server started")

        else:
            stop_ngrok_cli()
            stop_http_server()
            props.server_running = False
            props.server_url = ""
            self.report({"INFO"}, "Server stopped")

        return {"FINISHED"}


classes = (
    ColabRenderProperties,
    COLABRENDER_PT_panel,
    COLABRENDER_OT_render,
    COLABRENDER_OT_toggle_server,
    COLABRENDER_OT_copy_url,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.colab_render = bpy.props.PointerProperty(type=ColabRenderProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.colab_render
