import dataclasses
import math
from dataclasses import dataclass
from enum import Enum
from threading import Thread, RLock
import time

import requests

from logg import debug_print
from timer import ResettableTimer


class Role(Enum):
    Follower = "Follower"
    Leader = "Leader"
    Candidate = "Candidate"


@dataclass
class PersistentState:
    pass


@dataclass
class LogEntry:
    message: dict
    term: int
    success_reply: list


@dataclass
class AppendEntries:
    term: int
    leader_id: int
    prev_log_index: int
    prev_log_term: int
    entries: list  # list of LogEntries
    leader_commit: int  # leader's commit index


@dataclass
class AppendEntriesResponse:
    success: bool
    term: int
    matched_index: int


@dataclass
class VoteRequest:
    term: int
    candidate_id: int
    last_log_index: int
    last_log_term: int


@dataclass
class VoteResponse:
    term: int
    voter_id: int
    granted: bool


def serialize(rpc):
    return {"class": rpc.__class__.__qualname__, "dict": dataclasses.asdict(rpc)}


def deserialize(rpc_dict):
    rpc_obj = globals()[rpc_dict["class"]](**rpc_dict["dict"])
    if isinstance(rpc_obj, AppendEntries):
        rpc_obj.entries = [LogEntry(**val) for val in rpc_obj.entries]
    return rpc_obj


