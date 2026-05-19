import re
from pathlib import Path

import yaml


def load_prompt(prompt_name: str, **kwargs):
    """
    Loads a .prompt.md file, parses configuration,
    and injects data into placeholders.
    """
    # 1. Resolve file path relative to this file
    path = Path(__file__).parent.parent / "prompts" / f"{prompt_name}.prompt.md"

    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    content = path.read_text()

    # 2. Extract YAML Frontmatter vs Markdown Body
    # Regex splits the content between the --- separators
    pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)'
    match = re.search(pattern, content, re.DOTALL | re.MULTILINE)

    if not match:
        return {}, content # Fallback if no frontmatter

    config = yaml.safe_load(match.group(1))
    template = match.group(2)

    # 3. Variable Injection ({{variable}} -> real data)
    final_prompt = template
    for key, value in kwargs.items():
        placeholder = f"{{{{{key}}}}}"
        final_prompt = final_prompt.replace(placeholder, str(value))

    return config, final_prompt
