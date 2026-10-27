from waitress import serve
from app import create_app

if __name__ == '__main__':
    print('SW Cursos disponível em http://127.0.0.1:5000', flush=True)
    serve(create_app(), host='127.0.0.1', port=5000)
