from flask import Flask, request, jsonify
from raft import Node
from message_queue import MessageQueue
import sys
from helpers import parse_config_json
from raft import Role

app = Flask(__name__)

raft_node: Node = None
message_queue: MessageQueue = None


# node_id is the node that is sending vote request
@app.route("/request-vote/<node_id>", methods=["POST"])
def receive_vote_request(node_id):
    rpc_message_json = request.json
    res, status_code = raft_node.rpc_handler(node_id, rpc_message_json)
    return jsonify(res), status_code


@app.route("/vote-response/<node_id>", methods=["POST"])
def receive_vote_response(node_id):
    rpc_message_json = request.json
    raft_node.rpc_handler(node_id, rpc_message_json)
    return jsonify({"response": "handled"}), 200


# node_id is the node that is broadcasting the heartbeat
@app.route("/heart-beat/<node_id>", methods=["POST"])
def receive_heart_beat(node_id):
    rpc_message_json = request.json
    res, status_code = raft_node.rpc_handler(node_id, rpc_message_json)
    return jsonify(res), status_code


@app.route("/heart-beat-response/<node_id>", methods=["POST"])
def receive_heart_beat_response(node_id):
    rpc_message_json = request.json
    raft_node.rpc_handler(node_id, rpc_message_json)
    return jsonify({"response": "handled"}), 200


@app.route("/topic", methods=["PUT"])
def add_topic():
    content_type = request.headers.get('Content-Type')
    if content_type == 'application/json':
        json_body = request.json
        topic = json_body['topic']
        command = {'type': 'topic', 'method': 'PUT', 'topic': topic}
        print(f"Appending topic {topic} to message queue for node {raft_node.id}")
        # response = message_queue.process_command(command, raft_node.role)
        response = raft_node.client_command_handler(command)
        return jsonify(response), 200
    else:
        return jsonify({'Error': 400, 'Message': 'Content-Type not supported'}), 400


@app.route("/topic", methods=["GET"])
def get_topic():
    command = {'type': 'topic', 'method': 'GET'}
    # response = message_queue.process_command(command, raft_node.role)
    response = raft_node.client_command_handler(command)
    return jsonify(response), 200


@app.route("/message", methods=["PUT"])
def push_message():
    content_type = request.headers.get('Content-Type')
    if content_type == 'application/json':
        json_body = request.json
        topic = json_body['topic']
        message = json_body['message']
        command = {'type': 'message',
                   'method': 'PUT',
                   'topic': topic,
                   'message': message}
        print(f"Appending message {message} to message queue topic : {topic} for node {raft_node.id}")
        # response = message_queue.process_command(command, raft_node.role)
        response = raft_node.client_command_handler(command)
        return jsonify(response), 200
    else:
        return jsonify({'Error': 400, 'Message': 'Content-Type not supported'}), 400


@app.route("/message/<topic>", methods=["GET"])
def pop_message(topic):
    command = {'type': 'message',
               'method': 'GET',
               'topic': topic}
    # response = message_queue.process_command(command, raft_node.role)
    response = raft_node.client_command_handler(command)
    return jsonify(response), 200


@app.route("/status", methods=["GET"])
def get_status():
    response = {'role': raft_node.role.value, 'term': raft_node.current_term}
    return jsonify(response), 200


@app.route("/test", methods=["GET"])
def test():
    raft_node.role = Role.Candidate
    raft_node.run_election()
    return jsonify({'status': 200}), 200


if __name__ == "__main__":
    config_json_fp = sys.argv[1]
    config_json_idx = int(sys.argv[2])
    my_ip, my_port, peers, all_servers = parse_config_json(config_json_fp, config_json_idx)

    message_queue = MessageQueue()
    raft_node = Node(config_json_idx, peers, all_servers, message_queue)
    print(f"all server: {all_servers}")
    print(f"peers: {peers}")
    app.run(debug=False, host=my_ip, port=my_port, threaded=True)
