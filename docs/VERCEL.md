# Publicar a SW Cursos na Vercel pelo GitHub

O código foi adaptado para Vercel com **PostgreSQL** e **bucket privado compatível com S3**. Firebase não é obrigatório. A versão local continua funcionando com SQLite e arquivos em `instance/uploads`.

Esta entrega prepara o código; **não cria contas, contrata serviços, envia dados nem publica automaticamente**.

## 1. Preparar os serviços

- Crie um PostgreSQL acessível pela aplicação. Copie a URL de conexão com SSL (`postgresql://…?sslmode=require`). Para aplicações serverless, prefira a URL com pooling do provedor. Para migrações, use conexão direta se o provedor não aceitar operações de esquema pelo pooler.
- Crie um bucket dedicado, **privado**, compatível com a API S3. Pode ser AWS S3, Cloudflare R2 ou outro provedor compatível. Não habilite hospedagem pública do bucket. Gere uma credencial com acesso somente a esse bucket para ler, gravar e excluir objetos.
- Copie o endpoint HTTPS do serviço, o nome do bucket, a região e as credenciais. O endpoint não deve incluir o nome do bucket. Para R2, use a região `auto`; para AWS, a região real e seu endpoint regional S3.
- Não publique credenciais no GitHub nem as envie em mensagens. Elas serão configuradas como variáveis privadas no painel da Vercel.

