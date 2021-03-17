#!/bin/bash
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# Name:       print_usage
# Brief:      Print script usage
print_usage()
{
    echo "This script drives a EG-PMS2-LAN power supply
./$(basename ${0}) [OPTIONS]
Options:
        (--ip)          <ip>            Ip of the power supply
        (--password)    <password>      Password to use
        (--port)        <port>          Port to use
        (--state)       <state>         State to set
        (--status)		                Status of the port
        (-h|--help)                     Display this help message
        "
}
# Name:       parse_options
# Brief:      Parse options from command line
# Param[in]:  Command line parameters
parse_options()
{
    #TODO: Add an option for not cleaning build directory
    ARGS=$(getopt -o "h" -l "ip:,help,password:,port:,state:,status" -n "power.sh" -- "$@")
    #Bad arguments
    if [ $? -ne 0 ]; then
        exit 1
    fi
    eval set -- "${ARGS}"
    while true; do
        case "$1" in
            --ip)
                export IP=$2
                shift 2
                ;;
            --password)
                export PASSWORD=$2
                shift 2
                ;;
            --port)
                export PORT=$2
                shift 2
                ;;
            --state)
                export STATE=$2
                shift 2
                ;;
            --status)
                export STATUS=1
                shift 1
                ;;
            -h|--help)
                print_usage
                exit 1
                shift
                break
                ;;
            -|--)
                shift
                break
                ;;
            *)
                print_usage
                exit 1
                shift
                break
                ;;
        esac
    done
}
ping_plug(){
    local ip=$1
    ping -q -c1 $ip >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        return 1
    else
        return 0
    fi
}
login() {
    local ip=$1
    local passwd=$2
    curl -X POST -sd 'pw='$passwd'' http://$ip/login.html >/dev/null 2>&1
    is_login=1
}
get_status() {
    local ip=$1
    local passwd=$2
	local port=$3
    if [ ! $is_login ]; then
        login $ip $passwd
    fi
    if ping_plug $IP; then
        echo "$IP can not be ping"
        exit
    fi
	pos=$((port * 2))
    curl -s http://$ip/status.html | sed -e 's,.*var ctl = ,,' -e 's,var tod.*,,' | cut -c $pos- | cut -c -1
}
power() {
    local ip=$1
    local passwd=$2
    local port=$3
    local state=$4
    echo "setting $ip[$port] to $state"

    if [ ! $is_login ]; then
        login $ip $passwd
    fi
    if ping_plug $IP; then
        echo "$IP can not be ping"
        exit
    fi
    if [ "$state" = "off" ]; then
        curl -sd 'cte'$port'=0' http://$ip >/dev/null 2>&1
    elif [ "$state" = "on" ]; then
        curl -sd 'cte'$port'=1' http://$ip >/dev/null 2>&1
    else
        echo "wrong state set"
        exit 1
    fi
}
# Parse options
parse_options "${@}"
if [ ! "$IP" == "" ] && [ ! "$PASSWORD" == "" ] &&  [ ! "$PORT" == "" ] && [ ! "$STATUS" == "" ]; then
    get_status $IP $PASSWORD $PORT
elif [ ! "$IP" == "" ] && [ ! "$PASSWORD" == "" ] && [ ! "$PORT" == "" ] && [ ! "$STATE" == "" ]; then
    power $IP $PASSWORD $PORT $STATE
else
    echo "missing arguments"
    print_usage
    exit
fi
