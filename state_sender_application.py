import socket
import os
import numpy as np
from protocol_descriptors import HEADER_SIZE,FILE_REQUEST_BODY_SIZE,SOCKET_FAST_TIMEOUT ,SOCKET_TIMEOUT, MAX_BUFFER_SIZE, FILE_DATA_MAX_TRANSFER_SIZE, FILE_DATA_MAX_BODY_SIZE
from protocol_descriptors import wait_for_response
from protocol_descriptors import PARSE_RETURNS
from UDPFile_sender import UDPFile_sender
import sys

path_to_send_directory = 'sender_server_filesystem/'
DEBUG = False

# Client IP and connection constants
UDP_IP = "127.0.0.1"
UDP_RECEIVE_PORT = 5013 #5013#5006
UDP_SEND_PORT = 5010 #5010#5005

# Establish a connection
print(f"UDP target IP: {UDP_IP}")
print(f"UDP send port: {UDP_SEND_PORT}, UDP receive port: {UDP_RECEIVE_PORT}" )
sock_receive = socket.socket(socket.AF_INET, 
                     socket.SOCK_DGRAM)
sock_receive.bind((UDP_IP, UDP_RECEIVE_PORT))
sock_receive.settimeout(SOCKET_TIMEOUT)
sock_send = socket.socket(socket.AF_INET, 
                     socket.SOCK_DGRAM)
sock_send.settimeout(SOCKET_TIMEOUT)

# Create sender application object
UDPFile = UDPFile_sender()

# States
sender_states = {"file_request_wait": 0, \
                "file_exist_send": 1, \
                "file_start_transfer_wait": 2, \
                "sending_file_data": 3, \
                "wait_for_acknowledge": 4, \
                "end_sender": 5}

CURRENT_STATE = sender_states["file_request_wait"]


