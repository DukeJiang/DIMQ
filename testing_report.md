## Note:
Since the tests are in the test folder, after installing pytest and at root directory I ran:<br>
pytest test/..._test.py<br>
to run all the tests

## Part 1 test:
### How I tested:
Passed all tests in message_queue_test.py <br>
Manually tested by launching five flask apps with config file my_config.json.<br>
I have postman setup and tested all the api endpoints working. I then posted topics as well as
messages to the message queue of the leader node and confirmed that messages and topics all exist.<br>
When follower nodes are shut down, the leader node still has all the messages and topics in the message queue.<br>
Confirmed that correct response format are returned.

### Potential shortcomings:
1. Follower nodes do not redirect traffics to leader node


## Part 2 test:
### How I tested:
Passed all tests in election_test.py<br>
Manually launched five flask apps with config file my_config.json same as last part.<br>
After five flask apps have been running, I observed the role and term of each node with the /status
endpoint and saw one leader was elected in one term.<br>
I then shut down two instance one by one. Each time a follower node was shut down, 
a new leader was shortly elected.<br>
I also set up a many debug prints to see if heartbeats are regularly sent out and properly process.<br>

### Potential shortcomings:
1. Did not test leader election for a large number of node
2. Did not test faster heartbeat intervals

## Part 3 test:
### How I tested:
Passed all tests in replication_test.py<br>
Again manually launched five flask apps with config file my_config.json same as last part.<br>
After five flask apps have been running, I checked for leader node and then sent some test topics and messages
with PUT requests. I then checked the content of the message queue that the leader has with GET requests.
I confirmed that the leader has the correct message queue content and via many debug print, I checked
the replication logics are executed as intended.<br>
I then shut down the leader node and identified a new leader has been created. I made GET requests to the new
leader and then verified that topics are messages are consistent.

### Potential shortcomings:
1. Did not test at larger scale
2. Did not test a chain of failure happening within a heartbeat interval