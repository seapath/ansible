#!/usr/bin/env python3
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import socket,sys
from time import sleep
from _thread import start_new_thread

CID = socket.VMADDR_CID_HOST
PORT = int(sys.argv[1])

def client_handler(connection):
    data = connection.recv(2048)
    message = data.decode('utf-8')
    filename = ""
    if message == 'STATUS':
        filename = "/var/run/ptpstatus/ptp_state"
    if message == 'DETAILS':
        filename = "/var/run/ptpstatus/ptp_status"

    ptp_data = "0"
    try:
        with open(filename, "r", encoding="utf-8") as file:
            ptp_data = file.read()
    except FileNotFoundError:
        print(f'PTP {message} file not found, returning default sync state ({ptp_data})')

    connection.sendall(ptp_data.encode("utf-8"))
    connection.close()

def accept_connections(s):
    (conn, (remote_cid, remote_port)) = s.accept()
    print(f'Connected to: {remote_cid}:{str(remote_port)}')
    start_new_thread(client_handler, (conn, ))

def start_server(host, port):
    with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as s:
        while True:
            try:
                s.bind((host, port))
                s.listen()
            except socket.error:
                sleep(5)
                continue
            break
        print(f'Server is listing on the port {port}...')
        while True:
            accept_connections(s)

start_server(CID, PORT)
