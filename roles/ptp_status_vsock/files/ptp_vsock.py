#!/usr/bin/env python3
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import socket,sys
from time import sleep
from _thread import *

CID = socket.VMADDR_CID_HOST
PORT = int(sys.argv[1])

def client_handler(connection):
    data = connection.recv(2048)
    message = data.decode('utf-8')
    if message == 'STATUS':
      file = open("/var/run/ptpstatus/ptp_state", "r")
    if message == 'DETAILS':
      file = open("/var/run/ptpstatus/ptp_status", "r")
    data = file.read()
    connection.sendall(data.encode("utf-8"))
    connection.close()

def accept_connections(s):
    (conn, (remote_cid, remote_port)) = s.accept()
    print(f'Connected to: {remote_cid}:{str(remote_port)}')
    start_new_thread(client_handler, (conn, ))

def start_server(host, port):
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    while True:
        try:
            s.bind((host, port))
            s.listen()
        except socket.error as e:
            sleep(5)
            continue
        break
    print(f'Server is listing on the port {port}...')
    while True:
        accept_connections(s)

start_server(CID, PORT)
