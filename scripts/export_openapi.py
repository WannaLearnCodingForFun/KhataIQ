"""Write the API's OpenAPI document; the frontend generates its types from it.

    python scripts/export_openapi.py > frontend/openapi.json
"""

import json

from khataiq.api.main import create_app

if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), indent=1, sort_keys=True))
