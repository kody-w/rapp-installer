class BasicAgent:
    """Base class for all RAPP Brainstem agents. Extend this in your private agent files."""

    def __init__(self):
        # Only set defaults if subclass hasn't defined them
    if not hasattr(self, "name"):
    self.name = "BasicAgent"
    if not hasattr(self, "metadata"):
    self.metadata = {
        "name": self.name,
        "description": "Base agent -- override this.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }

    def perform(self, **kwargs):
    return "Not implemented."

    def to_tool(self):
    """Returns OpenAI function-calling tool definition."""
    return {
        "type": "function",
        "function": {
            "name": self.name,
            "description": self.metadata.get("description", ""),
            "parameters": self.metadata.get("parameters", {"type": "object", "properties": {}})
        }
    }
