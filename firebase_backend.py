"""Server-only Firebase clients. Credentials never enter HTML or static files."""
import json
import base64
import binascii
from functools import lru_cache
from google.oauth2 import service_account
from google.cloud import firestore, storage


@lru_cache(maxsize=4)
def clients(project, credentials_json, bucket):
    try:
        info = json.loads(credentials_json)
        if info.get('project_id') != project:
            raise ValueError('project mismatch')
        credentials = service_account.Credentials.from_service_account_info(info)
    except (ValueError, TypeError, KeyError):
        raise RuntimeError('Configure FIREBASE_CREDENTIALS_JSON com a conta de serviço do mesmo projeto Firebase.') from None
    return (firestore.Client(project=project, credentials=credentials),
            storage.Client(project=project, credentials=credentials).bucket(bucket))


def configured_clients(config):
    credentials=config.get('FIREBASE_CREDENTIALS_JSON','')
    if not credentials and config.get('FIREBASE_CREDENTIALS_BASE64'):
        try:
            credentials=base64.b64decode(config['FIREBASE_CREDENTIALS_BASE64'],validate=True).decode('utf-8')
        except (ValueError,UnicodeError,binascii.Error):
            raise RuntimeError('FIREBASE_CREDENTIALS_BASE64 inválido. Gere novamente o arquivo privado de configuração.') from None
    return clients(config['FIREBASE_PROJECT_ID'], credentials, config['FIREBASE_STORAGE_BUCKET'])
