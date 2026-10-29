# SW Cursos

**Firebase na Vercel:** o sistema também suporta Cloud Firestore e Firebase Storage, sem PostgreSQL/S3. Consulte [docs/FIREBASE.md](docs/FIREBASE.md) para configurar o projeto existente e publicar. O código precisa ser atualizado no GitHub e as variáveis privadas configuradas na Vercel antes do redeploy.

**Publicação na Vercel:** veja o passo a passo em [docs/VERCEL.md](docs/VERCEL.md). O projeto agora suporta PostgreSQL e armazenamento S3 privado, mantendo SQLite/arquivos locais para desenvolvimento. Na Vercel, uploads têm limite de 4 MB; localmente, 10 MB.

Aplicação web proprietária da **Pacovan Desenvolvimento**, com direito de uso pela **SW Cursos**. Nenhuma licença de código aberto é concedida ao código deste projeto. As licenças de terceiros permanecem aplicáveis às respectivas dependências.

## Escolha técnica

A pasta original continha somente `.git`, sem aplicação, instruções ou banco prévio. Foi escolhida uma aplicação Flask com páginas HTML renderizadas no servidor, CSS e JavaScript nativos, SQLite e Waitress. Essa stack reduz dependências, permite controle de autorização no servidor e funciona no Windows sem serviço de banco separado. SQLite atende uma instalação pequena em um único servidor; múltiplas instâncias e grande concorrência exigem migração para PostgreSQL e armazenamento compartilhado de arquivos.

Requer Python 3.12 ou posterior. Não há API paga, IA, CDN, fontes externas ou serviço de e-mail necessário para iniciar.

## Instalação (PowerShell, na pasta do projeto)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Substitua o valor `SECRET_KEY` de `.env` pela chave gerada. Nunca compartilhe ou versione essa chave. O exemplo é apenas um marcador, não use seu texto como chave. Na entrega local, `.venv`, `.env` com chave aleatória e banco demonstrativo já foram preparados; nenhum administrador foi criado.

`DATABASE` aceita caminho para o arquivo SQLite; o padrão é `instance/sw.sqlite3`. `COOKIE_SECURE=0` serve somente para HTTP local; use `1` com HTTPS em produção. O leitor de `.env` aceita linhas simples `NOME=valor` sem aspas, expansão ou comentários ao final. Variáveis do ambiente têm prioridade.

## Migração e demonstração

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app init-db
.\.venv\Scripts\python.exe -m flask --app app:create_app seed-demo
```

A migração `migrations/001_initial.sql` cria as tabelas e registra a versão. Ambos os comandos podem ser repetidos sem duplicar o esquema ou os cursos de demonstração. O seed é opcional: cria três cursos sinalizados como demonstração, sem usuários, contatos ou matrículas falsos. Para operar, edite ou desative esses cursos e substitua os textos provisórios.

## Primeiro administrador e senhas

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app create-admin
```

Informe nome, e-mail e senha no terminal. A senha fica oculta e deve ter de 12 a 128 caracteres. Não existe senha padrão nem rota pública para criar administradores. A criação requer acesso ao servidor. O administrador cadastra alunos em `/admin`; combine um canal seguro para entregar a senha inicial e solicite que o aluno a altere em Meus dados.

