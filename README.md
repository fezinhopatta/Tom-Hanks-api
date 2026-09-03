# Catálogo de Filmes - Tom Hanks (Atividade 3: Microsserviço de Autenticação Desacoplado)

Aplicação que consome a API do TMDB, exibe a filmografia do Tom Hanks, gerencia favoritos/comentários e possui um microsserviço de autenticação desacoplado.

**Professor responsável:** [@siriani](https://github.com/siriani)

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

# Mailtrap Credentials (Sandbox)
MAIL_SERVER=sandbox.smtp.mailtrap.io
MAIL_PORT=2525
MAIL_USERNAME=seu_mailtrap_username
MAIL_PASSWORD=seu_mailtrap_password
MAIL_FROM=no-reply@tomhanks.local
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
