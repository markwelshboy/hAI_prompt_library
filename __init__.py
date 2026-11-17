"""hAI Prompt Library ComfyUI custom-node entrypoint."""
from .comfyui_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

try:
    from server import PromptServer  # type: ignore
except ImportError:
    PromptServer = None
if PromptServer is not None:
    from .playground_api import register_routes
    register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
