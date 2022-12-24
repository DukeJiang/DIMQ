## Part 1 Implementation:
### Design:
Design for the message queue is pretty straight forward. <br>
I have a MessageQueue class that defines the underlying dictionary for
managing topics and messages.<br>
The message queue offers a process_command interface that takes in a command_message(dict),
and the role of the node that is trying to execute that command.<br>
Only Leader is allowed to return success response<br>
When launching the node, node.py spin up the Flask server, instantiate a MessageQueue instance,
and instantiate a Node instance defined in raft.py.<br>
Inside the raft node, it uses a client_command_handler to process all incoming client command.
When an endpoint related to topic and message is invoked, the request json body is first parsed,
and then passed to client_command_handler, the handler will return a response dict which is directly
used to respond to the invoker of the endpoint.


### Potential Shortcomings:
1. Did not do dependency injection.
2. Relies on flask to handle concurrent request for processing message queue command


## Part 2 Implementation:
### Design:
For leader election, I followed the Raft paper and put the majority of the election logic
in handle_vote_request event handler. This is one of the event handler that is implemented.
For handling inter-node communication, I have a rpc_handler function that direct incoming rpc request
and response messages to different handlers. vote_request_handler is the function that handles
incoming vote request broadcast by leader. <br>
The broadcast function hits /request-vote endpoint of each peer node, gathers the responses and
calls rpc_handler again so that vote_response_handler can be invoked. <br>
When a node receives a vote_request, it checks if the candidate's log is at least up to date and that
itself has not voted for any other nodes in the current term. I also have a on_receiving_rpc_message
function to check for higher_terms. If there is a higher_term in the incoming rpc message, the node
on the receiving end will be reverted to follower if not already a follower. A set of side effect functions
are called to restore state.<br>
Upon winning an election, a node will convert its role to leader and cancel the election_timer. It will
initialize next_index and match_index as shown in the paper and start the heart_beat_timer to send
heartbeat as well as regular append_entries rpc messages


### Potential Shortcomings:
1. Vote request messages are not sent out in parallel
2. Broadcasting vote request relies on locking the section where the requests are sent out


## Part 3 Implementation:
### Design:
When a node is elected leader, it will be responsible for sending out heart beat as well as append_entry
rpc message to its followers. I have a heart_beat_timer that starts running when a node is elected
leader, and it periodically sends out append_entries rpc messages. Heart_beat_timer gets reset every time run_heart_beat function
is called, creating an event loop. <br>
The leader node exposes a client_command_handler to the flask app so that REST request
can propagate its side effect to leader node. Flask app endpoints parses request json body
into a dict and pass it as command to the client_command_handler.<br>
Upon accepting client command, the leader node creates a client_task and updates its log.
It then starts a loop to check if enough nodes have replied success to replicating that client_task
in the log. The loop checks at a certain interval and times out after a certain number of tries. This is
a make-shift solution to prevent infinite loop. At every heart beat, append entries requests will be
sent out to follower which will contain the newly added client task in the entries array. 
When a follower respond with and append_entries_response, the handle_append_entries_response function
will update corresponding client task in leader's local log. Specifically, the id of the node that
has responded success will be appended to the success_reply array of that client task (LogEntry).<br>
At a certain time, the number of nodes that replied success might reach majority (before loop times out).
When that happens, the leader node updates its own message queue and commit the changes.
On the follower's side, I followed the description in the paper to perform a number of checks before calling
update_state_machine function to commit changes described in the incoming entries log.


### Potential Shortcomings:
1. Append entry requests are sent out by the callback function passed to heart_beat_timer which means
    append entry rpc message will not be immediately sent out. Heart beat is every 50ms so the delay is negligible
2. Append entry requests are not sent out in parallel
3. Leader node need to run a loop that times out after a certain number of tries to check if replication is complete for follower nodes.
    if the system fails during loop, the system might enter an inconsistent state.


## Sources:
1. https://github.com/makslevental/raft_rust
2. https://raft.github.io/
3. https://raft.github.io/raft.pdf
4. https://realpython.com/intro-to-python-threading/