import os
import redis
from flask import Flask, request, jsonify
from flasgger import Swagger

app = Flask(__name__)
swagger = Swagger(app, template={'info': {'title': 'Log Service API', 'version': '1.0.0'}})

REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
STREAM_NAME = 'audit_logs'

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

@app.route('/api/log', methods=['POST'])
def add_log():
    """
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
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    usuario_id = data.get('usuario_id', 'anonimo')
    acao = data.get('acao')
    ip_origem = data.get('ip_origem', '0.0.0.0')
    
    if not acao:
        return jsonify({'error': 'acao is required'}), 400

    log_entry = {
        'usuario_id': str(usuario_id),
        'acao': acao,
        'ip_origem': ip_origem
    }
    
    try:
        # XADD to redis stream
        msg_id = r.xadd(STREAM_NAME, log_entry)
        return jsonify({'success': True, 'msg_id': msg_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """
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
    """
    limit = int(request.args.get('limit', 100))
    try:
        # XREVRANGE to get logs in descending order (newest first)
        events = r.xrevrange(STREAM_NAME, max='+', min='-', count=limit)
        
        parsed_logs = []
        for msg_id, log_data in events:
            timestamp_ms = int(msg_id.split('-')[0])
            parsed_logs.append({
                'id': msg_id,
                'timestamp_ms': timestamp_ms,
                'usuario_id': log_data.get('usuario_id'),
                'acao': log_data.get('acao'),
                'ip_origem': log_data.get('ip_origem')
            })
            
        return jsonify({'success': True, 'logs': parsed_logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