O plano Hobby da Vercel é limitado a uso pessoal não comercial. Para a operação comercial da escola, escolha um plano compatível e confira custos de Vercel, banco e arquivos. Não é prometida hospedagem gratuita. [Regras do plano Hobby](https://vercel.com/docs/plans/hobby).

## 2. Variáveis necessárias

Configure em **Project → Settings → Environment Variables**:

| Nome | Valor/origem |
| --- | --- |
| `SECRET_KEY` | Chave aleatória exclusiva, com pelo menos 32 caracteres |
| `DATABASE_URL` | URL PostgreSQL do provedor com SSL |
| `STORAGE_BACKEND` | `s3` |
| `S3_ENDPOINT_URL` | Origem HTTPS do armazenamento, sem bucket no caminho |
| `S3_BUCKET` | Nome do bucket privado |
| `S3_ACCESS_KEY_ID` | Identificador da credencial do bucket |
| `S3_SECRET_ACCESS_KEY` | Segredo dessa credencial |
| `S3_REGION` | Região informada pelo provedor (`auto` em R2) |
| `COOKIE_SECURE` | `1` |

A Vercel define `VERCEL=1` automaticamente. Nesse ambiente o sistema exige PostgreSQL/S3 e força cookies HTTPS. Não há fallback para SQLite ou `/tmp` que poderia perder dados. Use bancos e buckets separados para Preview e Production se habilitar previews; não conecte testes de branches aos dados reais.

Gere a chave na sua máquina:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

## 3. Preparar o banco, antes do primeiro deploy

Atualize dependências:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

Pare o servidor local e faça backup de `instance` e `.env` antes de transferir dados. Preserve uma cópia de `.env` em `.env.local-backup` (ignorada pelo Git). Configure temporariamente seu `.env` com as variáveis de destino acima; mantenha `DATABASE=instance/sw.sqlite3` para identificar o arquivo local de origem, mas a conexão de destino será selecionada por `DATABASE_URL`.

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app init-db
```

Isso cria o esquema PostgreSQL versionado. Nenhuma migração ou administrador é criado em uma requisição pública ou durante o build.

Escolha **uma** opção:

**A. Levar os cadastros e arquivos locais atuais para a nuvem:**

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app import-local --source instance/sw.sqlite3 --uploads instance/uploads
```

O destino precisa estar vazio, exceto pelo esquema. O comando preserva IDs, usuários, hashes de senha, cursos, matrículas, contatos, configurações, auditoria, fotos, anúncios e materiais. Ajusta as sequências de IDs no PostgreSQL e copia os arquivos para o bucket. O banco e arquivos locais não são apagados nem alterados. Tentativas temporárias de login não são transferidas. Se falhar, a transação do banco é desfeita; objetos sem referência podem permanecer no bucket e devem ser conferidos pelo operador antes de qualquer limpeza. Não execute em uma aplicação de destino que já esteja recebendo cadastros.

**B. Começar com um banco vazio:**

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app create-admin
```

Crie seu administrador com senha oculta no terminal. Não crie outro administrador se ele já veio pela importação. O seed de demonstração é opcional e não é executado automaticamente.

Depois da preparação, restaure o `.env` local a partir da cópia preservada para continuar trabalhando localmente sem alterar o banco de produção. Não deixe credenciais de produção na configuração usada para testes.

## 4. Subir o código e importar na Vercel

1. Envie os arquivos do projeto para seu repositório **privado** do GitHub, preservando o caráter proprietário. `.env`, `instance`, `.venv`, `.vercel` e `public` gerado não devem ser versionados. As imagens de marca em `static` e as migrações devem ir para o repositório.
2. Na Vercel, escolha **Add New → Project**, conecte o GitHub e selecione esse repositório.
3. Selecione a raiz do projeto e o framework **Flask**. O projeto usa Python 3.12 e `wsgi:app`, declarado em `pyproject.toml`. Não use `run.py`, Waitress, `localhost` ou um comando para manter servidor aberto na Vercel.
4. Configure as variáveis da seção 2 **antes** de clicar em Deploy.
5. Mantenha o build definido no projeto. Ele executa `python scripts/build_vercel.py`, copiando somente os arquivos públicos de `static` para `public/static` e o service worker para `public/sw.js`.
6. Publique quando decidir. Confira os logs de build e aplicação. Depois, conecte o domínio da escola pelo painel, se houver.

O código não foi enviado ao GitHub nem publicado por esta adaptação. A conexão do repositório e a publicação precisam ser feitas na sua conta.

## 5. Limites e proteção dos arquivos

- Uploads pela aplicação na Vercel ficam limitados a **4 MB por requisição**, abaixo do limite de 4,5 MB da plataforma. O limite local continua 10 MB. Formulários e erros mostram o limite do ambiente. Para novos PDFs maiores, reduza o arquivo ou use um link externo autorizado; upload direto de arquivos grandes ao bucket não foi implementado.
- Arquivos existentes maiores podem ser transferidos pelo comando de importação, fora da Vercel. O download remoto usa redirecionamento assinado e não passa o conteúdo do arquivo pela função.
- Antes de liberar um material, a aplicação verifica usuário, matrícula e estado do curso. A URL assinada vale por **60 segundos** e deve ser tratada como um link temporário de acesso: pode continuar válida até expirar, mesmo se a matrícula for removida nesse intervalo. Não compartilhe essas URLs.
- Fotos/anúncios também usam URLs curtas do bucket privado; a política CSP permite imagens apenas do próprio site e do endpoint configurado. Conteúdo HTML continua escapado, com CSRF e controle de perfil.
- Não é necessário tornar o bucket público nem habilitar CORS para upload, pois a aplicação envia arquivos ao bucket pelo servidor.
- Nenhum dado pessoal ou material privado entra no cache offline. O modo offline continua limitado à orientação estática.

## 6. Testar e manter

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_sw.mjs
.\.venv\Scripts\python.exe scripts/build_vercel.py
```

Os testes locais usam SQLite e pastas temporárias. Os testes de S3 usam respostas simuladas e verificam operações, URLs com validade curta e autorização antes da geração do link. O teste PostgreSQL real só executa se `TEST_DATABASE_URL` for configurada para um banco de **teste**, no formato de URL PostgreSQL: cria um esquema temporário isolado e o remove ao final. É necessário que o usuário do teste possa criar esquemas. Não configure essa variável com credenciais de produção.

Antes de usar dados reais, valide no ambiente publicado: início/catálogo, contato, login/logout, criação de curso/aluno/matrícula, uploads, fotos/anúncios, material autorizado e bloqueio sem matrícula, limite de upload, persistência após novo deploy e recuperação de backups. Configurar variáveis sem criar as tabelas causará erro de banco.

Backups em nuvem precisam incluir **PostgreSQL e bucket**, não somente `instance`. Configure exportações/backups no provedor de banco e proteção/versões de objetos conforme a política da escola. Teste a restauração para uma instalação separada. Alterar uma variável na Vercel exige novo deploy para atualizar o ambiente da aplicação.

Não foi possível validar publicação, conectividade PostgreSQL real ou bucket real sem as contas e credenciais. Nenhuma credencial foi inventada.

Referências: [Flask na Vercel](https://vercel.com/docs/frameworks/backend/flask), [limites das funções](https://vercel.com/docs/functions/limitations), [S3/R2 com boto3](https://developers.cloudflare.com/r2/examples/aws/boto3/).
