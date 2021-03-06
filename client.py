#!/usr/bin/env python

import ao
import mad
import readline
import socket
import struct
import sys
import threading
import cPickle as pickle
from time import sleep

RECV_BUFFER_SIZE = 1024
BUF_TO_STREAM = 1

current_song = -1
number_of_songs = 0

# The Mad audio library we're using expects to be given a file object, but
# we're not dealing with files, we're reading audio data over the network.  We
# use this object to trick it.  All it really wants from the file object is the
# read() method, so we create this wrapper with a read() method for it to
# call, and it won't know the difference.
# NOTE: You probably don't need to modify this class.
class mywrapper(object):
    def __init__(self):
        self.mf = None
        self.data = ""

    # When it asks to read a specific size, give it that many bytes, and
    # update our remaining data.
    def read(self, size):
        result = self.data[:size]
        self.data = self.data[size:]
        return result


# Receive messages.  If they're responses to info/list, print
# the results for the user to see.  If they contain song data, the
# data needs to be added to the wrapper object.  Be sure to protect
# the wrapper with synchronization, since the other thread is using
# it too!
def recv_thread_func(wrap, cond_filled, sock):
    
    global number_of_songs
   

    recv_string = ""
    buf_count = 0

    packet = {}
    packet["type"] = "list_length_request"
    sock.sendall(pickle.dumps(packet)) 
    data = sock.recv(200)
    packet = pickle.loads(data)
    number_of_songs = int(packet["msg"])

    while True:
       
        # Gather the packet
        try:
            data = sock.recv(20000)
            packet = pickle.loads(data)
        except:
            pass

        if packet["type"] == "server_stop":
            wrap.data = ""
            wrap.mp = None
            recv_string = ""
            buf_count = 0

        if packet["last"] == True:

            if packet["type"] == "server_song":
                wrap.data += recv_string
                if wrap.mf == None:
                    wrap.mf = mad.MadFile(wrap)

                recv_string = ""
                buf_count = 0

        # If list response
        if packet["type"] == "server_list":

            while True:

                if data:
                    recv_string += packet["msg"]
                    if packet["last"] == True:
                        break
                else:
                    break

            for index, song_name in pickle.loads(recv_string).iteritems():
                print(str(index) + ": " + song_name)
       
        # If list response
        if packet["type"] == "server_song":

            if data:
                recv_string += packet["msg"]
                buf_count += 1

                packet["type"] = "client_ack"
                packet["seq"] = packet["seq"] + 1
                packet["msg"] = ""
                packet["len"] = len(packet["msg"])
                sock.sendall(pickle.dumps(packet))
                
                if buf_count >= BUF_TO_STREAM:
                    
                    wrap.data += recv_string
                    if wrap.mf == None:
                        wrap.mf = mad.MadFile(wrap)
                    
                    recv_string = ""
                    buf_count = 0


            else:
                break

            

    pass


# If there is song data stored in the wrapper object, play it!
# Otherwise, wait until there is.  Be sure to protect your accesses
# to the wrapper with synchronization, since the other thread is
# using it too!
def play_thread_func(wrap, cond_filled, dev):
    while True:
        """
        TODO
        example usage of dev and wrap (see mp3-example.py for a full example):
        buf = wrap.mf.read()
        dev.play(buffer(buf), len(buf))
        """

        while True:
            if wrap.mf:
                buf = wrap.mf.read()
                if buf is None:
                    break
                dev.play(buffer(buf), len(buf))



def main():
    if len(sys.argv) < 3:
        print 'Usage: %s <server name/ip> <server port>' % sys.argv[0]
        sys.exit(1)

    # Create a pseudo-file wrapper, condition variable, and socket.  These will
    # be passed to the thread we're about to create.
    wrap = mywrapper()

    # Create a condition variable to synchronize the receiver and player threads.
    # In python, this implicitly creates a mutex lock too.
    # See: https://docs.python.org/2/library/threading.html#condition-objects
    cond_filled = threading.Condition()

    # Create a TCP socket and try connecting to the server.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((sys.argv[1], int(sys.argv[2])))

    # Create a thread whose job is to receive messages from the server.
    recv_thread = threading.Thread(
        target=recv_thread_func,
        args=(wrap, cond_filled, sock)
    )
    recv_thread.daemon = True
    recv_thread.start()

    # Create a thread whose job is to play audio file data.
    dev = ao.AudioDevice('pulse')
    play_thread = threading.Thread(
        target=play_thread_func,
        args=(wrap, cond_filled, dev)
    )
    play_thread.daemon = True
    play_thread.start()

    global current_song
    global number_of_songs

    # Enter our never-ending user I/O loop.  Because we imported the readline
    # module above, raw_input gives us nice shell-like behavior (up-arrow to
    # go backwards, etc.).
    while True:

        line = raw_input('>> ')

        if ' ' in line:
            cmd, args = line.split(' ', 1)
        else:
            cmd = line

        # Send messages to the server when the user types things.
        request_arg = -1
        if cmd in ['l', 'list']:
            print 'The user asked for list.'
            request_type = 0

        if cmd in ['p', 'play']:
            print 'The user asked to play:', args
            request_type = 1
            request_arg = args

            if current_song != int(args) and int(args) < number_of_songs:
                current_song = int(args)
            else:
                request_type = -1

            if int(args) >= number_of_songs or int(args) < 0:
                print("Please give a valid song number!  Use list if you'd like")

        if cmd in ['s', 'stop']:
            print 'The user asked for stop.'
            request_type = 2
            current_song = -1

        if cmd in ['quit', 'q', 'exit']:
            packet = {}
            packet["type"] = "client_shutdown"
            sock.sendall(pickle.dumps(packet)) 
            sys.exit(0)

        if request_type > -1:
            # Create packet to send        
            packet = {}
            packet["type"] = "client_request"
            packet["msg"] = str(request_type)+str(request_arg)
            packet["len"] = len(packet["msg"])
            packet["last"] = True
            packet["seq"] = 0
            sock.sendall(pickle.dumps(packet)) 

        # If LIST, then give time to list the list before prompting for new input
        if request_type == 0:
            sleep(0.2)

        request_type = -1

if __name__ == '__main__':
    main()
