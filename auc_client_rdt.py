#################################
# Author: Po-Hsun Lin
#################################
import sys
import socket
import selectors
import types
import random
import time

class Error(Exception):
    # base class for custom exception
    pass

class AckMisMatchError(Error):
    # raise when Ack is not matched
    pass

class PacketLossError(Error):
    # raise when packet dropped occur
    pass

class IPMisMatch(Error):
    # raise when IP is not matched
    pass

class Client():
    def __init__(self, host, port):
        ###########################
        # host : server ip address
        # port : server port
        # state: 0->pass 1:->Seller(UDP Client) 2:->Server(UDP Server) 3:->auction finished
        ###########################
        self.host = host
        self.port = port
        self.sel = selectors.DefaultSelector()
        self.state = 0
        self.udp_addr = None

    def start_connections(self):
        ###########################
        # connect to server
        ###########################
        server_addr = (self.host, self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        sock.connect_ex(server_addr)
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        data = types.SimpleNamespace(outb = b"")
        self.sel.register(sock, events, data = data)
        try:
            while True:
                events = self.sel.select(timeout = None)
                for key, mask in events:
                    self.service_connection(key, mask)
                if self.state != 0:
                    break
        except ConnectionResetError:
            print("Server has closed the connection")
        except KeyboardInterrupt:
            print("Caught keyboard interrupt, exiting")
        finally:
            self.sel.close()
    
    def service_connection(self, key, mask):
        ###########################
        # listen to server
        # when recieve submit message from server, send message to server
        ###########################
        sock = key.fileobj
        data = key.data
        if mask & selectors.EVENT_READ:
            recv_data = sock.recv(1024)
            if recv_data:
                show_text = recv_data.decode()
                print(show_text)
                if "submit" in show_text:
                    send_text = input()
                    sock.send(send_text.encode())
                elif "Seller IP: " in show_text:
                    self.udp_addr = show_text.split(' ')[-1]
                    self.state = 2
                elif "Buyer IP: " in show_text:
                    self.udp_addr = show_text.split(' ')[-1]
                    self.state = 1
                elif "Auction is over" in show_text:
                    self.state = 3

class UDPServer():
    
    def __init__(self, host, port, prob=0.1):
        ###########################
        # variables
        # file_addr:            receive file local address
        # chunk_size:           maximum chunk size per packet
        # file_length:          file length in byte
        # bgn:                  begin index when slicing bytes_to_send
        # end:                  end index when slicing bytes_to_send
        # sock:                 udp socket
        # server_addr:          UDP server address (this machine)
        # buffer_size:          socket buffer size
        # type:                 data type (0 or 1) when sending file
        # ack:                  ack num used in relaibel transfer
        # prob:                 packet loss probability
        # connected             check if it is the first time client connect with the server
        # client_addr:          UDP client's address
        # start_time:           when receive the first package
        # end_time:             when receive the last package
        ############################
        # file setup
        self.file_adr = "recved.file"
        self.chunk_size = 2000
        self.file_length = None
        self.end = 0
        self.data = None
        # udp socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_addr = (host, port)
        self.buffer_size = 3000
        self.type = None
        self.ack = None
        self.pre_ack = 1
        self.prob = prob
        self.connected = False
        self.client_addr = None
        self.start_time = None
        self.end_time = None
        # output UDP socket opened msg
        print("UDP socket openned for RDT.")

    def recv(self):
        ###########################
        # 1. open or create recved.file, clear the file, and close
        # 2. bind IP address with the socket and strat listening
        # 3. send initial data (start file_length) to server(winner buyer)
        # 4. generate rand list 
        # 4. start to receive data form client
        # 5. when trasmission finished, calcuate required performance data
        ###########################
        # create and clean recv file
        open(self.file_adr, "w").close()
        # bind to address the IP and listen
        self.sock.bind(self.server_addr)
        print("UDP socket openned for RDT.")
        print("Start receiving file.")
        # Receiving data
        self.recv_file()
        tct = self.end_time - self.start_time
        at = self.file_length / tct
        print("Transmission finished: {} bytes / {:.6f} seconds = {:.6f} bps".format(self.file_length, tct, at))
        
    def recv_file(self):
        ###########################
        # try: 
        #       wait for client to send message
        #       send ack back to client
        # except socket.timeout:
        #       retransmit
        # except IPMisMatch:
        #       if received message not from UDP client, discard and retransmit
        # except AckMisMatchError:
        #       if ack not match with seq num, discard and retransmit
        # except PacketLossError:
        #       if packet loss: retransmit
        ###########################
        while True:
            try:
                if self.connected:  self.sock.settimeout(2)
                else: self.start_time = time.time()
                recv_msg = self.sock.recvfrom(self.buffer_size)
                msg = recv_msg[0].decode()
                self.ack, self.type, self.data = msg[0], msg[1], msg[2:]
                expect_ack = 1 if self.pre_ack == 0 else 1 
                if self.pre_ack ^ int(self.ack) == 0:
                    raise AckMisMatchError
                if self.is_packet_dropped():
                    raise PacketLossError
                if self.client_addr == None:
                    self.client_addr = tuple(recv_msg[1])
                elif self.client_addr != recv_msg[1]:
                    raise IPMisMatch
                self.sock.sendto(self.ack.encode(), self.client_addr)
                if not self.parse_pkt():
                    print("All data received! Exiting...") 
                    break
            except socket.timeout:
                print("Ack re-sent: {}".format(self.pre_ack))
                self.sock.sendto(str(self.pre_ack).encode(), recv_msg[1])
            except PacketLossError:
                print("Pkt dropped: {}".format(expect_ack))
                print("Ack re-sent: {}".format(self.pre_ack))
                self.sock.sendto(str(self.pre_ack).encode(), recv_msg[1])
            except AckMisMatchError:
                print("Msg received with mismatched sequence number {}. Expecting {}".format(self.ack, expect_ack))
                print("Ack re-sent: {}".format(self.pre_ack))
                self.sock.sendto(str(self.pre_ack).encode(), recv_msg[1])
            except IPMisMatch:
                pass
                
    def parse_pkt(self) -> bool:
        ###########################
        # if type == "0" and "start" in message:
        #       connected = True tells that server has connected to the client
        # if type == "0" and "fin" in message:
        #       received all data
        # if type == "1":
        #       write recv data into file 
        ###########################
        self.pre_ack = int(self.ack)
        print("Msg received: {}".format(self.ack))
        print("Ack sent: {}".format(self.ack))
        if self.type == "0":
            if "start" in self.data:
                self.file_length = int(self.data.split(" ")[1])
                self.connected = True
                return True
            elif "fin" in self.data:
                self.end_time = time.time()
                return False
        elif self.type == "1":
             f = open(self.file_adr, "a")
             f.write(self.data)
             f.close()
             self.end += len(self.data)
             print("Received data seq {}: {} / {}".format(self.ack, self.end, self.file_length))
             return True

    def is_packet_dropped(self):
        ###########################
        # return if packet will drop
        ###########################
        return True if self.prob > random.random() else False

class UDPClient():
    
    def __init__(self, host, port, prob=0.1):
        ###########################
        # variables
        # file_addr:            send file local address
        # bytes_to_send:        file content in byte form
        # file_length:          file length in byte
        # chunk_size:           maximum chunk size per packet
        # bgn:                  begin index when slicing bytes_to_send
        # end:                  end index when slicing bytes_to_send
        # sock:                 udp socket
        # server_addr:          UDP server address that client want to connect
        # buffer_size:          socket buffer size
        # seq:                  seq num used in relaible transfer
        # type:                 data type (0 or 1) when sending file
        # ack:                  ack num used in relaibel transfer
        # prob:                 packet loss probability
        ############################
        # file setup
        self.file_adr = "tosend.file"
        self.bytes_to_send = None
        self.file_length = None
        self.chunk_size = 2000
        self.bgn = 0
        self.end = self.bgn + self.chunk_size
        # udp socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_addr = (host, port)
        self.buffer_size = 3000
        self.seq = 0
        self.type = 0
        self.ack = None
        self.prob = prob
        # output UDP socket opened msg
        print("UDP socket openned for RDT.")
    
    def send(self):
        ###########################
        # 1. open tosend.file, store file content in bytes_to_send, and calculate total byte length
        # 2. generate rand list 
        # 3. send initial data (start file_length) to server(winner buyer)
        # 4. start to send file content to server
        # 5. send fin to server indicate end of transfer
        ###########################
        # read file and get file length in byte
        f = open(self.file_adr, "r")
        self.bytes_to_send = f.read()
        f.close()
        self.file_length = len(self.bytes_to_send.encode())
        # send initial
        print("Start sending file.")
        print("Sending control seq {}: start {}".format(str(self.seq), str(self.file_length)))
        self.send_start()
        # send data
        self.seq, self.type = 1, 1
        while self.bgn <= self.file_length:
            print("Sending data seq {}: {} / {}".format(self.seq, self.end, self.file_length))
            self.send_data()
        # send signal fin
        self.type = 0
        print("Sending control seq {}: fin".format(str(self.seq)))
        self.send_fin()

    def send_start(self):
        ###########################
        # try: 
        #       send start message to server
        #       wait for server response with timeout mechanism
        # except socket.timeout:
        #       retransmit
        # except IPMisMatch:
        #       if received message not from UDP server, discard and retransmit
        # except AckMisMatchError:
        #       if ack not match with seq num, discard and retransmit
        # except PacketLossError:
        #       if packet loss: retransmit
        ###########################
        while True:
            try:
                send_msg = str(self.seq) + str(self.type) + "start " + str(self.file_length)
                self.sock.sendto(send_msg.encode(), self.server_addr)
                self.sock.settimeout(2)
                msg_recv = self.sock.recvfrom(self.buffer_size)
                self.ack = msg_recv[0].decode()[0]
                if msg_recv[1] != self.server_addr:
                    raise IPMisMatch
                if self.ack != str(self.seq):
                    raise AckMisMatchError
                if self.is_packet_dropped():
                    raise PacketLossError
            except socket.timeout:
                print("Msg re-sent: {}".format(str(self.seq)))
            except PacketLossError:
                print("Ack dropped: {}".format(self.seq))
                print("Msg re-sent: {}".format(str(self.seq)))
            except AckMisMatchError:
                print("Ack received with mismatched sequence number {}. Expecting {}".format(self.ack, self.seq))
                print("Msg re-sent: {}".format(str(self.seq)))
            except IPMisMatch:
                pass
            else:
                print("Ack received: {}".format(self.ack))
                break
    
    def send_data(self):
        ###########################
        # try: 
        #       send file content to server
        #       wait for server response with timeout mechanism
        # except socket.timeout:
        #       retransmit
        # except IPMisMatch:
        #       if received message not from UDP server, discard and retransmit
        # except AckMisMatchError:
        #       if ack not match with seq num, discard and retransmit
        # except PacketLossError:
        #       if packet loss: retransmit
        ###########################
        while True:
            try:
                send_msg = str(self.seq) + str(self.type) + str(self.bytes_to_send[self.bgn:self.end])
                self.sock.sendto(send_msg.encode(), self.server_addr)
                self.sock.settimeout(2)
                msg_recv = self.sock.recvfrom(self.buffer_size)
                self.ack = msg_recv[0].decode()[0]
                if msg_recv[1] != self.server_addr:
                    raise IPMisMatch
                if self.ack != str(self.seq):
                    raise AckMisMatchError 
                if self.is_packet_dropped():
                    raise PacketLossError
            except socket.timeout:
                print("Msg re-sent: {}".format(str(self.seq)))
            except PacketLossError:
                print("Ack dropped: {}".format(self.seq))
                print("Msg re-sent: {}".format(str(self.seq)))
            except AckMisMatchError:
                print("Ack received with mismatched sequence number {}. Expecting {}".format(self.ack, self.seq))
                print("Msg re-sent: {}".format(str(self.seq)))
            except IPMisMatch:
                pass
            else:
                self.seq = 1 if self.seq == 0 else 0
                self.bgn += self.chunk_size
                self.end += self.chunk_size
                self.end = self.file_length if self.end > self.file_length else self.end
                print("Ack received: {}".format(self.ack))
                break
    
    def send_fin(self):
        ###########################
        # try: 
        #       send fin message to server
        #       wait for server response with timeout mechanism
        # except socket.timeout:
        #       retransmit
        # except IPMisMatch:
        #       if received message not from UDP server, discard and retransmit
        # except AckMisMatchError:
        #       if ack not match with seq num, discard and retransmit
        # except PacketLossError:
        #       if packet loss: retransmit
        ###########################
        while True:
            try:
                send_msg = str(self.seq) + str(self.type) + "fin"
                self.sock.sendto(send_msg.encode(), self.server_addr)
                self.sock.settimeout(2)
                msg_recv = self.sock.recvfrom(self.buffer_size)
                self.ack = msg_recv[0].decode()[0]
                if msg_recv[1] != self.server_addr:
                    raise IPMisMatch
                if self.ack != str(self.seq):
                    raise AckMisMatchError 
            except socket.timeout:
                print("Msg re-sent: {}".format(str(self.seq)))
            except AckMisMatchError:
                print("Ack received with mismatched sequence number {}. Expecting {}".format(self.ack, self.seq))
                print("Msg re-sent: {}".format(str(self.seq)))
            except IPMisMatch:
                pass
            else:
                print("Ack received: {}".format(self.ack))
                break

    def is_packet_dropped(self):
        ###########################
        # return if packet will drop
        ###########################
        return True if self.prob > random.random() else False

if __name__ == '__main__':
    # check input format
    if len(sys.argv) != 4 and len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <host> <port> <rdt_port>")
        print(f"Usage: {sys.argv[0]} <host> <port> <rdt port> <packet loss rate>")
        sys.exit(1)
    # check input data integrity
    host, port, rdt_port, pkt_loss_rate = None, None, None, "0"
    if len(sys.argv) == 4:
        host, port, rdt_port = sys.argv[1:4]
    elif len(sys.argv) == 5:
        host, port, rdt_port, pkt_loss_rate = sys.argv[1:5]
    # run client
    client = Client(host, int(port))
    client.start_connections()
    # run UDP server or client
    if client.state == 1: # seller (UDP client)
        UDPClient(client.udp_addr, int(rdt_port), float(pkt_loss_rate)).send()
    elif client.state == 2: # client (UDP server)
        UDPServer("0.0.0.0", int(rdt_port), float(pkt_loss_rate)).recv()