import os
import redis
from flask import Flask, request, jsonify

app = Flask(__name__)

REDIS_HOST = os.getenv('REDIS_HOST', 'redis')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
STREAM_NAME = 'audit_logs'

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

@app.route('/api/log', methods=['POST'])
def add_log():
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
