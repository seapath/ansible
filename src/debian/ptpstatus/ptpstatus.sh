#!/bin/bash

#------------------------------------------------------------------------------
# Project : Virtual Merging Unit - Driver for legacy SASensor hardware
# Company : (C) Copyright 2021, Locamation B.V.
# Function: Linux shell script reading the status of the PTP client with pmc 
#           and storing the result into a status file.
#
#  Any reproduction without written permission is prohibited by law.
#------------------------------------------------------------------------------

set -e
set -u

# Global variables
declare -i PTP_STAT_PREV=0
declare -i CLOCK_NO_SYNC=0
declare -i CLOCK_LOCAL_SYNC=1
declare -i CLOCK_GLOBAL_SYNC=2

PTP_STAT_FILE=""
PMC_EXE="/usr/sbin/pmc"

PTP_STAT_GMPRESENT="none"
PTP_STAT_CLOCK_CLASS="none"
PTP_STAT_CLOCK_ACCURACY="none"

declare -i CLOCK_CLASS_MIN=7 # The minimum requirement for the best clock
declare -i CLOCK_MIN_ACCURACY=0x23 # 0x23: the time is accurate to within 1 us

# Error checks
if [[ $# -ne 2 ]]; then
  echo "ERROR: PTP status and details output files not specified!"
  exit 1
fi

PTP_STAT_FILE="$1"
PTP_DETAILS_FILE="$2"

# Initialize this script and perform some condition checks
function init() {
  if [[ ! -f "$PMC_EXE" ]]; then
    echo "ERROR: linuxptp pmc application ($PMC_EXE) does not exist on this platform."
    exit 1
  fi

  ptpStatusFileDir="$(dirname "$PTP_STAT_FILE" 2> /dev/null)"
  ptpDetailsFileDir="$(dirname "$PTP_DETAILS_FILE" 2> /dev/null)"

  mkdir -p "$ptpStatusFileDir"
  mkdir -p "$ptpDetailsFileDir"

  # Write initially 0 into the stat file
  echo "$PTP_STAT_PREV" > "$PTP_STAT_FILE"
  echo "PTP status write; $PTP_STAT_PREV > '$PTP_STAT_FILE'"
}

# Gather and analyse the PTP client status using pmc, and return the status according
# to the iec61850 standard description.
function getPtpStatus() {
  local resultVar=$1
  local clockClassInSpec="true"
  local pmcOutput=""
  local -i ptpStatus=$CLOCK_NO_SYNC

  pmcOutput="$($PMC_EXE -s /var/run/timemaster/ptp4l.0.socket -u -b 0 'GET PARENT_DATA_SET' 'GET TIME_STATUS_NP' 'GET PORT_DATA_SET')"
  echo "$pmcOutput" > "$PTP_DETAILS_FILE"
  
  PTP_STAT_GMPRESENT=$(echo "$pmcOutput" | grep 'gmPresent'| tr -d '\t' | tr -s ' ' | cut -f2 -d " ")
  PTP_STAT_CLOCK_CLASS=$(echo "$pmcOutput" | grep 'gm.ClockClass'| tr -d '\t' | tr -s ' ' | cut -f2 -d " ")
  PTP_STAT_CLOCK_ACCURACY=$(echo "$pmcOutput" | grep 'gm.ClockAccuracy'| tr -d '\t' | tr -s ' ' | cut -f2 -d " ")

  # Determine whether the Clock Class is not out of spec (even when gmPresent=true)
  if [[ "$PTP_STAT_CLOCK_CLASS" == "52"  || "$PTP_STAT_CLOCK_CLASS" == "58" ||
        "$PTP_STAT_CLOCK_CLASS" == "187" || "$PTP_STAT_CLOCK_CLASS" == "193" ]]; then
    clockClassInSpec=false
  fi

  if [ "${PTP_STAT_GMPRESENT,,}" == "true" -a "$clockClassInSpec" = true ]; then
    ptpStatus=$CLOCK_LOCAL_SYNC

    # Swap the following line when clock accuracy is needed:
    #if [ $PTP_STAT_CLOCK_CLASS -le $CLOCK_CLASS_MIN -a $((PTP_STAT_CLOCK_ACCURACY)) -le $((CLOCK_MIN_ACCURACY)) ]; then
    if [[ $PTP_STAT_CLOCK_CLASS -le $CLOCK_CLASS_MIN ]]; then
      ptpStatus=$CLOCK_GLOBAL_SYNC
    fi
  fi

  eval $resultVar="'$ptpStatus'"
}

# Main while loop
function run() {
  while true
  do
    sleep 1
    getPtpStatus status
    setPtpStatus $status
  done
}

# Write the given value into the PTP status file
function setPtpStatus() {
  local currentPtpStat=$1

  if [[ $PTP_STAT_PREV -ne $currentPtpStat ]]; then
    echo "PTP status new; gmPresent: $PTP_STAT_GMPRESENT, gm.ClockClass: $PTP_STAT_CLOCK_CLASS, gm.ClockAccuracy: $PTP_STAT_CLOCK_ACCURACY"
    echo "PTP status write; $PTP_STAT_PREV -> $currentPtpStat > '$PTP_STAT_FILE'"
    echo "$1" > "$PTP_STAT_FILE"

    PTP_STAT_PREV=$currentPtpStat
  fi
}

init
run

