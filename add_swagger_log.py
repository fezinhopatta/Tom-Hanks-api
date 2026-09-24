import re

with open('log_service/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Adiciona o import e inicializa o Swagger
content = content.replace("from flask import Flask, request, jsonify", "from flask import Flask, request, jsonify\nfrom flasgger import Swagger")
content = content.replace("app = Flask(__name__)", "app = Flask(__name__)\nswagger = Swagger(app, template={'info': {'title': 'Log Service API', 'version': '1.0.0'}})")

docs = {
    "def add_log():": """def add_log():
    \"\"\"
    Adiciona um novo log de auditoria
    ---
    tags:
      - Auditoria
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            usuario_id:
              type: string
            acao:
              type: string
            ip_origem:
              type: string
    responses:
      201:
        description: Log registrado com sucesso
      400:
        description: Erro de validação
      500:
        description: Erro interno
    \"\"\"""",

    "def get_logs():": """def get_logs():
    \"\"\"
    Recupera os últimos logs de auditoria
    ---
    tags:
      - Auditoria
    parameters:
      - in: query
        name: limit
        type: integer
        required: false
        description: Limite de logs a retornar (padrão 100)
    responses:
      200:
        description: Lista de logs retornada com sucesso
      500:
        description: Erro interno
    \"\"\""""
}

for key, value in docs.items():
    content = content.replace(key, value)

with open('log_service/app.py', 'w', encoding='utf-8') as f:
    f.write(content)