# Main while loop
transfering = True
transfer_window_idx = 0
last_transfer_window_idx = -1
last_transfer_successul = True
while True:
    print(f"CURRENT STATE: {CURRENT_STATE}")
    if CURRENT_STATE == sender_states["file_request_wait"]:
        # Wait for response
        print(f"Waiting for response, timeout: {SOCKET_TIMEOUT}...")
        success, data = wait_for_response(sock_receive, timeout=SOCKET_FAST_TIMEOUT)
        
        if not success:
            print("WARNING: file_request_wait: Receiver timed-out...")
            CURRENT_STATE = sender_states["file_request_wait"]
            continue
        else:
            # Parse received file request
            print(f'Received data of len: {len(data)}')
            print(f"Parsing data...")
            ret_dict = UDPFile.parse_file_request(data=data)

            # Parsing ret logic
            if ret_dict["return"] == PARSE_RETURNS["wrong_message_type"] or \
                    ret_dict["return"] == PARSE_RETURNS["wrong_crc"]:
                print(f"WARNING: file_request_wait: ret_dict: wrong_message_type, wrong_crc")
                CURRENT_STATE = sender_states["file_request_wait"]
                continue
            elif ret_dict["return"] == PARSE_RETURNS["request_successful"]:
                CURRENT_STATE = sender_states["file_exist_send"]
                UDPFile.path_to_file = ret_dict["file_path"] 
                continue

    elif CURRENT_STATE == sender_states["file_exist_send"]:
        # Change to faster timeout
        sock_send.settimeout(SOCKET_FAST_TIMEOUT)
        sock_receive.settimeout(SOCKET_FAST_TIMEOUT)

        exists = UDPFile.check_file_existence(path_to_file=UDPFile.path_to_file)
        if exists:
            message = UDPFile.MESSAGE_file_exists()
            CURRENT_STATE = sender_states["file_start_transfer_wait"]
            print(f"File exists...")
        else:
            message = UDPFile.MESSAGE_file_doesnt_exists()
            CURRENT_STATE = sender_states["file_request_wait"]
            print(f"File doesn't exists...")
        
        # Send message
        print(f'Sent data of size: {len(message)} bytes')
        sock_send.sendto(message, (UDP_IP, UDP_SEND_PORT))

    elif CURRENT_STATE == sender_states["file_start_transfer_wait"]:
        # Wait for response
        print(f"Waiting for response, timeout: {SOCKET_TIMEOUT}...")
        success, data = wait_for_response(sock_receive, timeout=SOCKET_FAST_TIMEOUT)
        
        if not success:
            print("WARNING: file_start_transfer_wait: Receiver timed-out...")
            CURRENT_STATE = sender_states["file_exist_send"]
            continue
        else:
            # Parse received file request
            print(f'Received data of len: {len(data)}')
            print(f"Parsing data...")
            ret_dict = UDPFile.parse_start_transfer(data=data)

            # Parsing ret logic
            if ret_dict["return"] == PARSE_RETURNS["wrong_message_type"] or \
                    ret_dict["return"] == PARSE_RETURNS["wrong_crc"]:
                print(f"WARNING: file_request_wait: ret_dict: wrong_message_type, wrong_crc")
                CURRENT_STATE = sender_states["file_exist_send"]
                continue
            elif ret_dict["return"] == PARSE_RETURNS["request_successful"]:
                CURRENT_STATE = sender_states["sending_file_data"]
                # Read file data into memory
                UDPFile.load_file_data()
                continue

    elif CURRENT_STATE == sender_states["sending_file_data"]:
        iter_start = 0
        iter_end = 0
        
        print(f"transfer_window_idx: {transfer_window_idx}")

        if not (transfering or not last_transfer_successul):
            #CURRENT_STATE = sender_states["end_sender"]
            continue

        iter_start = transfer_window_idx*FILE_DATA_MAX_TRANSFER_SIZE
        iter_end = (transfer_window_idx+1)*FILE_DATA_MAX_TRANSFER_SIZE
        if (iter_end+1) >= UDPFile.file_byte_size:
            transfering = False # End transfer
            iter_end = UDPFile.file_byte_size

            print("LAST PACKET")
            print(f"type window: {type(transfer_window_idx)}")
            # Wrap the buffer with appropriate header 
            print(f"file_data[iter_start:iter_end+1] len: {len(UDPFile.file_data[iter_start:iter_end])}")
            print(f"last_transfer_successul: {last_transfer_successul},iter_start:iter_end: {iter_start}:{iter_end}, transfering: {transfering}, UDPFile.file_byte_size: {UDPFile.file_byte_size}")
        
        message = UDPFile.MESSAGE_file_data(body=UDPFile.file_data[iter_start:iter_end], transfer_window_idx=transfer_window_idx)
        sock_send.sendto((message.astype(np.int8)).tobytes(), (UDP_IP, UDP_SEND_PORT))
        CURRENT_STATE = sender_states["wait_for_acknowledge"]
        continue

    elif CURRENT_STATE == sender_states["wait_for_acknowledge"]:
        # Wait for response
        print(f"Waiting for response, timeout: {SOCKET_TIMEOUT}...")
        success, data = wait_for_response(sock_receive, timeout=SOCKET_FAST_TIMEOUT)
        
        if not success:
            print("WARNING: wait_for_acknowledge: Receiver timed-out...")
            CURRENT_STATE = sender_states["sending_file_data"]
            continue
        else:
            # Parse received file request
            print(f'Received data of len: {len(data)}')
            print(f"Parsing data...")
            ret_dict = UDPFile.parse_file_acknowledge(data=data)
            
            # Parsing ret logic
            if ret_dict["return"] == PARSE_RETURNS["wrong_message_type"] or \
                    ret_dict["return"] == PARSE_RETURNS["wrong_crc"]:
                print(f"WARNING: file_request_wait: ret_dict: wrong_message_type, wrong_crc")
                CURRENT_STATE = sender_states["sending_file_data"]
                continue
            elif ret_dict["return"] == PARSE_RETURNS["request_successful"]:
                CURRENT_STATE = sender_states["sending_file_data"]    
                parsed_transfer_window_idx = ret_dict["transfer_window_idx"]
                transfer_window_idx = parsed_transfer_window_idx

                # if transfering == False:
                #     CURRENT_STATE = sender_states["end_sender"]
                #     continue
                #last_transfer_window_idx = transfer_window_idx

                continue

    elif CURRENT_STATE == sender_states["end_sender"]:
        print("Closing sender...")
        ## Currently the sender can get into infinite loop if he doesnt get
        # ack on last packet !!!

        ##
        break







