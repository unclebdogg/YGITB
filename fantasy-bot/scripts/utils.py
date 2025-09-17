import os
from dotenv import load_dotenv
import yaml

load_dotenv()

def get_env(name, default=None, cast=str):
    val = os.getenv(name, default)
    if val is None:
        return None
    return cast(val) if (cast and val is not None) else val

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def render_template(tpl: str, **kwargs) -> str:
    out = tpl
    for k, v in kwargs.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
