import bpy
import threading
import subprocess
import json
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

bl_info = {
    "name": "Colab Render Bridge",
    "author": "Aditya Sharma",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "category": "Render",
}

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Colab Render Bridge Server Running")

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
        stderr=subprocess.DEVNULL
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
            "colab.copy_server_url",
            text="Copy Server URL",
            icon="COPYDOWN"
        )

        layout.separator()
        layout.prop(props, "gpu_enable")
        layout.prop(props, "cpu_enable")
        layout.prop(props, "optix_enable")

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
                target=start_http_server,
                args=(port,),
                daemon=True
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