class Node:
    def __init__(self, id, peers, all_servers, message_queue):
        self.id = id
        self.current_term = 0
        self.role = Role.Follower
        self.peers = peers
        self.all_servers = all_servers
        self.voted_for = None
        self.log = []
        self.election_timer = ResettableTimer(self.run_election, interval_lb=200, interval_ub=400)
        self.heart_beat_timer = ResettableTimer(self.run_heart_beat, interval_lb=100, interval_ub=100)
        self.message_queue = message_queue  # message queue state machine
        self.election_timer.run()
        self.commit_index = -1  # volatile state on server
        self.last_applied = -1  # volatile state on server
        self.next_index = {}  # volatile state on leaders
        self.match_index = {}  # volatile state on leaders
        self.current_leader = None
        self.votes_received = set()
        self.lock = RLock()

        if len(self.peers) == 0:
            self.role = Role.Leader

    # gets last_log_index of the node, used in request_vote
    def get_last_log_index(self):
        return len(self.log) - 1

    # gets last_log_term of the node, used in request_vote
    def get_last_log_term(self):
        return self.log[self.get_last_log_index()].term if len(self.log) else -1

    def rpc_handler(self, sender_id, rpc_message_json):
        debug_print("received rpc str", sender_id, rpc_message_json)
        rpc_message = deserialize(rpc_message_json)
        # self.on_receiving_rpc_request(rpc_message)
        if isinstance(rpc_message, VoteRequest):
            debug_print("Received vote request, responding... passing to handle_vote_request")
            response, status_code = self.handle_vote_request(rpc_message)
            return response, status_code
        elif isinstance(rpc_message, AppendEntries):
            debug_print("Received append entries, responding... passing to handle_append_entries_request")
            response, status_code = self.handle_append_entries_request(rpc_message)
            return response, status_code
        elif isinstance(rpc_message, VoteResponse):
            debug_print("Received vote response, processing....")
            self.handle_vote_response(rpc_message)
        elif isinstance(rpc_message, AppendEntriesResponse):
            debug_print("Received append entries response, processing....")
            self.handle_append_entries_response(sender_id, rpc_message)
        return {"thank you": "come again"}, 200

    # Event handlers --------------------------------------------------------------

    # handles vote_request rpc broadcast from candidate nodes
    def handle_vote_request(self, vote_request):
        self.on_receiving_rpc_request(vote_request)
        # check if candidate log is at least up to date as receiver's log
        log_ok = (vote_request.last_log_term > self.get_last_log_term()) or (
                (vote_request.last_log_term == self.get_last_log_term())
                and (vote_request.last_log_index >= self.get_last_log_index())) or (
                         (vote_request.last_log_term == -1) and (len(self.log) == 0))
        if ((vote_request.term == self.current_term) and log_ok and (
                self.voted_for is None or self.voted_for == vote_request.candidate_id)):
            self.voted_for = vote_request.candidate_id
            self.election_timer.reset()
            # serialized into dict {class : ... , dict : ...}
            response = serialize(VoteResponse(self.current_term, self.id, True))
            return response, 200
        else:
            # serialized into dict {class : ... , dict : ...}
            response = serialize(VoteResponse(self.current_term, self.id, False))
            return response, 200

    # handles vote_request rpc response from voting participants
    def handle_vote_response(self, vote_response):
        if self.role == Role.Candidate \
                and self.current_term == vote_response.term and vote_response.granted:
            self.votes_received.add(vote_response.voter_id)
            if len(self.votes_received) >= math.ceil((len(self.all_servers) + 1) / 2):
                debug_print("Elected Leader!")
                self.on_election_win()  # perform state changes and propagate side effects

    # handles append_entries rpc request broadcast from leader
    def handle_append_entries_request(self, append_entries_request):
        self.on_receiving_rpc_request(append_entries_request)
        if append_entries_request.term == self.current_term:  # received heart beat
            self.current_leader = append_entries_request.leader_id
            self.election_timer.reset()
        prev_log_index = append_entries_request.prev_log_index
        prev_log_term = append_entries_request.prev_log_term

        if append_entries_request.term == self.current_term \
                and prev_log_index == -1 and prev_log_term == -1:  # initial message
            self.log = append_entries_request.entries
            response = serialize(AppendEntriesResponse(True, self.current_term, len(self.log) - 1))
            self.update_state_machine(append_entries_request)
            debug_print("Finished updating local state machine*************************")
            debug_print(f"local topics are {self.message_queue.queues}")
            debug_print(f"local logs are {self.log}")
            debug_print(f"Response to leader should be {response}")
            return response, 200
        # reply false if log does not contain an entry at prevlogindex whose term matches pervlogindex
        if append_entries_request.term < self.current_term \
                or prev_log_index >= len(self.log) \
                or self.log[prev_log_index].term != prev_log_term:
            response = serialize(AppendEntriesResponse(False, self.current_term, -1))
            return response, 200
        if len(append_entries_request.entries) > 0:
            self.log = self.log[:prev_log_index + 1]
            for entry in append_entries_request.entries:
                self.log.append(entry)
        response = serialize(AppendEntriesResponse(True, self.current_term, self.get_last_log_index()))
        self.update_state_machine(append_entries_request)
        debug_print("Finished updating local state machine*************************")
        return response, 200

    # handles response got from sending append_entry rpc
    def handle_append_entries_response(self, sender_id, append_entries_response):
        if not append_entries_response.success:
            if self.next_index[sender_id] > 0:
                self.next_index[sender_id] -= 1
        else:  # followers successfully replicated log
            debug_print(f"Node {sender_id} replicated log successfully, updating successReply")
            old_match_index = self.match_index[sender_id]
            self.match_index[sender_id] = append_entries_response.matched_index
            self.next_index[sender_id] = append_entries_response.matched_index + 1
            for i in range(old_match_index + 1, append_entries_response.matched_index + 1):
                self.log[i].success_reply.append(sender_id)

    # Event handlers END--------------------------------------------------------------

    # Functions run by the resettable timer ------------------------------------------
    def run_election(self):
        self.election_timer.reset()  # reset election timer
        if self.role == Role.Leader:
            debug_print("Already leader, cannot run election")
            return
        # from raft paper:
        # to begin an election, a follower increments its current term and transition
        # to candidate state. It then votes for itself and issues RequestVote RPCs
        # in parallel to each of the other servers in the cluster
        debug_print(f"starting election, current role is {self.role}")
        self.current_term += 1  # increment its current term
        self.role = Role.Candidate  # transition to candidate state
        self.voted_for = self.id  # vote for itself, need to +1 to vote received
        self.votes_received.add(self.id)
        self.broadcast_request_vote(
            serialize(
                VoteRequest(
                    self.current_term,
                    self.id,
                    self.get_last_log_index(),
                    self.get_last_log_term()
                )
            )
        )

    # broadcasts request_vote to peer and gather votes
    # returns the number of votes received from peers
    def broadcast_request_vote(self, json_payload):
        for _ip, port, node_id in self.peers:
            self.lock.acquire()
            try:
                response = requests.post(
                    f"http://localhost:{port}/request-vote/{self.id}", json=json_payload, timeout=500
                )
                if response.json():  # gets back VoteResponse rpc message
                    # need to call handle_rpc to handle vote_response
                    debug_print(f"Received request_vote rpc response: {response.json()}")
                    rpc_message_json = response.json()  # should be a vote_response
                    self.rpc_handler(node_id, rpc_message_json)  # no return
            except Exception as e:
                debug_print(f"Failed to request vote from port {port}", e)
            self.lock.release()

    def run_heart_beat(self):
        if self.role != Role.Leader:
            debug_print("Cannot send heart beat without being a leader")
            return
        debug_print("Sending out heartbeat to followers")
        self.heart_beat_timer.reset()
        # broadcast to followers
        for _ip, port, node_id in self.peers:
            self.lock.acquire()
            prev_log_index = self.next_index[node_id] - 1
            if prev_log_index < 0:
                prev_log_term = -1
                entries = self.log
            else:
                prev_log_term = self.log[prev_log_index].term
                entries = self.log[prev_log_index + 1:]
            if len(entries) > 0:
                debug_print(f"Log entries to send to followers are {entries}")
            try:
                json_payload = serialize(
                    AppendEntries(
                        self.current_term,
                        self.id,
                        prev_log_index,
                        prev_log_term,
                        entries,
                        self.commit_index
                    )
                )
                response = requests.post(
                    f"http://localhost:{port}/heart-beat/{self.id}", json=json_payload
                )
                if response.json():  # gets back append_entries_response rpc message
                    debug_print(f"Received append_entries_response rpc message: {response.json()}****************************")
                    rpc_message_json = response.json()
                    self.rpc_handler(node_id, rpc_message_json)
            except Exception as e:
                debug_print(f"Failed to send append_entries rpc to port: {port}", e)
            self.lock.release()

    # Side Effect functions -----------------------------------------------------
    def on_receiving_rpc_request(self, rpc_request):
        if rpc_request.term > self.current_term:
            debug_print("Discovered higher term, converting to follower")
            self.current_term = rpc_request.term
            self.role = Role.Follower
            self.voted_for = None

    def on_election_win(self):
        if self.role == Role.Candidate:
            self.role = Role.Leader
            self.current_leader = self.id
            self.election_timer.cancel()
            self.on_candidate_to_leader()

    # Changing state from candidate to leader after election won
    # initialize next_index and match_index
    # start heart_beat_timer that periodically broadcast heartbeat to followers
    def on_candidate_to_leader(self):
        self.next_index = [self.get_last_log_index() + 1 for i in self.all_servers]  # initialized to be leader last log index + 1
        self.match_index = [-1 for i in self.all_servers]  # initialized to be -1, increases monotonically
        debug_print(f"Leader next_index initialized to be {self.next_index}")
        debug_print(f"Leader match_index initialized to be {self.match_index}")
        self.run_heart_beat()

    def on_leader_to_follower(self):
        pass

    def on_candidate_to_follower(self):
        pass

    def convert_to_follower(self):
        if self.role == Role.Leader:
            self.role = Role.Follower
            self.on_leader_to_follower()
        if self.role == Role.Candidate:
            self.role = Role.Follower
            self.on_candidate_to_follower()

    # Side Effect functions END-----------------------------------------------------

    # Replication related --------------------------------------------------------
    def update_state_machine(self, append_entries_request):
        if append_entries_request.leader_commit >= self.commit_index:
            debug_print("Updating local log and state machine--------------------------------------")
            # self.lock.acquire()
            self.commit_index = min(append_entries_request.leader_commit, self.get_last_log_index())
            old_last_applied = self.last_applied
            for i in range(old_last_applied + 1, self.commit_index + 1):
                debug_print(f"Processing log command indexed {i}")
                self.message_queue.process_command(self.log[i].message, self.role)
                self.last_applied = i
            # self.lock.acquire()
        else:
            debug_print("Did not update local log and state machine--------------------------------------")

    # Client command handler --------------------------------------------------------
    def client_command_handler(self, command_message):
        debug_print(command_message)
        client_task = LogEntry(command_message, self.current_term, [])
        client_task.success_reply.append(self.id)
        self.log.append(client_task)
        debug_print(f"Appended client_task {client_task} to local log--------------------")
        counter = 0  # make-shift time out util
        while True:
            debug_print(f"Waiting for log to be replicated, number of success_reply are {len(client_task.success_reply)}")
            if len(client_task.success_reply) >= math.ceil((len(self.all_servers) + 1) / 2):
                self.commit_index = self.get_last_log_index()
                response = self.message_queue.process_command(command_message, self.role)
                self.last_applied = self.commit_index
                return response
            time.sleep(0.1)
            counter += 1
            if counter == 10:
                return
