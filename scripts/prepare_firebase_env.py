"""Create a git-ignored Vercel import file without printing any secret."""
import argparse
import base64
import json
import secrets
from pathlib import Path
from google.oauth2 import service_account

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--credentials',required=True,type=Path)
    parser.add_argument('--bucket',required=True)
    args=parser.parse_args()
    data=json.loads(args.credentials.read_text(encoding='utf-8-sig'))
    service_account.Credentials.from_service_account_info(data)
    destination=ROOT/'.env.vercel'
    previous={}
    if destination.exists():
        previous=dict(line.split('=',1) for line in destination.read_text().splitlines() if '=' in line)
    key=previous.get('SECRET_KEY') or secrets.token_hex(32)
    values=dict(DATABASE_BACKEND='firestore',STORAGE_BACKEND='firebase',
        FIREBASE_PROJECT_ID=data['project_id'],FIREBASE_STORAGE_BUCKET=args.bucket,
        FIREBASE_CREDENTIALS_BASE64=base64.b64encode(json.dumps(data,separators=(',',':')).encode()).decode(),
        FIREBASE_CREDENTIALS_JSON='',DATABASE_URL='',SECRET_KEY=key,COOKIE_SECURE='1')
    destination.write_text(''.join(f'{k}={v}\n' for k,v in values.items()),encoding='utf-8')
    print('Arquivo privado preparado: '+str(destination))
    print('Importe em Vercel > Settings > Environment Variables > Import .env (Production).')
    print('O arquivo contém credenciais privadas; mantenha fora do Git e não envie em chats.')


if __name__=='__main__': main()