exit()





























# Create sender application object
UDPFile = UDPFile_sender()

# Wait for file request
print("Waiting for request...")
file_path = ''
while True:
    try:
        data, addr = sock_receive.recvfrom(MAX_BUFFER_SIZE) # Buffer 1024 bytes
        if not data: break
    except socket.timeout as e:
        print(e,f': SENDER APPLICATION: Connection timeout {SOCKET_TIMEOUT} seconds')
        sock_receive.close()
        break
    
    if DEBUG: print(f'Received data: {data}')

    # Parse received file request
    file_path = UDPFile.parse_file_request(data=data)
    print(f'Received request for file: {file_path}')
    
    # if file exists -> return successfull message
    # else return unsuccessful message
    exists = UDPFile.check_file_existence(path_to_file=file_path)
    if exists:
        message = UDPFile.MESSAGE_file_exists()
        print(f"File exists...")
    else:
        message = UDPFile.MESSAGE_file_doesnt_exists()
        print(f"File doesn't exists...")
    
    # Send the message
    print(f"Sending data:")
    # Resize message for print 
    if DEBUG: 
        print_msg = np.resize(message,(-1,8))
        print(print_msg)
    print(f"message request respose: {message}")
    sock_send.sendto(message, (UDP_IP, UDP_SEND_PORT))
    print(f'Sent data of size: {len(message)} bytes')

    # If existed, break and continue to another state
    if exists: break


# Wait for start transfer message
while True:
    try:
        data, addr = sock_receive.recvfrom(MAX_BUFFER_SIZE) # Buffer 1024 bytes
        if not data: break
    except socket.timeout as e:
        print(e,f': SENDER APPLICATION: Connection timeout {SOCKET_TIMEOUT} seconds, transfer didnt start')
        sock_receive.close()
        break
    print(f'Received data: {data}')

    # Parse received file request
    if UDPFile.parse_start_transfer(data=data):
        print("Starting file transfer...")
        break
    else:
        print("Start transfer message failed, sending again")
        sock_send.sendto(message, (UDP_IP, UDP_SEND_PORT))
        # Send message again

        continue


# Transfer started, read and send file data
# It will be perpetual send and wait implementation
transfering = True
transfer_window_idx = 0
last_transfer_window_idx = -1
last_transfer_successul = True
# Open file

TEST_WRITE_BIN_DATA = []

