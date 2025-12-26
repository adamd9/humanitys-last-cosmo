"""Model configuration loader for LLM Pop Quiz Bench."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from ..adapters.mock_adapter import MockAdapter
from ..adapters.openrouter_adapter import OpenRouterAdapter
from .openrouter import strip_prefix


class ModelConfig:
    """Configuration for a single OpenRouter model."""

    def __init__(self, config_dict: dict):
        self.id = config_dict["id"]
        self.model = strip_prefix(self.id)
        self.api_key_env = "OPENROUTER_API_KEY"
        self.description = config_dict.get("description", "")
        self.default_params = config_dict.get("defaultParams", {})
        self.max_concurrency = config_dict.get("maxConcurrency", 1)

    def is_available(self, use_mocks: bool = False) -> bool:
        """Check if this model is available (has API key or is in mock mode)."""
        if use_mocks:
            return True
        return bool(os.environ.get(self.api_key_env))

    def create_adapter(self, use_mocks: bool = False):
        """Create the appropriate adapter for this model."""
        if use_mocks:
            adapter = MockAdapter(model=self.id)
        else:
            adapter = OpenRouterAdapter(model=self.model, api_key_env=self.api_key_env)

        # Override the adapter's ID to use our unique model ID
        adapter.id = self.id
        # Pass through the default parameters from model configuration
        adapter.default_params = self.default_params
        return adapter


class ModelConfigLoader:
    """Loads and manages model configurations (groups + overrides)."""
    
    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            # Default to config/models.yaml relative to project root
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "models.yaml"
        
        self.config_path = config_path
        self._config = None
        self._models = None
        self._model_groups = None
    
    def _load_config(self):
        """Load the configuration file."""
        if self._config is None:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
            
            # Parse model overrides
            self._models = {}
            for model_dict in self._config.get("models", []):
                model_config = ModelConfig(model_dict)
                self._models[model_config.id] = model_config

            # Parse model groups
            self._model_groups = self._config.get("model_groups", {})
    
    @property
    def models(self) -> Dict[str, ModelConfig]:
        """Get model overrides keyed by model id."""
        if self._models is None:
            self._load_config()
        return self._models
    
    @property
    def model_groups(self) -> Dict[str, List[str]]:
        """Get all model groups."""
        if self._model_groups is None:
            self._load_config()
        return self._model_groups
    
    def get_model(self, model_id: str) -> Optional[ModelConfig]:
        """Get a specific model configuration."""
        return self.models.get(model_id)
    
    def get_models_by_group(self, group_name: str) -> List[ModelConfig]:
        """Get models from a specific group."""
        if group_name not in self.model_groups:
            raise ValueError(f"Unknown model group: {group_name}")

        model_ids = self.model_groups[group_name]
        return [self.get_model(model_id) or ModelConfig({"id": model_id}) for model_id in model_ids]
    
    def create_adapters(self, model_ids: List[str], use_mocks: bool = False) -> List:
        """Create adapters for the specified model IDs."""
        adapters = []
        for model_id in model_ids:
            model_config = self.get_model(model_id) or ModelConfig({"id": model_id})
            if model_config.is_available(use_mocks):
                adapter = model_config.create_adapter(use_mocks)
                adapters.append(adapter)
        return adapters


# Global instance
model_config_loader = ModelConfigLoader()
