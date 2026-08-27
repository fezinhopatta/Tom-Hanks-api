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
CREATE TABLE IF NOT EXISTS reset_tokens (
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