Sem serviço de envio, a recuperação é feita por um operador autorizado no servidor, depois de verificar a identidade do solicitante:

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app reset-password
```

Nenhum envio de e-mail é simulado. Mudanças de senha invalidam sessões anteriores no próximo acesso. Desativar um usuário bloqueia a próxima requisição; remover uma matrícula ou desativar um curso bloqueia seus materiais imediatamente nas novas requisições. Arquivos já baixados pelo usuário não podem ser revogados.

## Executar e acessar

```powershell
.\.venv\Scripts\python.exe run.py
```

Abra [a aplicação local](http://127.0.0.1:5000). Rotas: `/` início, `/cursos` catálogo, `/interesse` captação, `/login` acesso, `/admin` gestão e `/aluno` cursos liberados. O servidor escuta somente a interface local. Para desenvolvimento com recarga, use `python -m flask --app app:create_app run --debug` apenas na sua máquina.

## Funcionalidades entregues

- Site e landing page responsivos em português, catálogo, detalhes, busca, capas gráficas provisórias e sinalização de demonstração.
- Interessados persistidos com data e cópia do aviso aceito; consulta e status novo, em atendimento ou concluído.
- Login/logout, hashes scrypt, perfis e autorização no servidor; proteção individual de materiais por matrícula ativa.
- Gestão de cursos e alunos com edição/ativação/desativação; vínculos e remoção de matrículas; materiais organizados por curso, criação, edição e exclusão; busca nas listas e confirmações de remoção.
- PDF, PNG, JPEG até 10 MB por requisição, links HTTPS/vídeo e orientações em texto. Downloads passam por autorização; arquivos ficam fora de `static`. Arquivos são entregues como anexo, com tipo validado por extensão e assinatura básica, nomes aleatórios no disco e `nosniff`.
- Nome, chamada, apresentação, benefícios, contato e aviso editáveis. O painel oferece três paletas de identidade visual. Cores e tipografia são variáveis no início de `static/style.css`; as capas são ilustrações locais, sem alegações sobre cursos reais.
- Área do aluno com cursos próprios, materiais e alteração de nome, e-mail e senha.
- Manifest com ícones, service worker e página de orientação offline; estados vazios, erros e avisos.
- Registro das ações administrativas, sem senhas nem conteúdo dos formulários.

## Segurança e privacidade

Consultas SQL parametrizadas, validação no servidor, escape automático de conteúdo, política CSP sem scripts inline, CSRF em todas as alterações, cookie HttpOnly/SameSite=Lax e validade de oito horas. Limite persistido de dez tentativas em 15 minutos por IP e por e-mail no login, e dez envios por IP no formulário. Não confie em cabeçalhos de proxy fornecidos pelo cliente; se configurar proxy, limite quem pode acessar o servidor e configure endereços confiáveis antes de alterar essa lógica.

Sessões são assinadas, não criptografadas: guardam apenas identificador, prova de versão da senha e token CSRF, sem os dados pessoais dos formulários. Respostas usam `Cache-Control: no-store`; arquivos privados nunca entram no service worker. Não inclua scripts de terceiros sem reavaliar a segurança. Uploads têm validação básica; análise antivírus/sanitização aprofundada não está integrada. Restrinja uploads a administradores confiáveis e avalie um scanner antes de ampliar a operação.

O aviso é um **modelo para revisão**. SW Cursos/Pacovan devem definir responsabilidades, bases legais, canal de direitos, retenção, descarte, backups e regras de acesso antes de captar dados reais. Não há promessa de conformidade automática com LGPD. Exclusão/exportação de dados pessoais exige procedimento supervisionado no banco nesta versão; não existe rotina automática de retenção. Proteja banco, backups, `.env` e uploads por permissões do sistema operacional e criptografia do disco.

## Online e offline

O aplicativo pode ser instalado em navegadores compatíveis sobre HTTPS ou localhost. O primeiro carregamento precisa de conexão. O cache guarda somente uma lista explícita de recursos públicos: estilos, ícones, JavaScript, manifest e uma página estática de orientação. Ao navegar sem conexão, essa página informa a limitação e permite tentar novamente.

**Não são armazenados offline**: páginas dinâmicas de cursos, sessão HTML, dados de alunos, contatos, painel, formulários ou materiais restritos. Login, cadastros, downloads e alterações precisam de internet. Não há fila nem sincronização automática. Nenhum material está autorizado para cache offline nesta versão: isso evita persistir conteúdo privado sem um mecanismo adequado de proteção e revogação. Downloads manuais permanecem no dispositivo sob responsabilidade do usuário. Catálogo offline completo e materiais offline ficam como expansão que exige uma política explícita do negócio e desenho de segurança próprio.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Teste adicional do service worker (Node.js 18+): `node tests/test_sw.mjs`. Verifica instalação, limpeza de versões antigas, fallback offline e ausência de cache privado em ambiente simulado.

A suíte usa bancos e uploads temporários isolados. Cobre páginas, envio de contato, privacidade, login/logout, limite de tentativas, papéis, curso/aluno/material/matrícula, acesso indevido, desativação, atualização de senha, arquivos privados, URLs perigosas, XSS, SQL, auditoria, idempotência e política de cache. Nenhum dado de teste é inserido no banco operacional.

Verificação manual no navegador: abra início, catálogo e formulário em 1440 e 390 px; percorra com Tab; crie administrador pelo terminal; cadastre aluno/curso/material; vincule o aluno e confira acesso; remova o vínculo e confirme bloqueio. Em Ferramentas de desenvolvedor > Application, confira service worker/manifest; em Network, habilite Offline e recarregue para conferir a página de orientação; confira Cache Storage (somente recursos públicos). Volte a Online e confira navegação. A instalação efetiva depende do navegador/dispositivo e deve ser validada no ambiente final.

## Produção (não publicada)

1. Revisar dados institucionais, catálogo, marca, política de privacidade e retenção; criar administrador real e remover demonstrações.
2. Escolher hospedagem Python persistente, domínio, certificado HTTPS e proxy reverso. Não use hospedagem de arquivos estáticos para esta aplicação.
3. Instalar dependências travadas, aplicar migração, configurar chave secreta aleatória e `COOKIE_SECURE=1`. Guardar banco e uploads em volume persistente com acesso restrito. Não usar debug.
4. Executar Waitress como serviço supervisionado (o `run.py` escuta `127.0.0.1:5000`), encaminhar tráfego pelo proxy HTTPS, limitar corpo a 10 MB e configurar timeouts. Não servir a pasta do projeto ou `instance` pelo proxy.
5. Configurar backups, monitoramento e política de logs; testar restauração, perfis, certificados, downloads, mobile e instalação PWA. Executar verificação atualizada de vulnerabilidades das dependências antes da publicação.

Hospedagem, domínio, armazenamento, backups e possíveis serviços de e-mail podem ter custos conforme o fornecedor. Integrações de e-mail/WhatsApp não foram configuradas; exigem contratação/configuração e autorização. Não há cobrança, certificados de conclusão ou gestão financeira, pois não foram solicitados. A aplicação não foi publicada.

## Backup e restauração

Para uma cópia consistente que inclua arquivos: pare o serviço, copie toda a pasta `instance` (banco e uploads) e guarde `.env` separadamente em armazenamento seguro. Exemplo, com destino previamente escolhido e acesso restrito:

```powershell
Copy-Item -LiteralPath .\instance -Destination D:\BackupSW\2026-10-27 -Recurse
```

Não use um backup público nem o Git. Defina frequência, criptografia e retenção com o responsável. Para restaurar, pare o serviço, preserve a instalação atual em outra pasta, copie o backup para uma nova instalação compatível, configure `.env`, instale o lock, execute `init-db`, confirme arquivos/perfis e inicie. Rotacione a chave de sessão se houver suspeita de exposição. Faça um teste de restauração regularmente. Para banco personalizado em `DATABASE`, inclua esse caminho no backup além de `instance/uploads`.

## Estrutura e dependências

`app.py`: aplicação e comandos; `run.py`: servidor local; `migrations/`: esquema versionado; `templates/`: páginas; `static/`: estilos, identidade e PWA; `tests/`: fluxos automatizados; `instance/`: dados locais ignorados; `.env.example`: configuração sem segredos; `requirements.lock.txt`: versões instaladas; `THIRD_PARTY_NOTICES.txt`: licenças de dependências.

Dependências diretas: Flask (BSD-3-Clause), Waitress (ZPL-2.1). Transitivas: Werkzeug, Jinja2, MarkupSafe, ItsDangerous, Click (BSD-3-Clause) e Blinker (MIT). Os textos de licença são preservados no arquivo de avisos e nos pacotes instalados. Python e SQLite conservam suas próprias licenças. Os ícones e ilustrações do projeto foram criados localmente; Pillow foi usado somente como ferramenta de geração dos ícones, não é dependência da aplicação.

## Verificação desta entrega

14 testes automatizados de integração passaram. O teste isolado do service worker passou. Início e formulário foram inspecionados no navegador a 390 px, sem rolagem horizontal, e a página inicial foi inspecionada em tela de computador. O fallback offline foi confirmado no navegador após interromper o servidor local. A instalação pelo sistema operacional, HTTPS público, envio externo e dispositivos físicos permanecem para validação no ambiente final.

## Identidade visual da escola

Logo fornecida pelo cliente em `static/logo-sw.png`, preservada sem redesenho. Paleta visual baseada no azul-marinho, vermelho e branco dessa imagem. O tema padrão é SW Cursos; a tipografia continua de sistema. O arquivo recebido tem resolução pequena (178 × 124), sendo recomendável substituí-lo pelo original de alta resolução quando disponível.

Logo atualizada: `static/logo-sw-transparente.png`, baseada na nova imagem enviada pelo cliente, com fundo transparente e letras brancas opacas. A versão anterior permanece preservada em `static/logo-sw.png`.

## Fotos, anúncios e gestão de cursos

Execute `python -m flask --app app:create_app init-db` para aplicar também a migração 2 em instalações existentes, sem apagar cadastros. Faça um backup antes de atualizar uma instalação em produção.

O painel `/admin` tem as seções **Fotos dos cursos** e **Anúncios**. Somente administradores podem cadastrar/editar/excluir cursos, fotos ou anúncios; a proteção é feita no servidor, inclusive para requisições diretas. Na seção Cursos, o botão **Excluir curso** retira o curso do catálogo e da área do aluno. É uma exclusão lógica: o histórico de matrículas e interessados é preservado. Cursos excluídos não podem ser reativados pela edição normal.

Em Fotos, escolha o curso, envie PNG/JPEG, informe legenda e ordem (0 a 999). A primeira foto pela ordem é usada como capa; as demais compõem a galeria na página pública do curso. É possível alterar legenda/ordem, substituir a imagem e excluir. Fotos de cursos inativos só são visualizadas pelo administrador; fotos de cursos excluídos ficam indisponíveis.

Em Anúncios, envie uma arte, título, descrição opcional, destino do botão, ordem e estado ativo. Edite ou exclua quando desejar. O destino aceita caminhos internos ou HTTPS. As artes aparecem inteiras, sem corte. Sem anúncios ativos, o carrossel mostra três chamadas institucionais. A rotação começa automaticamente e troca a imagem a cada cinco segundos, com botões anterior/próximo e pausa. Passar o mouse ou focar os controles não interrompe a rotação; somente o botão de pausa ou a aba oculta interrompem o avanço.

Fotos e anúncios são recursos de divulgação **públicos**; use imagens com autorização de publicação. São armazenados em `instance/uploads`, junto dos arquivos privados, mas atendidos por rotas distintas que verificam a visibilidade de cada registro. Não são colocados em cache offline. O upload tem limite de 10 MB por requisição e 20 milhões de pixels. Pillow 12.3.0 decodifica e regrava PNG/JPEG como JPEG (até 2400 px), removendo metadados e conteúdo extra. Esta biblioteca agora é uma dependência da aplicação; sua licença e licenças incluídas estão em `THIRD_PARTY_NOTICES.txt`.

O cabeçalho usa uma faixa azul-marinho com navegação branca e detalhe vermelho, mantendo a identidade da escola. Novos anúncios e fotos exigem conexão, assim como as demais alterações administrativas.

## Página inicial — apresentação atualizada

A página inicial reúne apresentação e anúncios no topo, acessos rápidos, busca de cursos, catálogo, apresentação da escola e contato. Mantém a identidade azul/vermelho/branco e o carrossel automático de cinco segundos. Textos institucionais e anúncios continuam editáveis no painel. A revisão visual foi conferida em computador e a 390 px, sem rolagem horizontal, com acesso direto ao catálogo.

## Adaptação para Vercel

`wsgi.py`, `pyproject.toml` e `vercel.json` configuram o ponto de entrada e build. `database.py` oferece PostgreSQL e SQLite; `storage.py` oferece arquivos locais ou bucket privado S3. Migrações PostgreSQL estão em `migrations/postgres`. `cloud_import.py` e o comando `import-local` transferem dados existentes sem apagar a origem. Os serviços externos precisam ser contratados/configurados pelo responsável antes de publicar. Consulte `docs/VERCEL.md` para variáveis, importação, limites, backups e validação final.
