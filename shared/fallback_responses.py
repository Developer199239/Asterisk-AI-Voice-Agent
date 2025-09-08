"""
Fallback Response Mechanisms

This module provides a system for generating scripted fallback responses when
the primary LLM services are unavailable.
"""

import json
import random
from typing import Dict, List, Optional

class FallbackResponseManager:
    """Manages loading and selecting fallback responses."""

    def __init__(self, templates: Optional[Dict[str, List[str]]] = None):
        if templates is None:
            self.templates = self._get_default_templates()
        else:
            self.templates = templates

    def _get_default_templates(self) -> Dict[str, List[str]]:
        """Get the default fallback response templates."""
        return {
            "GREETING": [
                "Hello, thank you for calling. How can I assist you?",
                "Hi there! How can I help you today?",
            ],
            "ERROR_GENERIC": [
                "I'm sorry, I'm having some technical difficulties. Please call back later.",
                "It seems I'm unable to process your request at the moment. Please try again shortly.",
            ],
            "ERROR_STT": [
                "I'm sorry, I didn't catch that. Could you please repeat yourself?",
                "I'm having trouble understanding you. Could you speak a bit more clearly?",
            ],
            "GOODBYE": [
                "Thank you for calling. Goodbye!",
                "Have a great day! Goodbye.",
            ],
        }

    def get_response(self, category: str) -> Optional[str]:
        """Get a random response from a given category."""
        if category in self.templates:
            return random.choice(self.templates[category])
        return None

    def load_from_json(self, file_path: str):
        """Load fallback templates from a JSON file."""
        with open(file_path, 'r') as f:
            self.templates = json.load(f)

# Example usage
if __name__ == "__main__":
    manager = FallbackResponseManager()
    print("Generic Error:", manager.get_response("ERROR_GENERIC"))
    print("Greeting:", manager.get_response("GREETING"))
    print("Unknown:", manager.get_response("UNKNOWN_CATEGORY"))
