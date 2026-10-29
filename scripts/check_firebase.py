"""Read-only project checks; never print credential contents or access tokens."""
import argparse
import json
import os
import ssl
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--credentials',required=True,type=Path)
    parser.add_argument('--project',required=True)
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--smoke',action='store_true',help='Verificar páginas públicas com o Firestore real, sem gravar dados.')
    args=parser.parse_args()
    # gRPC ships its own roots. Trust the same installed CAs as Windows, including
    # corporate proxies, without disabling certificate validation.
    trust_file=None
    if sys.platform == 'win32':
        trust_file=tempfile.NamedTemporaryFile(mode='w',suffix='.pem',delete=False)
        for certificate in ssl.create_default_context().get_ca_certs(binary_form=True):
            trust_file.write(ssl.DER_cert_to_PEM_cert(certificate))
        trust_file.close()
        os.environ['GRPC_DEFAULT_SSL_ROOTS_FILE_PATH']=trust_file.name
        os.environ['REQUESTS_CA_BUNDLE']=trust_file.name
    from firebase_backend import clients
    credentials=args.credentials.read_text(encoding='utf-8-sig')
    database,bucket=clients(args.project,credentials,args.bucket)
    print('Conta de serviço: arquivo válido para o projeto informado.')
    checks = [('Firestore',lambda: database.collection('sw_counters').document('users').get(timeout=15,retry=None)),
              ('Storage',lambda: bucket.reload(timeout=15,retry=None))]
    failed=False
    for name,check in checks:
        try:
            check()
            print(name+': acesso confirmado.')
        except Exception as error:
            failed=True
            print(name+': '+type(error).__name__)
            for detail in getattr(error,'errors',()):
                if isinstance(detail,dict):
                    # Google error reason strings do not contain credentials.
                    print('  motivo: '+str(detail.get('reason','não informado')))
    if args.smoke:
        import secrets
        from app import create_app
        app=create_app(dict(DATABASE_BACKEND='firestore',DATABASE_URL='',STORAGE_BACKEND='firebase',
            SERVERLESS=True,SECRET_KEY=secrets.token_hex(32),FIREBASE_PROJECT_ID=args.project,
            FIREBASE_CREDENTIALS_JSON=credentials,FIREBASE_CREDENTIALS_BASE64='',FIREBASE_STORAGE_BUCKET=args.bucket))
        with app.test_client() as client:
            for path in ['/','/cursos','/login']:
                response=client.get(path)
                print('Página '+path+': HTTP '+str(response.status_code))
                failed=failed or response.status_code!=200
    if trust_file: Path(trust_file.name).unlink(missing_ok=True)
    return int(failed)


if __name__=='__main__': sys.exit(main())
