import re

with open('auth_service/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Adiciona o import e inicializa o Swagger
content = content.replace("from flask import Flask, request, jsonify", "from flask import Flask, request, jsonify\nfrom flasgger import Swagger")
content = content.replace("app = Flask(__name__)", "app = Flask(__name__)\nswagger = Swagger(app, template={'info': {'title': 'Auth Service API', 'version': '1.0.0'}})")

# Docs
docs = {
    "def register():": """def register():
    \"\"\"
    Registra um novo usuário no sistema
    ---
    tags:
      - Autenticação
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            nome:
              type: string
            email:
              type: string
            senha:
              type: string
            role:
              type: string
    responses:
      201:
        description: Usuário registrado com sucesso
      400:
        description: Erro de validação ou email já existente
      500:
        description: Erro interno
    \"\"\"""",
    
    "def login():": """def login():
    \"\"\"
    Autentica um usuário e retorna seus dados
    ---
    tags:
      - Autenticação
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            email:
              type: string
            senha:
              type: string
    responses:
      200:
        description: Login realizado com sucesso
      400:
        description: Dados insuficientes
      401:
        description: Credenciais inválidas
    \"\"\"""",

    "def forgot_password():": """def forgot_password():
    \"\"\"
    Solicita recuperação de senha e envia e-mail com token
    ---
    tags:
      - Recuperação
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            email:
              type: string
    responses:
      200:
        description: E-mail de recuperação enviado (ou falso positivo se não existir)
      400:
        description: E-mail não fornecido
    \"\"\"""",

    "def verify_token():": """def verify_token():
    \"\"\"
    Verifica a validade de um token de redefinição de senha
    ---
    tags:
      - Recuperação
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            token:
              type: string
    responses:
      200:
        description: Token válido
      400:
        description: Token não fornecido
      404:
        description: Token inválido, expirado ou já utilizado
    \"\"\"""",

    "def reset_password():": """def reset_password():
    \"\"\"
    Redefine a senha de um usuário utilizando um token válido
    ---
    tags:
      - Recuperação
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            token:
              type: string
            nova_senha:
              type: string
    responses:
      200:
        description: Senha redefinida com sucesso
      400:
        description: Dados incompletos
      404:
        description: Token inválido ou expirado
    \"\"\"""",

    "def check_role(user_id):": """def check_role(user_id):
    \"\"\"
    Consulta o papel (role) de um usuário específico
    ---
    tags:
      - Autorização
    parameters:
      - in: path
        name: user_id
        type: integer
        required: true
        description: ID do usuário
    responses:
      200:
        description: Role retornado com sucesso
      404:
        description: Usuário não encontrado
    \"\"\""""
}

for key, value in docs.items():
    content = content.replace(key, value)

with open('auth_service/app.py', 'w', encoding='utf-8') as f:
    f.write(content)
