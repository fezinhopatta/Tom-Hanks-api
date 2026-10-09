# Catálogo de Filmes - Tom Hanks (Atividade 5: Log de Auditoria com Redis)

Aplicação que consome a API do TMDB, exibe a filmografia do Tom Hanks, gerencia favoritos/comentários e possui um microsserviço de autenticação desacoplado.

**Professor responsável:** [@siriani](https://github.com/siriani)

**Arquivo relatorio para P1**[Clique aqui para acessar](./P1_ISW055_Victor_Siveri.pdf)

---

## 🚀 O que mudou nesta Atividade (Atividade 3)

Na **Atividade 2**, o sistema rodava como um monólito em um único container (catálogo, login, cadastro, papéis de usuário, comentários e favoritos no mesmo processo).

Na **Atividade 3**, a lógica de autenticação foi **extraída para um microsserviço desacoplado** (`auth-service`), rodando em seu próprio container e comunicando-se com o container de catálogo (`catalog`) apenas através da **rede interna do Docker**.

### 🛠️ Decisões de Arquitetura e Benefícios
- **Isolamento de Responsabilidade:** Alterações no fluxo de autenticação ou envio de e-mails não exigem o redeploy do catálogo.
- **Segurança da Rede Docker:** O container `auth-service` não publica portas para a máquina hospedeira (`host`). O catálogo é o **único ponto de entrada público**.
- **Papéis de Usuário (Roles):** Cada usuário possui um papel definido (`usuario` ou `admin`) armazenado e validado pelo microsserviço.
- **Recuperação de Senha com Expiração Real:** Tabela `reset_tokens` com tokens UUID únicos de uso único e expiração de 30 minutos.
- **Envio Real de E-mail via Mailtrap:** Integração SMTP para envio transacional de e-mails em ambiente de desenvolvimento.

---

## 📐 Arquitetura de Rede

```
                   ┌────────────────────────────────────────────────────────┐
                   │                  REDE DOCKER INTERNA                   │
                   │                      (app-network)                     │
 Navegador  ───►   │  ┌──────────────────┐            ┌──────────────────┐  │
  Usuário    PORTA │  │  catalog-service │   HTTP     │   auth-service   │  │
 (Internet)  5000  │  │  (Ponto Público) ├───────────►│ (Sem Porta Host) │  │
                   │  └────────┬─────────┘            └────────┬─────────┘  │
                   │           │                               │            │
                   │           ▼                               │            │
                   │  ┌──────────────────┐                     │            │
                   │  │   log-service    │◄────────────────────┘            │
                   │  │ (Sem Porta Host) │                                  │
                   │  └────────┬─────────┘                                  │
                   │           │                                            │
                   │           ▼                                            │
                   │  ┌──────────────────┐                                  │
                   │  │  redis-service   │                                  │
                   │  └──────────────────┘                                  │
                   └───────────┼───────────────────────────────┼────────────┘
                               │                               │
                               ▼                               ▼
                      ┌──────────────────┐           ┌──────────────────┐
                      │ External MariaDB │           │  Mailtrap SMTP   │
                      │ (Favoritos/Com.) │           │ (Envio de Email) │
                      └──────────────────┘           └──────────────────┘
```

---

## 📄 Estrutura do `docker-compose.yml`

```yaml
version: '3.8'

services:
  catalog:
    build: .
    container_name: catalog-service
    ports:
      - "${PORTA_ALUNO:-5000}:5000"
    environment:
      - TMDB_API_KEY=${TMDB_API_KEY}
      - DB_HOST=${DB_HOST}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
      - DB_NAME=${DB_NAME}
      - SECRET_KEY=${SECRET_KEY}
      - AUTH_SERVICE_URL=http://auth-service:5000
    networks:
      - app-network
    depends_on:
      - auth-service

  auth-service:
    build: ./auth_service
    container_name: auth-service
    # Sem publicação de portas para o host (acessível apenas via rede interna)
    environment:
      - DB_HOST=${DB_HOST}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
      - DB_NAME=${DB_NAME}
      - SECRET_KEY=${SECRET_KEY}
      - MAIL_SERVER=${MAIL_SERVER:-sandbox.smtp.mailtrap.io}
      - MAIL_PORT=${MAIL_PORT:-2525}
      - MAIL_USERNAME=${MAIL_USERNAME}
      - MAIL_PASSWORD=${MAIL_PASSWORD}
      - MAIL_FROM=${MAIL_FROM:-no-reply@tomhanks.local}
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
```

> **Confirmação de Segurança:** O serviço `auth-service` não possui a diretiva `ports:`, garantindo que não possa ser acessado diretamente pela internet ou pela máquina hospedeira.

---

## 🗄️ Esquema da Tabela `reset_tokens`

A recuperação de senha foi implementada com persistência dos tokens no MariaDB:

```sql
CREATE TABLE reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    token VARCHAR(255) NOT NULL UNIQUE,
    usuario_id INT NOT NULL,
    criado_em DATETIME NOT NULL,
    expira_em DATETIME NOT NULL,
    usado BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
```

---

## 🛡️ Atividade 4: RBAC (Role-Based Access Control)

### 1. Permissões documentadas por papel

No sistema atual, temos as seguintes permissões por papel:

* **Papel `usuario`:**
  * Pode logar no sistema.
  * Pode pesquisar filmes do catálogo.
  * Pode favoritar filmes.
  * Pode adicionar comentários em filmes.
  * **Pode apagar apenas os seus próprios comentários.**

* **Papel `admin`:**
  * Possui todas as permissões do papel `usuario`.
  * **Pode apagar o comentário de qualquer pessoa (ação exclusiva de moderação).**

### 2. Ação exclusiva de admin e Enforcement no backend

A ação exclusiva implementada é a **exclusão de comentários de outros usuários**.
O enforcement é feito no `catalog-service` que consulta o `auth-service` para verificar o papel real do usuário atual no banco de dados.
Se um usuário comum tentar chamar o endpoint de exclusão de um comentário que não lhe pertence (por exemplo, diretamente via cURL ou Postman), o backend recusará a ação retornando um HTTP status `403 Forbidden`.

### 5. Resposta curta: Padrão A ou B?

**O auth-service usa hoje o Padrão A (enforcement centralizado).**
Toda vez que a ação sensível (apagar comentário) é chamada, o catálogo faz uma requisição via rede para o `auth-service` (`/api/check-role`) para confirmar o papel do usuário.
Se fossemos para o **Padrão B (claims no JWT)**, o catálogo não precisaria fazer essa chamada de rede extra. O próprio token JWT recebido no login já conteria a informação `role: "admin"`. O catálogo apenas decodificaria o JWT localmente e autorizaria a exclusão, tornando a requisição mais rápida, porém com a desvantagem de que uma mudança de papel demoraria a ter efeito (apenas quando o token expirasse).

---

## 📜 Atividade 5: Log de Auditoria com Redis

Foi criado um microsserviço independente (`log-service`) apoiado por um banco de dados em memória e de alta performance (`redis`) para servir como log de auditoria.

*   **Responsabilidade Separada:** Em vez de poluir o banco MariaDB, as transações de auditoria ficam em uma infra de logs apropriada.
*   **Redis Streams (`XADD` e `XREVRANGE`):** Utilizados para guardar os eventos (`login`, `logout`, `favoritar`, `comentar`, `moderação` e erros de segurança HTTP `403`), mantendo carimbos de tempo precisos nativamente e permitindo fácil recuperação cronológica.
*   **Consulta Exclusiva para Admins:** Há um endpoint no catálogo (`/admin/logs`) que obtém os logs consolidados do `log-service` de forma protegida, assim como na Atividade 4.

---

## 🏃 Como rodar o projeto localmente (via Docker Compose)

1. Crie um arquivo `.env` na raiz do projeto, baseado no `.env.example`:
   ```bash
   cp .env.example .env
   ```
2. Edite o `.env` e coloque sua `TMDB_API_KEY` e credenciais do Mailtrap/MariaDB.
3. Suba os containers:
   ```bash
   docker compose up --build
   ```
4. Acesse em seu navegador: [http://localhost:5000](http://localhost:5000)

> **Dica para testar o RBAC:** Crie dois usuários. Vá no banco de dados e mude o campo `role` de um deles para `admin`. O admin verá o botão "Apagar" em todos os comentários. O usuário comum verá o botão "Apagar" apenas nos seus. Tente fazer um POST para a rota `/apagar_comentario/<id>` com a sessão do usuário comum no comentário de outra pessoa, e você receberá o erro `403`.

---

## 🧪 Como Executar e Testar

### 1. Configurar o arquivo `.env`
Crie um arquivo `.env` baseado no `.env.example`:
```env
TMDB_API_KEY=sua_chave_tmdb
DB_HOST=35.226.64.52
DB_USER=seu_usuario
DB_PASSWORD=sua_senha
DB_NAME=seu_banco
SECRET_KEY=sua_chave_secreta
PORTA_ALUNO=5000
APP_URL=http://localhost:5000

# Mailtrap Credentials (Sandbox) / Brevo
MAIL_SERVER=smtp-relay.brevo.com
MAIL_PORT=587
MAIL_USERNAME=seu_usuario
MAIL_PASSWORD=sua_senha
MAIL_FROM=seu_email_validado@dominio.com
```

### 2. Iniciar os Containers
```bash
docker-compose up --build
```

### 3. Demonstrar o Fluxo de "Esqueci minha senha"

1. **Solicitação:** Acesse `http://localhost:5000/login`, clique em **Esqueci minha senha**, digite seu e-mail e envie.
2. **E-mail recebido (Mailtrap):** Acesse a caixa de entrada da Sandbox no Mailtrap. O e-mail conterá o link no formato:
   `http://localhost:5000/reset-password/<token_uuid>`
3. **Uso do Link:** Clique no link do e-mail (ou abra no navegador). Digite a nova senha e confirme.
4. **Login com nova senha:** Faça login utilizando o e-mail e a nova senha recém-definida.
5. **Tentativa de Reuso de Token (Recusada):** Tente acessar o mesmo link novamente. O sistema recusará com a mensagem: `"Este link de redefinição já foi utilizado."`
6. **Tentativa com Token Expirado (Recusada):** Se o token tiver mais de 30 minutos da sua criação (`expira_em < agora`), a troca é recusada com a mensagem: `"Este link de redefinição expirou (válido por 30 minutos)."`
---
## 📘 Atividade Extra: Swagger/OpenAPI
As APIs dos microsserviços **auth-service** e **log-service** foram documentadas com **Flasgger**.
Para visualizar a documentação interativa e testar os endpoints (Try it out):
1. Suba os containers com \docker-compose up --build\.
2. Acesse o Swagger UI do Auth Service em: [http://localhost:5001/apidocs/](http://localhost:5001/apidocs/)
3. Acesse o Swagger UI do Log Service em: [http://localhost:5002/apidocs/](http://localhost:5002/apidocs/)
*(As portas 5001 e 5002 foram abertas temporariamente no \docker-compose.yml\ para permitir o acesso do host ao Swagger)*
O arquivo \openapi.json\ pode ser obtido ao adicionar \pispec_1.json\ na URL respectiva.

---
## 📘 Atividade Extra: Swagger/OpenAPI
As APIs dos microsserviços **auth-service** e **log-service** foram documentadas com **Flasgger**.
Para visualizar a documentação interativa e testar os endpoints (Try it out):
1. Suba os containers com `docker-compose up --build`.
2. Acesse o Swagger UI do Auth Service em: [http://localhost:5001/apidocs/](http://localhost:5001/apidocs/)
3. Acesse o Swagger UI do Log Service em: [http://localhost:5002/apidocs/](http://localhost:5002/apidocs/)
*(As portas 5001 e 5002 foram abertas temporariamente no `docker-compose.yml` para permitir o acesso do host ao Swagger)*
O arquivo `openapi.json` pode ser obtido ao acessar `http://localhost:5001/apispec_1.json` ou `http://localhost:5002/apispec_1.json`.


---

## 🖼️ Atividade 6: Upload e Perfil de Usuário com MinIO

O Catálogo agora conta com uma funcionalidade de rede social: cada usuário tem o seu **Perfil**. O perfil exibe a biografia, os filmes favoritados e uma **foto de perfil** (avatar).

### 🏗️ Arquitetura de Upload e Decisão Técnica

Em vez de armazenar o arquivo binário (BLOB) da imagem dentro do MariaDB — o que tornaria o banco lento e pesado —, a imagem vai para um **Object Storage (MinIO)** dedicado na rede Docker, e o banco guarda apenas a URL (referência) da imagem (`avatar_url`).

### ⚖️ Trade-off Documentado: Bucket Público vs. URL Pré-assinada

Para exibir as imagens de perfil, decidi utilizar **Bucket com Leitura Pública** em vez de gerar URLs pré-assinadas (Presigned URLs).
**Justificativa:** Em um contexto de rede social ou sistema de catálogos abertos, a foto de perfil geralmente não é um dado sigiloso restrito apenas a sessões ativas (como seria um documento pessoal ou extrato bancário). Um bucket público permite que a imagem seja cacheada por CDNs e navegadores, reduzindo a carga computacional no microsserviço (que não precisa re-assinar a URL a cada requisição ou gerenciar tempo de expiração) e garantindo maior performance na renderização de milhares de perfis.

### 🛡️ Controle de Acesso (RBAC)

A rota `/perfil/<id>` suporta validação de identidade: **somente o próprio usuário (dono do perfil)** pode submeter um novo avatar ou atualizar sua biografia. Qualquer requisição com ID diferente do usuário logado é imediatamente recusada com `403 Forbidden`.

---

## 💳 Atividade 7: Plano Premium — Cobrança de Verdade com Stripe (Modo de Teste)

O catálogo ganha um modelo de negócio sustentável: um **Plano Premium pago** cobrado de forma real em **modo de teste** através de um provedor de pagamentos global (**Stripe**).

### 💡 Por que Pagamento é um Serviço à Parte?
Armazenar dados de cartão de crédito no próprio banco de dados exige um nível extremo de segurança e conformidade legal e regulatória (**PCI-DSS - Payment Card Industry Data Security Standard**). Para evitar responsabilidades de risco cibernético, vazamento de dados bancários e auditorias complexas, a solução do mercado moderno é:
1. **Delegar a interface de pagamento:** O próprio Stripe hospeda a tela segura de checkout onde o cartão é inserido. Nosso backend nunca tem contato com número de cartão, validade ou código de segurança (CVV).
2. **Comunicação Assíncrona via Webhooks:** Em vez de confiar em um retorno imediato do navegador (que pode ser fechado, desconectado ou manipulado), a confirmação do pagamento chega através de um **Webhook assinado** enviado diretamente dos servidores do Stripe para o nosso backend.

```
   ┌──────────┐                     ┌───────────────┐                  ┌──────────────┐
   │ Usuário  │ ── 1. Clica Assinar ──►│ Catalog App   │ ── 2. Cria Sessão──►│ Stripe API   │
   │ (Cliente)│                     │ (Backend)     │                  │              │
   └────┬─────┘                     └───────┬───────┘                  └──────┬───────┘
        │                                   │                                 │
        │◄── 3. Redireciona (HTTP 303) ─────┘                                 │
        │                                                                     │
        │────────────────────── 4. Digita Cartão na Página Hospedada ────────►│
        │                                                                     │
        │                                   ┌───────────────┐                 │
        │                                   │  MariaDB / DB │                 │
        │                                   └───────▲───────┘                 │
        │                                           │ (Atualiza is_premium=1) │
        │                                   ┌───────┴───────┐                 │
        │                                   │ Catalog App   │◄── 5. Webhook ──┘
        │                                   │ (/webhook/stripe) (Assíncrono)
        │◄── 6. Redireciona Sucesso ────────┴───────────────┘
```

---

### ⚙️ O que foi Implementado

#### 1. Plano no Stripe e Configuração em Modo de Teste
- Suporte a `STRIPE_PRICE_ID` configurado no painel do Stripe (ex: produto *"Plano Premium — R$ 9,90/mês"*).
- Fallback automático inteligente: caso `STRIPE_PRICE_ID` não seja especificado no `.env`, o backend cria dinamicamente o item de assinatura recorrente mensal de R$ 9,90 via `price_data`, facilitando os testes imediatos.

#### 2. Endpoint de Checkout (`/checkout` e `/stripe/checkout`)
- Cria uma `stripe.checkout.Session` com `mode='subscription'`, `client_reference_id` com o ID do usuário logado e metadados.
- Redireciona com código HTTP `303 See Other` para a página hospedada pelo Stripe.
- Rotas de retorno tratadas: `/checkout/sucesso` e `/checkout/cancelado`.

#### 3. Endpoint de Webhook com Validação Criptográfica (`/webhook/stripe`)
- Recebe os eventos assíncronos do Stripe.
- **Validação de Assinatura:** O cabeçalho `Stripe-Signature` é rigorosamente verificado com `stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)`. Requisições forjadas ou sem assinatura válida são rejeitadas com `400 Bad Request`.
- **Processamento de Eventos:**
  - `checkout.session.completed`: Identifica o usuário e marca `is_premium = 1`, além de armazenar o `stripe_customer_id` e o `stripe_subscription_id`. Dispara log de auditoria.
  - `customer.subscription.deleted`: Em caso de cancelamento da assinatura no Stripe, rebaixa o usuário para `is_premium = 0` automaticamente.

#### 4. Benefício Real e Verificável do Plano Premium
Existe uma diferença de comportamento clara e comprovável entre usuário comum e usuário Premium:
- **Usuário Gratuito (Não-Premium):**
  - Limitado a **no máximo 5 filmes favoritos**.
  - Tentativas de favoritar o 6º filme são bloqueadas pelo backend, registrando log de auditoria `403_limite_favoritos_atingido` e exibindo mensagem flash com convite de upgrade.
  - Banner na tela inicial exibindo o consumo da cota (ex: *Favoritos: 3 de 5 disponíveis*).
- **Usuário Premium:**
  - **Favoritos Ilimitados:** pode favoritar quantos filmes desejar sem nenhum bloqueio.
  - **Selo VIP Dourado (`⭐ VIP PREMIUM` / `⭐ ASSINANTE PREMIUM`):** exibido com destaque na barra superior e no perfil social do usuário.
  - Informações de status ativo visíveis no perfil.
- **Gerenciamento:** Adicionada a funcionalidade `/desfavoritar` para permitir remover filmes e gerenciar a cota de favoritos.

#### 5. Conformidade PCI-DSS e Proteção de Dados
- **Nenhum dado de cartão de crédito** (número, CVV, data de expiração ou senha) trafega ou é gravado no banco de dados.
- O banco armazena unicamente identificadores de referência do próprio Stripe (`stripe_customer_id` e `stripe_subscription_id`).

---

### 🧪 Como Testar o Fluxo do Stripe

#### 1. Configurar as Chaves no `.env`
No seu `.env`, defina as credenciais de teste obtidas na sua conta do Stripe Dashboard (Test Mode):
```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_... # Opcional
```

#### 2. Cartões de Teste Oficiais do Stripe
Ao ser redirecionado para a tela de checkout do Stripe, utilize os cartões de simulação:
* **Número do Cartão:** `4242 4242 4242 4242`
* **Validade:** Qualquer data futura (ex: `12/30`)
* **CVC:** Qualquer 3 dígitos (ex: `123`)
* **Nome e CEP:** Qualquer informação fictícia

#### 3. Encaminhando Webhooks Localmente (Stripe CLI)
Para receber os webhooks do Stripe no ambiente de desenvolvimento local:
```bash
# Faça login no Stripe CLI
stripe login

# Encaminhe os eventos para o container do catálogo
stripe listen --forward-to localhost:5000/webhook/stripe
```
Copie o `webhook signing secret` gerado no terminal (começa com `whsec_...`) e cole na variável `STRIPE_WEBHOOK_SECRET` do seu `.env`.

#### 4. Executar os Testes Automatizados
O projeto conta com suíte de testes automatizados cobrindo todas as regras:
```bash
python test_stripe_integration.py
```
Testes inclusos:
- Verificação de registro de todas as rotas;
- Rejeição de assinaturas inválidas com HTTP 400;
- Aceitação e parsing seguro de eventos assinados;
- Bloqueio comprovado de limite de 5 favoritos para usuários comuns;
- Liberação irrestrita de favoritos para usuários Premium.

