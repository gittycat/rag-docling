import os
import sys

def get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        print(f"ERROR: Required environment variable '{var_name}' is not set.", file=sys.stderr)
        print(f"Please define {var_name} in docker-compose.yml", file=sys.stderr)
        sys.exit(1)
    return value
