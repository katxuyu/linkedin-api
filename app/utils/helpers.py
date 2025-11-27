import re
from jinja2 import Template, Environment, meta, TemplateError, StrictUndefined
from datetime import timedelta

def render_message(template_str: str, variables: dict) -> str:
    """
    Render a Jinja2 template string with strict variable checking.
    Raises an error if any variable is missing.
    """
    try:
        env = Environment(undefined=StrictUndefined)
        template = env.from_string(template_str)
        return template.render(**variables)
    except TemplateError as e:
        raise ValueError(f"Template rendering failed: {e}")

def extract_template_variables(template_message: str) -> set[str]:
    """
    Extract variable names from a template string supporting both
    Jinja2-style {{ variable }} and Python-style {variable} placeholders.
    """
    if not template_message:
        return set()

    variables = set()

    # --- 1️⃣ Extract Jinja-style {{ variable }} ---
    try:
        env = Environment()
        ast = env.parse(template_message)
        jinja_vars = meta.find_undeclared_variables(ast)
        variables.update(jinja_vars)
    except Exception:
        raise ValueError
        #pass  # fallback to regex if Jinja parsing fails

    # --- 2️⃣ Extract {variable} placeholders (Python format-style) ---
    # Avoid matching double braces or formatting specifiers like {var!r:10}
    curly_vars = re.findall(r'(?<!{){([a-zA-Z_][a-zA-Z0-9_]*)}(?!})', template_message)
    variables.update(curly_vars)

    # --- 3️⃣ Optionally: Extract %%variable%% or other custom markers ---
    percent_vars = re.findall(r'%{1,2}\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*%{1,2}', template_message)
    variables.update(percent_vars)

    return variables

def normalize_timedelta_to_standard_format(td: timedelta) -> timedelta:
    """
    Normalize timedelta to always have explicit days, hours, minutes, and seconds components.
    This ensures consistent storage format in the database.
    """
    total_seconds = int(td.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
