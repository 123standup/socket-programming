#################################
# Author: Po-Hsun Lin
#################################
from curses.ascii import isdigit
import socket
import threading
import sys
import time

class ThreadedServer():
    def __init__(self, host, port):
        ###########################
        # variables
        # status:               status state
        # type:                 bid type
        # lowest_price:         bid lowesr price
        # num_of_bids:          numbers of bids
        # cur_num_of_bids:      current numbers of bids (buyers)
        # item_name:            bid item name
        # seller:               seller's connection and address
        # buyers:               store buyer's connection and addrress
        # bids:                 buyers' bid value
        # cur_num_bids_left:    num of buyers that has not bid yet
        # final_price:          final prize for auction
        ############################
        self.status = -1
        self.type = 0
        self.lowest_price = 0
        self.num_of_bids = 0
        self.cur_num_of_bids = 0
        self.item_name = ''
        self.seller = None
        self.buyers = []
        self.bids = []
        self.cur_num_bids_left = 0
        self.final_price = 0

        # socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind((host, port))
        except OSError:
            print(f'Can not assign address {host}. Please try again using other host.')
            sys.exit(1)
        print('Auctioneer is ready for hosting acutions!')
        
    def listen(self):
        ###########################
        # status == -1: before seller connected to the server
        # status ==  0: seller connected to the server and waiting seller to input
        #               other connection request will be rejected (accept first and then reject immediately)
        # status ==  1: auction start, waiting for buyers to connect
        # status ==  2: all buyers has connected to the server, bidding starts
        #               other connection request will be rejected (accept first and then reject immediately)
        ###########################
        self.sock.listen(5)
        while True:
            conn, addr = self.sock.accept()
            conn.settimeout(60)
            conn.send(b'Connected to the Auctioneer server.\n')
            if self.status == -1:
                self.status = 0
                self.seller = tuple((conn, addr))
                threading.Thread(target = self.listenToSeller, args = (conn,)).start()
                send_text = b"Your Role is: [Seller]\nPlease submit action request:"
                show_text = f"Seller is connected from {addr[0]}:{addr[1]}\n>> New Seller Thread spawned"
                conn.send(send_text)
                print(show_text)
            elif self.status == 1:
                self.cur_num_of_bids += 1
                threading.Thread(target = self.listenToBuyer, args = (conn, self.cur_num_of_bids - 1)).start()
                self.buyers.append(tuple((conn,addr)))
                send_text = b'Your Role is: [Buyer]'
                show_text = f'Buyer {self.cur_num_of_bids} is connected from {addr[0]}:{addr[1]}'
                if self.cur_num_of_bids < self.num_of_bids:
                    send_text += b'\nThe Auctioneer is still wating for other Buyer to connect...'
                else:
                    self.status = 2
                    threading.Thread(target = self.startBidding, args = ()).start()
                    show_text += '\nRequest number of bidders arrived. Lets start bidding!'
                    show_text += '\n>> New Bidding Thread spawned'
                conn.send(send_text)
                print(show_text)
            elif self.status == 0 or self.status == 2:
                send_text = b'Server is Busy. Try to connect again later.'
                conn.send(send_text)
                conn.close()
    
    def listenToSeller(self, conn):
        ###########################
        # new thread
        # wait for seller (first client) to be connected to the server
        # after connected, invalid input will be checked by function sellerInputValid
        # if input is valid, server start waiting to buyer connection
        ###########################
        while True:
            try:
                data = conn.recv(1024)
                if data:
                    if self.sellerInputValid(data.decode()):
                        self.status = 1
                        send_text = b'Server: Auction start.'
                        show_text = f'Action request recieved. Now wating for Buyer.'
                        conn.send(send_text)
                        print(show_text)
                    else:
                        send_text = b'Server: Invalid action request!\nPlease submit action request:' 
                        conn.send(send_text)
            except KeyboardInterrupt:
                print("Caught keyboard interrupt, exiting")
            except:
                conn.close()
                return False

    def listenToBuyer(self, conn, serial):
        ###########################
        # new thread
        # wait for buyers to be connected to the server
        # after connected, invalid input will be checked by function 
        ###########################
        while True:
            try:
                data = conn.recv(1024)
                if data:
                    if self.buyerInputValid(data.decode(), serial):
                        self.cur_num_bids_left -= 1
                        send_text = b'Server: Bid recieved. Please wait...'
                        show_text = f'>> Buyer 1 bid ${self.bids[serial]}'
                        conn.send(send_text)
                        print(show_text)
                        if self.cur_num_bids_left == 0:
                            self.manifestWinner()
                    else:
                        send_text = b'Server: Invalid bid! Please submit a positve integer!\nPlease submit your bid:' 
                        conn.send(send_text)
            except KeyboardInterrupt:
                print("Caught keyboard interrupt, exiting")
            except:
                conn.close()
                return False
    
    def startBidding(self):
        ###########################
        # new thread
        # start the bidding 
        ###########################
        self.bids = [0] * len(self.buyers)
        self.cur_num_bids_left = self.cur_num_of_bids
        for i,con in enumerate(self.buyers):
            send_text = b'The bidding has started!\nPlease submit your bid:'
            con[0].send(send_text)

    def manifestWinner(self):
        ###########################
        # prompy result to seller and buyer
        # if lowest price > all bid price: 
        #   auction failed
        # else if type == 1:
        #   winner == highest bid, bid price == highest bid
        # else if type == 2:
        #   winner == highest bid, bid price == second highest bid
        ###########################
        self.seller[0].send(b'Auction Finished!')
        for conn in self.buyers:
            conn[0].send(b'Auction Finished!')
        # bids' value smaller than lowest price
        sort_index = self.argsort(self.bids)
        if self.lowest_price > self.bids[sort_index[0]]:
            self.seller[0].send(b'Unfortunately your item was not sold in the action')
            for con in self.buyers:
                con[0].send(b'Unfortunately you did not win in the last round')
            print('Unfortunately the Item is not sold')
        else:
            # auction type 1 and 2 output different price
            if self.type == 1:
                self.final_price = self.bids[sort_index[0]]
            elif self.type == 2:
                self.final_price = self.bids[sort_index[1]]
            # prompt seller and buyers the result
            send_text = f'Success! Your item {self.item_name} has been sold for ${self.final_price}. '
            # self.seller.send(send_text.encode())
            for i, con in enumerate(self.buyers):
                if i == sort_index[0]:
                    text = f'You won this item {self.item_name}! Your payment due is ${self.final_price}. '
                    text += f'Seller IP: {self.seller[1][0]}'
                    send_text += f'Buyer IP: {con[1][0]}'
                    con[0].send(text.encode())
                else:
                    con[0].send(b'Unfortunately you did not win in the last round.')
            print(f'Item sold! The highest bid is ${self.bids[sort_index[0]]}. The actual payment is ${self.final_price}')
            self.seller[0].send(send_text.encode())
        time.sleep(1)
        # close connection
        self.closeConnection(self.seller[0])
        for con in self.buyers:
            self.closeConnection(con[0])
        # clear variabels
        self.clear()

    def closeConnection(self, conn):
        ###########################
        # close connection         
        # #########################       
        conn.send(b'Disconnecting from the Auctioneer server. Auction is over!')
        conn.close()

    def clear(self):
        ###########################
        # clear all variabels and wait to srtart a new auction        
        # ######################### 
        self.status = -1
        self.type = 0
        self.lowest_price = 0
        self.num_of_bids = 0
        self.cur_num_of_bids = 0
        self.item_name = ''
        self.seller = None
        self.buyers = []
        self.bids = []
        self.cur_num_bids_left = 0
        self.final_price = 0

    def sellerInputValid(self, data) -> bool:
        ###########################
        # check seller input
        # type of auction == 1 or 
        # lowest price >= 0
        # numbers of bids between [1-10]
        # item name is string and characther lenght > 255         
        # ######################### 
        splt = data.split(' ')
        if len(splt) != 4:
            return False
        elif not splt[0].isdigit() or int(splt[0]) != 1 and int(splt[0]) != 2: # type of auction
            return False
        elif not splt[1].isdigit() or int(splt[1]) < 0: # lowest price
            return False
        elif not splt[2].isdigit() or int(splt[2]) < 0 or int(splt[2]) >= 10: # numbers of bids
            return False
        elif splt[3].isdigit() or len(splt[3]) > 255: # item name
            return False
        else:
            self.type = int(splt[0])
            self.lowest_price = int(splt[1])
            self.num_of_bids = int(splt[2])
            self.item_name = splt[3]
            return True

    def buyerInputValid(self, data, serial) -> bool:
        ###########################
        # check buyer input
        # input >= 0     
        # ######################### 
        if not data.isdigit() or int(data) < 0:
            return False
        else:
            self.bids[serial] = int(data)
            return True
    
    def argsort(self, lst) -> list:
        ###########################
        # retrun sorted list in index        
        ########################### 
        temp = []
        sort_index = []
        for i, bid in enumerate(lst):
            temp.append([bid,i])
        temp.sort(reverse = True)
        for t in temp:
            sort_index.append(t[1])
        return sort_index

if __name__ == "__main__":
    # regex pattern of valid IP address
    host = '127.0.0.1'
    port = 0
    # check input format
    if len(sys.argv) == 3:
        host = sys.argv[1]
        port = sys.argv[2]
    elif len(sys.argv) == 2:
        port = sys.argv[1]
    else:
        print(f"Usage: {sys.argv[0]} <port>")
        print(f"Usage: {sys.argv[0]} <host> <port>")
        print('port should be in range 3000-5000')
        sys.exit(1)
    # port should be in range 3000 - 5000
    if not port.isdigit() or int(port) < 3000 or int(port) > 5000:
        print('Please enter port number between 3000 - 5000')
        sys.exit(1)
    # run multithread server
    auc_server = ThreadedServer(host, int(port))
    auc_server.listen()

