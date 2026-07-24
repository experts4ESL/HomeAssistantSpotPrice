"""Allow importing the API module without importing Home Assistant setup code."""

import sys
import types
from pathlib import Path

PACKAGE = Path(__file__).parents[1] / "custom_components" / "oeko_spot"
custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(PACKAGE.parent)]
sys.modules.setdefault("custom_components", custom_components)
oeko_spot = types.ModuleType("custom_components.oeko_spot")
oeko_spot.__path__ = [str(PACKAGE)]
sys.modules.setdefault("custom_components.oeko_spot", oeko_spot)

