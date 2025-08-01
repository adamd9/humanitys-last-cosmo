import json
from typing import Any, Union


def parse_choice_json(text: str) -> Union[dict[str, Any], None]:
    """Parse the model response for choice JSON."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        # attempt simple extraction
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            snippet = text[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return None
        return None
