# Usar Firebase com a Vercel

Esta opção usa **Cloud Firestore Standard (modo nativo)** e **Cloud Storage for Firebase**. Não precisa de PostgreSQL, S3 nem Firebase SQL Connect. Realtime Database não é compatível com este backend. O login da escola continua sendo o login do próprio sistema; não é necessário habilitar Firebase Authentication.

Projeto informado: `swcursos-325a3`. Bucket informado na configuração web: `swcursos-325a3.firebasestorage.app`. Esses identificadores não confirmam que o banco e o armazenamento já estejam habilitados.

## 1. No projeto Firebase existente

1. Em **Build → Firestore Database**, crie o banco `(default)` em modo produção, se ainda não existir. Selecione uma região adequada. Não use regras públicas/modo teste.
2. Em **Build → Storage**, prepare o bucket e copie seu nome exato, sem `gs://`. O nome pode terminar em `.firebasestorage.app` ou `.appspot.com`; não invente o sufixo.
3. Storage requer o plano Blaze com faturamento vinculado. Consulte o painel antes de habilitar: uso de banco, arquivos e tráfego pode gerar cobranças. Não há promessa de funcionamento gratuito.
4. Em **Configurações do projeto → Contas de serviço**, gere uma chave privada de conta de serviço. Guarde o arquivo JSON localmente, fora do repositório. Não envie o conteúdo em chats. `firebaseConfig` do aplicativo web e `apiKey` não substituem essa conta de serviço.
5. A conta precisa de acesso ao Firestore (papel Cloud Datastore User) e aos objetos do bucket (Storage Object User, limitado ao bucket). A chave permite assinar URLs temporárias diretamente, sem tornar os arquivos públicos.

## 2. Na Vercel

Em **Settings → Environment Variables**, configure para **Production**:

| Nome | Valor |
| --- | --- |
| `DATABASE_BACKEND` | `firestore` |
| `STORAGE_BACKEND` | `firebase` |
| `FIREBASE_PROJECT_ID` | ID mostrado nas configurações do projeto |
| `FIREBASE_STORAGE_BUCKET` | Nome exato do bucket |
| `FIREBASE_CREDENTIALS_JSON` | Todo o conteúdo do JSON privado da conta de serviço |
| `SECRET_KEY` | Chave aleatória exclusiva com pelo menos 32 caracteres |
| `COOKIE_SECURE` | `1` |

Remova `DATABASE_URL` ao selecionar Firestore. Variáveis `S3_*` não são usadas. Não coloque credenciais em `vercel.json`, arquivos públicos ou variáveis com prefixo público. Preview deve usar outro projeto/bucket para não alterar dados de produção.

Para importar tudo de uma vez, execute o comando abaixo com o caminho do JSON baixado:

```powershell
.venv/Scripts/python.exe scripts/prepare_firebase_env.py --credentials C:/caminho/conta-privada.json --bucket swcursos-325a3.firebasestorage.app
```

Ele cria `.env.vercel`, ignorado pelo Git, para **Environment Variables → Import .env → Production**. O arquivo contém `FIREBASE_CREDENTIALS_BASE64` em vez de JSON multilinha, evitando erros de colagem. Base64 **não é criptografia**: trate esse valor como a própria chave privada. Deixe `FIREBASE_CREDENTIALS_JSON` vazio ao usar a alternativa Base64. O script não altera seu `.env` local e preserva a chave de sessão quando executado novamente.

Gere a chave de sessão localmente (não publique a saída):

```powershell
.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Depois que o código atualizado estiver no GitHub, faça **Redeploy** na Vercel. Variáveis alteradas só passam a valer em um novo deploy. Não existe criação automática de administrador em uma página pública.

## 3. Preparar o primeiro acesso

Na máquina local, instale as dependências atualizadas. Preserve seu `.env` local antes de mudar de banco. Configure temporariamente as mesmas variáveis Firebase em `.env`. Nesse arquivo, `FIREBASE_CREDENTIALS_JSON` precisa estar inteiro em **uma linha**, sem aspas extras envolvendo o JSON.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
.venv/Scripts/python.exe -m flask --app app:create_app init-db
.venv/Scripts/python.exe -m flask --app app:create_app create-admin
```

`init-db` verifica acesso ao Firestore. Coleções são criadas conforme os cadastros forem inseridos; não há tabelas SQL para migrar. O administrador informa a senha com entrada oculta. Para começar sem cursos de demonstração, não execute `seed-demo`.

O comando `import-local` para Firebase permite transferir uma instalação SQLite pequena para um destino vazio, com o site fora de uso. Faça backup antes; consulte o limite que o comando informa. Nunca use `create-admin` antes da importação, pois o destino precisa estar vazio. O banco e arquivos originais são preservados. Restaure o `.env` local quando terminar para evitar operar produção por engano.

## 4. Segurança e funcionamento

- O navegador acessa o Flask; somente o servidor acessa Firebase com a conta de serviço. As regras de clientes devem negar leitura e escrita nas coleções `sw_*` e na pasta `sw-cursos/` do bucket. Acesso administrativo do servidor é controlado por IAM, não pelas regras de clientes.
- Em um projeto **exclusivo desta aplicação**, as regras abaixo podem negar todo acesso direto de clientes. Em um projeto compartilhado, adapte as regras existentes: nenhuma regra mais ampla pode permitir acesso às coleções/arquivos da escola.

Firestore:

```text
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} { allow read, write: if false; }
  }
}
```

Storage:

```text
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    match /{path=**} { allow read, write: if false; }
  }
}
```

- Arquivos ficam privados em `sw-cursos/`. Downloads usam URLs assinadas de 60 segundos, emitidas após a autorização. Uma URL já emitida pode funcionar até expirar após a remoção de matrícula.
- IDs numéricos e e-mails exclusivos são protegidos por transações Firestore. Cursos excluídos continuam bloqueados na área pública e do aluno.
- Não há cópia temporária do banco em `/tmp` nem dados persistidos no disco da Vercel.
- As listas administrativas e a busca atual não são paginadas. O adaptador usa índices simples para filtrar e ordena os resultados para exibição no servidor. Catálogos/volumes grandes exigem paginação e índices específicos; não há busca de texto completo integrada.
- Faça backups do Firestore **e** do bucket. SQLite local não é um backup da instalação Firebase.

## 5. Conferir após publicar

Abra início, catálogo e login; entre como administrador, cadastre curso/aluno e faça uma matrícula. Envie foto, anúncio e PDF, confirme downloads permitidos e negados e confira persistência após novo deploy. Na Vercel, uploads continuam limitados a 4 MB por requisição.

Os testes automatizados cobrem os fluxos com um substituto em memória do cliente Firebase e armazenamento simulado. Eles não confirmam as permissões, cobrança, regras e conectividade do seu projeto real. Essa validação depende da configuração privada na sua conta.

Referências: [Firestore no servidor](https://firebase.google.com/docs/firestore/quickstart-server), [contas de serviço](https://firebase.google.com/docs/admin/setup), [Storage administrativo](https://firebase.google.com/docs/storage/admin/start), [mudanças de requisitos do Storage](https://firebase.google.com/docs/storage/faqs-storage-changes-announced-sept-2024).
