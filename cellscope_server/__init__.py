from .handlers import setup_handlers

__all__ = ["setup_handlers"]



def _jupyter_server_extension_points():
    return [{"module": "cellscope_server"}]


def _load_jupyter_server_extension(server_app):
    setup_handlers(server_app)
    server_app.log.info("CellScope server extension loaded")