with open('sender_server_filesystem/bitttttt.bmp', 'wb+') as file2:
    with open(UDPFile.path_to_file, 'rb') as file:
        # Read whole file once, then move the transfer window
        file_data = file.read()
        iter_start = 0
        iter_end = 0
        while (transfering or not last_transfer_successul):
            # Read new 'FILE_DATA_MAX_TRANSFER_SIZE' bytes
            # if transfer was successful, reset buffer, move window

            if DEBUG: print(f"Preparing new message buffer...")

            iter_start = transfer_window_idx*FILE_DATA_MAX_TRANSFER_SIZE
            iter_end = (transfer_window_idx+1)*FILE_DATA_MAX_TRANSFER_SIZE
            if (iter_end+1) >= UDPFile.file_byte_size:
                transfering = False # End transfer
                print("LAST PACKET")
                iter_end = UDPFile.file_byte_size
                

            if DEBUG: print(f"bytes file_data[iter_start:iter_end+1]: {bytes(file_data[iter_start:iter_end])}")
            print(f"type window: {type(transfer_window_idx)}")
            # Wrap the buffer with appropriate header 
            print(f"file_data[iter_start:iter_end+1] len: {len(file_data[iter_start:iter_end])}")
            print(f"last_transfer_successul: {last_transfer_successul},iter_start:iter_end: {iter_start}:{iter_end}, transfering: {transfering}, UDPFile.file_byte_size: {UDPFile.file_byte_size}")
            print("TELl: ",file2.tell())
            
            print(f"last_transfer_window_idx: {last_transfer_window_idx}, transfer_window_idx: {transfer_window_idx}")
            if last_transfer_successul:
                print('************* HHHAAAHHAA')
                file2.write(bytes(file_data[iter_start:iter_end]))
            
            message = UDPFile.MESSAGE_file_data(body=file_data[iter_start:iter_end], transfer_window_idx=transfer_window_idx)
            print(f"Sending transfer window: {transfer_window_idx}")
            if DEBUG:
                print(f"MESSAGE: ")
                print(message)
            print(f"sending message header: {message[:16]}")
            print(f'message length: {len(message)}')
                
            print(f"message type: {type(message)}")
            if DEBUG: print(f"sending message: {(message.astype(np.int8)).tobytes()}")
            sock_send.sendto((message.astype(np.int8)).tobytes(), (UDP_IP, UDP_SEND_PORT))

            # Wait for response 
            print(f"Waiting for packet window: {transfer_window_idx} acknowledge...")
            while True:
                try:
                    data, addr = sock_receive.recvfrom(MAX_BUFFER_SIZE)
                    if not data: break
                except socket.timeout as e:
                    print(e,f': SENDER APPLICATION: Connection timeout {SOCKET_TIMEOUT} seconds - data transfer ACK wait')
                    sock_receive.close()
                    break
                
                if DEBUG: print(f'Received data: {data}')

                # Parse received file request and check if its corrupted
                valid, parsed_transfer_window_idx = UDPFile.parse_file_acknowledge(data=data)
                last_transfer_window_idx = transfer_window_idx
                if parsed_transfer_window_idx == transfer_window_idx+1:
                    transfer_window_idx = parsed_transfer_window_idx
                if not valid:
                    print(f"Transfer was corrupted, valid: {valid}, transfering: {transfering}")
                
                # last_transfer_successul = valid
                if last_transfer_window_idx != transfer_window_idx and last_transfer_window_idx != -1:
                    last_transfer_successul = True
                else:
                    last_transfer_successul = False
                

                break


        # Send new data or repeate older one


        ## Wait for ACK
        
        # if ACK_success:
        #    transfer_windows += 1
        # else repeat transfer


# # Read binary data from the first file
# file_to_send = files_to_send[0]
# binary_data = []
# i = 1
# with open(f'{cwd}/{path_to_send_directory}/{file_to_send}', 'rb') as f:
#     byte = f.read(i)
#     i+=1
#     while byte:
#         #print(f'byte {i}: {byte}')
#         binary_data.append(byte)
#         byte = f.read(i)
#         i+=1

# data_len = len(binary_data)
# print(f'len(binary_data): {data_len}')

# # Send byte by byte
# UDP_IP = "127.0.0.1"
# UDP_PORT = 5005
# print("UDP target IP: %s" % UDP_IP)
# print("UDP target port: %s" % UDP_PORT)

# sock = socket.socket(socket.AF_INET, 
#                     socket.SOCK_DGRAM) # Internet # UDP

# for byte_idx in range(data_len):
#     MESSAGE = binary_data[byte_idx]
#     # print("message: %s" % MESSAGE)
#     sock.sendto(MESSAGE, (UDP_IP, UDP_PORT))
# print(f'len(binary_data): {data_len}')