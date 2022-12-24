from raft import Role


class MessageQueue:
    def __init__(self):
        self.queues = {}

    # interface for message queue
    def process_command(self, command, role):
        command_type = command['type']
        if command_type == 'topic':
            if command['method'] == 'PUT':
                topic = command['topic']
                if topic in self.queues:
                    if role == Role.Leader:
                        return {"success": False}
                else:
                    self.queues[topic] = []
                    if role == Role.Leader:
                        return {"success": True}
            elif command['method'] == 'GET':
                if role == Role.Leader:
                    return{"success": True, "topics": list(self.queues.keys())}
            else:
                return {"success": False}
        if command_type == 'message':
            topic = command['topic']
            method = command['method']
            if method == 'PUT':
                message = command['message']
                if topic in self.queues:
                    self.queues[topic].append(message)
                    if role == Role.Leader:
                        return {"success": True}
                else:
                    if role == Role.Leader:
                        return {"success": False}
            elif method == 'GET':
                if (topic not in self.queues) or (len(self.queues[topic]) == 0):
                    if role == Role.Leader:
                        return {"success": False}
                else:
                    message = self.queues[topic].pop(0)
                    if role == Role.Leader:
                        return {"success": True, "message": message}
        else:
            if role == Role.Leader:
                return {"success": False}