import json
import os
import sys
import urllib.error
import urllib.request


def main() -> None:
    base_url = os.getenv(
        'LIMO_LLM_BASE_URL',
        os.getenv('OPENAI_BASE_URL', 'http://192.168.1.123:8317/v1'),
    ).rstrip('/')
    api_key = os.getenv(
        'LIMO_LLM_API_KEY', os.getenv('OPENAI_API_KEY', '')).strip()

    if not api_key:
        print('Missing LIMO_LLM_API_KEY (or OPENAI_API_KEY).', file=sys.stderr)
        raise SystemExit(2)

    request = urllib.request.Request(
        f'{base_url}/models',
        headers={'Authorization': f'Bearer {api_key}'},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        with opener.open(request, timeout=10) as response:
            payload = json.load(response)
            print(f'HTTP {response.status}')
    except urllib.error.HTTPError as error:
        body = error.read(300).decode('utf-8', errors='replace')
        print(f'HTTP {error.code}: {body}', file=sys.stderr)
        raise SystemExit(3) from error
    except Exception as error:  # noqa: BLE001
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(4) from error

    models = payload.get('data', []) if isinstance(payload, dict) else []
    ids = [item.get('id') for item in models if isinstance(item, dict)]
    ids = [model_id for model_id in ids if model_id]
    print(f'{len(ids)} model(s):')
    for model_id in ids:
        print(f'- {model_id}')


if __name__ == '__main__':
    main()
